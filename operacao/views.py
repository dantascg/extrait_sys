import logging

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone
import datetime

from .models import Cliente, Frasco, Pedido, Transferencia
from .services import detectar_cliente, extrair_dados_ia

logger = logging.getLogger(__name__)


# =============================================================================
# IMPORTAÇÃO — ESTADO 1: chama a IA e monta o rascunho na sessão
# =============================================================================
def importar_leilao(request):
    if request.method != "POST":
        trinta_dias_atras = timezone.now() - datetime.timedelta(days=30)
        frascos_recentes_count = Frasco.objects.filter(data_abertura__gte=trinta_dias_atras).count()
        clientes_com_saldo = Pedido.objects.filter(pago=False).values('cliente').distinct().count()

        stats_dashboard = {
            'total_frascos': Frasco.objects.count(),
            'decants_abertos': Frasco.objects.filter(status='ABERTO').count(),
            'importados_recentemente': frascos_recentes_count,
            'estoque_baixo': Frasco.objects.filter(ml_disponiveis__lte=10, status='ABERTO').count(),
            'clientes_pendentes': clientes_com_saldo,
        }
        
        frascos_recentes = Frasco.objects.all().order_by("-id")[:5]
        frascos_abertos = Frasco.objects.filter(status='ABERTO').annotate(num_pedidos=Count('pedido')).order_by('-data_abertura')

        return render(request, "operacao/importar.html", {
            "stats_dashboard": stats_dashboard,
            "frascos_recentes": frascos_recentes,
            "frascos_abertos": frascos_abertos,
        })

    texto = request.POST.get("texto_leilao", "").strip()
    if not texto:
        return render(request, "operacao/importar.html", {
            "resultado": "Insira o texto do leilão antes de processar."
        })

    try:
        dados = extrair_dados_ia(texto)
        logger.debug("Dados extraídos pela IA: %d evento(s).", len(dados.get("eventos", [])))

        frasco_nome = f"{dados['perfume']} - {dados['marca']}"

        frasco = Frasco.objects.filter(nome_perfume=frasco_nome).first()
        if frasco and Pedido.objects.filter(frasco=frasco, pago=False).exists():
            return render(request, "operacao/importar.html", {
                "resultado": "Já existe leilão ativo para este perfume."
            })

        dados["compras"] = dados.pop("eventos")
        tem_conflito = False

        for item in dados["compras"]:
            cliente, status, sugestoes = detectar_cliente(item)
            item["status"] = status
            item["sugestoes"] = sugestoes
            item["nome"] = item["nome_raw"]
            if status == "conflito":
                tem_conflito = True

        # ── Armazena o rascunho na sessão (servidor) — nada trafega no DOM ──
        request.session["dados_leilao_pendente"] = dados

        return render(request, "operacao/importar.html", {
            "dados_resumo": dados,
            "tem_conflito": tem_conflito,
        })

    except (ValueError, RuntimeError) as exc:
        logger.warning("Erro controlado ao processar leilão: %s", exc)
        return render(request, "operacao/importar.html", {
            "resultado": str(exc)
        })
    except Exception as exc:
        logger.exception("Erro inesperado ao processar leilão.")
        return render(request, "operacao/importar.html", {
            "resultado": f"Erro inesperado ao processar mensagem: {exc}"
        })


