from django.contrib import admin
from .models import Cliente, Frasco, Pedido, PagamentoAvulso, Transferencia

# Customizando a exibição dos pedidos para ficar igual à sua planilha
@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'frasco', 'quantidade_ml', 'valor_total', 'pago', 'data_pedido', 'observacao')
    list_filter = ('pago', 'frasco')
    search_fields = ('cliente__nome', 'frasco__nome_perfume')
    list_editable = ('pago',) # Permite clicar no checkbox direto na lista!

# Registrando os outros modelos mais simples
admin.site.register(Cliente)
admin.site.register(PagamentoAvulso)

@admin.register(Frasco)
class FrascoAdmin(admin.ModelAdmin):
    list_display = ('nome_perfume', 'marca', 'preco_ml', 'ml_total', 'ml_disponiveis', 'status', 'data_abertura')
    list_editable = ('ml_disponiveis', 'status')
    search_fields = ('nome_perfume', 'marca')
    list_filter = ('status',)

@admin.register(Transferencia)
class TransferenciaAdmin(admin.ModelAdmin):
    list_display = ('frasco', 'pedido_cedente', 'pedido_destinatario', 'quantidade_ml', 'data')
    search_fields = ('pedido_cedente__cliente__nome', 'pedido_destinatario__cliente__nome')