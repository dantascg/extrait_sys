from django.db import models
from decimal import Decimal

class Cliente(models.Model):
    nome = models.CharField(max_length=150, unique=True, verbose_name="Nome no WhatsApp")
    telefone = models.CharField(max_length=20, blank=True, null=True)
    data_cadastro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome

class Frasco(models.Model):
    nome_perfume = models.CharField(max_length=200)
    marca = models.CharField(max_length=100, blank=True, null=True)
    preco_ml = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço por ML (R$)")
    ml_total = models.IntegerField(null=True, blank=True, verbose_name="Volume total (ML)")
    ml_disponiveis = models.IntegerField(null=True, blank=True, verbose_name="ML disponíveis")
    link_fragrantica = models.URLField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=[('ABERTO', 'Disponível'), ('FECHADO', 'Fechado/Esgotado')],
        default='ABERTO'
    )
    data_abertura = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nome_perfume} - R$ {self.preco_ml}/ml"

class Pedido(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    frasco = models.ForeignKey(Frasco, on_delete=models.PROTECT)
    quantidade_ml = models.IntegerField(verbose_name="Quantidade (ML)")
    tipo_pedido = models.CharField(
        max_length=20,
        choices=[('SPLIT', 'Split Normal'), ('APC', 'Apresentação Completa')],
        default='SPLIT'
    )
    pago = models.BooleanField(default=False, verbose_name="Pagamento Realizado?")
    observacao = models.TextField(blank=True, null=True, verbose_name="Observação")
    data_pedido = models.DateTimeField(auto_now_add=True)

    @property
    def valor_total(self):
        # Converte a quantidade para Decimal para fazer o cálculo com precisão perfeita
        valor_dos_mls = Decimal(str(self.quantidade_ml)) * self.frasco.preco_ml
        
        # Se for APC, o frasco é grátis (não soma os 6 reais)
        if self.tipo_pedido == 'APC':
            return valor_dos_mls
        else:
            # Transforma os 6.00 reais do vidro recravado em Decimal também!
            return valor_dos_mls + Decimal('6.00')

    def __str__(self):
        status_pagamento = "✅ PAGO" if self.pago else "🔴 PENDENTE"
        return f"[{status_pagamento}] {self.cliente.nome} | {self.frasco.nome_perfume} ({self.quantidade_ml}ml)"

class PagamentoAvulso(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    valor_pago = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor do Pix (R$)")
    data_pagamento = models.DateTimeField(auto_now_add=True)
    observacao = models.TextField(blank=True, null=True, help_text="Ex: Abatimento de dívida antiga da planilha")

    def __str__(self):
        return f"Crédito: {self.cliente.nome} - R$ {self.valor_pago}"


class Transferencia(models.Model):
    frasco = models.ForeignKey(Frasco, on_delete=models.PROTECT)
    pedido_cedente = models.ForeignKey(Pedido, related_name='transferencias_cedidas', on_delete=models.PROTECT)
    pedido_destinatario = models.OneToOneField(Pedido, related_name='transferencia_origem', on_delete=models.PROTECT)
    quantidade_ml = models.IntegerField(verbose_name="ML transferidos")
    data = models.DateTimeField(auto_now_add=True)
    observacao = models.TextField(blank=True)

    def __str__(self):
        return f"{self.pedido_cedente.cliente} → {self.pedido_destinatario.cliente}: {self.quantidade_ml}ml"