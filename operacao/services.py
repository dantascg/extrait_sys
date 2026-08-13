"""
services.py — Extrait Club System

Camada de serviços isolada do views.py.
Contém a integração com a API da Groq (LLaMA 3.3 70B) e o matching de clientes.
Não importa nada do Django web (request, render, redirect) — apenas ORM e modelos.
"""

import json
import logging
import os
import re

from groq import Groq

from .models import Cliente

logger = logging.getLogger(__name__)


# =============================================================================
# INTEGRAÇÃO COM A API DO GROQ / LLaMA 3.3 70B
# =============================================================================

_PROMPT_TEMPLATE = """
Você é um extrator de dados.

Retorne APENAS JSON válido.

Formato:

{{
  "perfume": "",
  "marca": "",
  "preco_ml": 0,
  "ml_total": 0,
  "ml_disponiveis": 0,
  "is_fechado": false,
  "link": "",
  "data_envio": "",
  "eventos": [
    {{
      "nome_raw": "",
      "ddd": "",
      "ml": "",
      "tipo": "APC | SPLIT"
    }}
  ]
}}

REGRAS:
- Extraia `ml_total` (tamanho físico, ex: "Frasco 90ML" -> 90) e `ml_disponiveis` (ex: "40 ML disponíveis" -> 40). Se não achar, envie null.
- Verifique se a mensagem indica que o perfume foi fechado (ex: "❌ FECHADO ❌" ou similar). Se sim, defina `is_fechado` como true.
- Separe SEMPRE o "perfume" (apenas aroma) da "marca" (casa de perfumaria), independentemente da formatação ou uso de hífen.
- NORMALIZAÇÃO DA MARCA: identifique a marca a partir desta lista e retorne exatamente como está na lista: Abdul Samad Al Qurashi, Acqua di Parma, Amouage, Argos, Atelier des Ors, BDK Parfums, BLNDRGRPHY, Boadicea the Victorious, By Kilian, Byredo, Carner Barcelona, Clive Christian, Creed, Diptyque, Electimuss, Essential Parfums, Etat Libre d'Orange, Floraiku, Fragrance Du Bois, Francesca Bianchi, Frederic Malle, Goldfield & Banks Australia, Gritti, Guerlain, Histoires de Parfums, Initio Parfums Privés, Juliette Has A Gun, Kemi Blending Magic, Laboratorio Olfattivo, Le Labo, Lorenzo Villoresi, Louis Vuitton, M. Micallef, Maison Crivelli, Maison Francis Kurkdjian, Maison Margiela, Mancera, Matiere Premiere, Memo Paris, Mind Games, Montale, Narcotica, Nasomatto, New Notes, Nishane, Orto Parisi, Parfums de Marly, Penhaligon's, Puredistance, Ramon Monegal, Regalien, Roja Parfums, Rosendo Mateu, Santa Maria Novella, Serge Lutens, Sospiro Perfumes, Spirit Of Kings, Stephane Humbert Lucas 777, Thameen, Tiziana Terenzi, Unique & Luxury, Vilhelm Parfumerie, Xerjoff, Yves Saint Laurent, Zoologist Perfumes.
- APC sem número = "APC_DEFAULT"
- NÃO agrupar clientes
- NÃO interpretar intenção
- NÃO calcular nada
- Quando houver multiplicadores como:

2x 10ML
3x 5ML
4x 2ML

NÃO some os valores.

Retorne um evento separado para cada unidade.

Exemplo:

Entrada:
Maurício Silva 2x 10ML

Saída:

[
 {{ "nome_raw":"Maurício Silva","ml":10,"tipo":"SPLIT"}},
 {{ "nome_raw":"Maurício Silva","ml":10,"tipo":"SPLIT"}}
]

Nunca transforme em:

"20ML"

TEXTO:
{texto_bruto}
"""


def extrair_dados_ia(texto_bruto: str) -> dict:
    """
    Envia o texto bruto do WhatsApp para o LLaMA 3.3 70B via Groq
    e retorna o dicionário de dados estruturado.

    Raises:
        ValueError: Se a resposta da IA não for JSON válido.
        RuntimeError: Se a chamada à API do Groq falhar.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não configurada no ambiente.")

    prompt = _PROMPT_TEMPLATE.format(texto_bruto=texto_bruto)

    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_completion_tokens=4000,
        )
    except Exception as exc:
        logger.exception("Falha na chamada à API do Groq: %s", exc)
        raise RuntimeError(f"Erro ao contatar a API de IA: {exc}") from exc

    raw = completion.choices[0].message.content.strip()
    logger.debug("Resposta bruta do Groq recebida (%d chars).", len(raw))

    # Remove blocos de código Markdown caso o modelo os inclua
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        dados = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Resposta da IA não é JSON válido. Conteúdo: %s", raw[:500])
        raise ValueError(
            "A resposta da IA não pôde ser interpretada como JSON. "
            "Tente novamente ou ajuste o texto de entrada."
        ) from exc

    logger.debug(
        "Dados extraídos com sucesso: %d evento(s).", len(dados.get("eventos", []))
    )
    return dados


# =============================================================================
# MATCHING DE CLIENTE
# =============================================================================

def detectar_cliente(item: dict) -> tuple:
    """
    Tenta encontrar um Cliente correspondente ao nome extraído pela IA.

    Retorna:
        (cliente, status, sugestoes)
        - status "ok"       → match exato encontrado
        - status "conflito" → múltiplas sugestões, requer resolução humana
        - status "novo"     → nenhum match, será criado como novo cliente
    """
    from django.db.models import Q

    nome = item["nome_raw"].strip()

    # 1. Match exato (case-insensitive)
    cliente = Cliente.objects.filter(nome__iexact=nome).first()
    if cliente:
        logger.debug("Match exato para '%s' → Cliente ID %d.", nome, cliente.id)
        return cliente, "ok", []

    # 2. Busca aproximada por palavras significativas
    nome_limpo = re.sub(r"[^a-zA-ZÀ-ÿ\s]", "", nome)
    palavras = [p for p in nome_limpo.split() if len(p) > 2]

    if not palavras:
        logger.debug("Nenhuma palavra significativa em '%s' — tratando como novo.", nome)
        return None, "novo", []

    query = Q()
    for p in palavras:
        query |= Q(nome__istartswith=p) | Q(nome__icontains=f" {p}")

    sugestoes = Cliente.objects.filter(query).distinct()[:5]

    if sugestoes:
        logger.debug(
            "Conflito para '%s': %d sugestão(ões) encontrada(s).",
            nome,
            len(sugestoes),
        )
        return None, "conflito", list(sugestoes.values("id", "nome"))

    logger.debug("Nenhum match para '%s' — será registrado como novo.", nome)
    return None, "novo", []