# =============================================================================
# IMPORTAÇÃO — ESTADO 2: confirmação e persistência atômica
# =============================================================================
@require_POST
@transaction.atomic
def confirmar_importacao(request):
    dados = request.session.pop("dados_leilao_pendente", None)

    if dados is None:
        logger.warning("Tentativa de confirmar importação sem sessão ativa.")
        return render(request, "operacao/importar.html", {
            "resultado": "Sessão expirada ou inválida. Reimporte o texto do leilão."
        })

    frasco_nome = dados['perfume'].strip()
    frasco_marca = dados['marca'].strip()
    
    frasco = Frasco.objects.filter(nome_perfume__iexact=frasco_nome).first()
    if not frasco:
        frasco = Frasco.objects.create(
            nome_perfume=frasco_nome,
            marca=frasco_marca,
            preco_ml=dados["preco_ml"],
            ml_total=dados.get("ml_total"),
            ml_disponiveis=dados.get("ml_disponiveis"),
            status="ABERTO"
        )
        logger.info("Novo frasco criado: '%s' (R$ %s/ml).", frasco_nome, dados["preco_ml"])

    for i, item in enumerate(dados.get("compras", [])):
        resolucao = request.POST.get(f"resolucao_{i}")

        # 1. Operador vinculou a um cliente existente
        if resolucao and resolucao != "novo":
            try:
                cliente = Cliente.objects.get(id=int(resolucao))
            except (Cliente.DoesNotExist, ValueError):
                # ID inválido — cria novo como fallback seguro
                cliente, _ = Cliente.objects.get_or_create(
                    nome=item["nome_raw"].strip()
                )
        # 2. Criar novo, ou era match perfeito / cliente novo sem conflito
        else:
            nome = item["nome_raw"].strip()
            cliente = Cliente.objects.filter(nome__iexact=nome).first()
            if not cliente:
                cliente = Cliente.objects.create(nome=nome)

        Pedido.objects.create(
            cliente=cliente,
            frasco=frasco,
            quantidade_ml=item["ml"],
            tipo_pedido=item["tipo"],
            pago=False,
        )

    # Atualiza status baseado na IA
    if dados.get("is_fechado", False):
        frasco.status = "FECHADO"
        frasco.save()
        
    request.session.modified = True

    logger.info(
        "Importação confirmada: %d pedido(s) criado(s) para o frasco '%s'.",
        len(dados.get("compras", [])),
        frasco_nome,
    )
    messages.success(request, f"Leilão de {frasco_nome} confirmado com sucesso!")
    return redirect("operacao:importar_leilao")


# =============================================================================
# PAINEL DE COBRANÇAS
# =============================================================================
def painel_cobranca(request):
    pedidos = Pedido.objects.filter(pago=False).select_related("cliente", "frasco")

    cobrancas = {}

    for p in pedidos:
        nome = p.cliente.nome

        if nome not in cobrancas:
            cobrancas[nome] = {
                "cliente_id": p.cliente.id,
                "itens": [],
                "total_geral": 0,
            }

        cobrancas[nome]["itens"].append({
            "perfume": p.frasco.nome_perfume,
            "ml": p.quantidade_ml,
            "valor": float(p.valor_total),
            "tipo": p.tipo_pedido,
            "preco_ml": float(p.frasco.preco_ml),
        })

        cobrancas[nome]["total_geral"] += float(p.valor_total)

    return render(request, "operacao/cobranca.html", {"cobrancas": cobrancas})


@require_POST
def dar_baixa_pagamento(request, cliente_id):
    count = Pedido.objects.filter(cliente_id=cliente_id, pago=False).update(pago=True)
    logger.info("Baixa em lote: %d pedido(s) marcados como pagos (cliente_id=%d).", count, cliente_id)
    return redirect("operacao:painel_cobranca")


# =============================================================================
# LISTA DE CLIENTES
# =============================================================================
def lista_clientes(request):
    query = request.GET.get("q", "").strip()

    clientes_qs = Cliente.objects.annotate(
        total_pedidos=Count("pedido")
    ).order_by("nome")

    if query:
        clientes_qs = clientes_qs.filter(
            Q(nome__icontains=query) | Q(id__icontains=query)
        )

    # Busca todos os pedidos pendentes de uma vez — uma query só
    pedidos_pendentes = (
        Pedido.objects
        .filter(cliente__in=clientes_qs, pago=False)
        .select_related("frasco")
    )

    # Agrupa por cliente_id em memória
    saldos = {}
    for p in pedidos_pendentes:
        saldos[p.cliente_id] = saldos.get(p.cliente_id, 0) + float(p.valor_total)

    # Monta lista e stats em um único loop
    clientes_list = []
    pendentes_count = 0
    ativos_count = 0

    for c in clientes_qs:
        saldo = saldos.get(c.id, 0)

        if saldo > 0:
            status = "PENDING"
            pendentes_count += 1
        elif c.total_pedidos > 0:
            status = "ACTIVE"
            ativos_count += 1
        else:
            status = "EMPTY"

        clientes_list.append({
            "id": c.id,
            "nome": c.nome,
            "saldo_pendente": saldo,
            "status": status,
            "ultima_atividade": "Sem atividade" if c.total_pedidos == 0 else "Recente",
        })

    total_clientes = Cliente.objects.count()

    stats = {
        "total": total_clientes,
        "pendentes": pendentes_count,
        "ativos": ativos_count,
        "vazios": total_clientes - pendentes_count - ativos_count,
    }

    return render(request, "operacao/clientes.html", {
        "clientes": clientes_list,
        "stats": stats,
        "query": query,
    })


# =============================================================================
# DETALHE DO CLIENTE
# =============================================================================
def detalhe_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)

    # Todos os pedidos do cliente — materializado em lista para evitar
    # dupla avaliação do queryset nas métricas abaixo
    todos_pedidos = list(
        Pedido.objects.filter(cliente=cliente).select_related("frasco")
    )

    # Métricas calculadas em memória (sem queries extras)
    saldo_pendente = sum(float(p.valor_total) for p in todos_pedidos if not p.pago)
    total_gasto    = sum(float(p.valor_total) for p in todos_pedidos if p.pago)
    total_pedidos  = len(todos_pedidos)

    # Pedidos filtrados para exibição (respeita filtro por frasco)
    frasco_filtro = request.GET.get("frasco")

    if frasco_filtro:
        pedidos_exibidos = [p for p in todos_pedidos if str(p.frasco_id) == frasco_filtro]
    else:
        pedidos_exibidos = todos_pedidos

    # Ordenação: frasco mais recente primeiro, depois pedido mais recente
    pedidos_exibidos.sort(
        key=lambda p: (p.frasco.data_abertura, p.data_pedido), reverse=True
    )

    # Agrupa pedidos por frasco para exibição
    frascos_dict = {}
    for p in pedidos_exibidos:
        fid = p.frasco.id
        if fid not in frascos_dict:
            frascos_dict[fid] = {"frasco": p.frasco, "pedidos": []}
        frascos_dict[fid]["pedidos"].append(p)

    # Lista de frascos para o filtro (todos os que o cliente já comprou)
    frascos_do_cliente = (
        Frasco.objects
        .filter(pedido__cliente=cliente)
        .distinct()
        .order_by("-data_abertura")
    )

    # Transferências do cliente
    transferencias_cedidas = Transferencia.objects.filter(pedido_cedente__cliente=cliente).select_related('frasco', 'pedido_destinatario__cliente').order_by('-data')
    transferencias_recebidas = Transferencia.objects.filter(pedido_destinatario__cliente=cliente).select_related('frasco', 'pedido_cedente__cliente').order_by('-data')

    return render(request, "operacao/detalhe_cliente.html", {
        "cliente": cliente,
        "frascos_agrupados": list(frascos_dict.values()),
        "frascos_do_cliente": frascos_do_cliente,
        "frasco_filtro": frasco_filtro,
        "saldo_pendente": saldo_pendente,
        "total_gasto": total_gasto,
        "total_pedidos": total_pedidos,
        "transferencias_cedidas": transferencias_cedidas,
        "transferencias_recebidas": transferencias_recebidas,
    })


# =============================================================================
# EDITAR NOME DO CLIENTE
# =============================================================================
@require_POST
def editar_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)
    novo_nome = request.POST.get("nome", "").strip()
    if novo_nome:
        cliente.nome = novo_nome
        cliente.save()
        logger.info("Nome do cliente ID %d atualizado para '%s'.", cliente_id, novo_nome)
    return redirect("operacao:detalhe_cliente", cliente_id=cliente_id)


# =============================================================================
# DAR BAIXA EM PEDIDO INDIVIDUAL
# =============================================================================
@require_POST
def baixa_pedido_individual(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    cliente_id = pedido.cliente.id
    pedido.pago = True
    pedido.save()
    logger.info("Pedido ID %d marcado como pago (cliente_id=%d).", pedido_id, cliente_id)
    return redirect("operacao:detalhe_cliente", cliente_id=cliente_id)


# =============================================================================
# PERFUMES
# =============================================================================
def lista_perfumes(request):
    is_estoque_baixo = 'estoque-baixo' in request.path
    
    if is_estoque_baixo:
        frascos = Frasco.objects.filter(ml_disponiveis__lte=10, status='ABERTO').prefetch_related('pedido_set__cliente').order_by('nome_perfume', '-data_abertura')
    else:
        frascos = Frasco.objects.all().prefetch_related('pedido_set__cliente').order_by('nome_perfume', '-data_abertura')
        
    perfumes_dict = {}
    for f in frascos:
        if f.nome_perfume not in perfumes_dict:
            perfumes_dict[f.nome_perfume] = {
                'nome': f.nome_perfume,
                'marca': f.marca,
                'aberturas': []
            }
        perfumes_dict[f.nome_perfume]['aberturas'].append(f)
        
    return render(request, "operacao/perfumes.html", {
        "perfumes": perfumes_dict.values(),
        "is_estoque_baixo": is_estoque_baixo
    })

def detalhe_perfume(request, nome_perfume):
    frascos = Frasco.objects.filter(nome_perfume=nome_perfume).prefetch_related('pedido_set__cliente').order_by('-data_abertura')
    if not frascos.exists():
        return redirect('operacao:lista_perfumes')
        
    perfume = {
        'nome': frascos.first().nome_perfume,
        'marca': frascos.first().marca,
        'aberturas': list(frascos)
    }
    
    return render(request, "operacao/detalhe_perfume.html", {
        "perfume": perfume,
        "clientes_lista": Cliente.objects.all().order_by('nome')
    })

@require_POST
@transaction.atomic
def transferir_ml(request, pedido_id):
    pedido_cedente = get_object_or_404(Pedido, id=pedido_id)
    
    try:
        quantidade_ml = int(request.POST.get('quantidade_ml', 0))
        cliente_destinatario_id = int(request.POST.get('destinatario_id'))
        observacao = request.POST.get('observacao', '').strip()
    except (ValueError, TypeError):
        messages.error(request, "Dados inválidos para a transferência.")
        return redirect(request.META.get('HTTP_REFERER', 'operacao:lista_perfumes'))
        
    if quantidade_ml <= 0:
        messages.error(request, "A quantidade deve ser maior que zero.")
        return redirect(request.META.get('HTTP_REFERER', 'operacao:lista_perfumes'))
        
    if pedido_cedente.quantidade_ml <= quantidade_ml:
        messages.error(request, f"Quantidade a ceder ({quantidade_ml}ml) deve ser menor que o total ({pedido_cedente.quantidade_ml}ml).")
        return redirect(request.META.get('HTTP_REFERER', 'operacao:lista_perfumes'))
        
    if pedido_cedente.cliente.id == cliente_destinatario_id:
        messages.error(request, "O destinatário não pode ser o mesmo que o cedente.")
        return redirect(request.META.get('HTTP_REFERER', 'operacao:lista_perfumes'))
        
    cliente_destinatario = get_object_or_404(Cliente, id=cliente_destinatario_id)
    
    # Efetua transferência
    pedido_cedente.quantidade_ml -= quantidade_ml
    if not pedido_cedente.observacao:
        pedido_cedente.observacao = ""
    pedido_cedente.observacao += f" Cedeu {quantidade_ml}ml para {cliente_destinatario.nome}"
    pedido_cedente.save()
    
    novo_pedido = Pedido.objects.create(
        cliente=cliente_destinatario,
        frasco=pedido_cedente.frasco,
        quantidade_ml=quantidade_ml,
        tipo_pedido='SPLIT',
        pago=False,
        observacao=f"Recebido por transferência de {pedido_cedente.cliente.nome}",
    )
    
    Transferencia.objects.create(
        frasco=pedido_cedente.frasco,
        pedido_cedente=pedido_cedente,
        pedido_destinatario=novo_pedido,
        quantidade_ml=quantidade_ml,
        observacao=observacao,
    )
    
    messages.success(request, f"Transferência de {quantidade_ml}ml para {cliente_destinatario.nome} realizada com sucesso.")
    return redirect(request.META.get('HTTP_REFERER', 'operacao:lista_perfumes'))
