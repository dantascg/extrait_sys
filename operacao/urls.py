from django.urls import path

from . import views

app_name = "operacao"

urlpatterns = [
    # Importação
    path("importar/", views.importar_leilao, name="importar_leilao"),
    path("importar/confirmar/", views.confirmar_importacao, name="confirmar_importacao"),

    # Cobranças
    path("cobranca/", views.painel_cobranca, name="painel_cobranca"),
    path("cobranca/baixa/<int:cliente_id>/", views.dar_baixa_pagamento, name="dar_baixa_pagamento"),

    # Clientes
    path("clientes/", views.lista_clientes, name="lista_clientes"),
    path("clientes/<int:cliente_id>/", views.detalhe_cliente, name="detalhe_cliente"),
    path("clientes/<int:cliente_id>/editar/", views.editar_cliente, name="editar_cliente"),

    # Pedidos
    path("pedidos/<int:pedido_id>/baixa/", views.baixa_pedido_individual, name="baixa_pedido_individual"),
    path("pedidos/<int:pedido_id>/transferir/", views.transferir_ml, name="transferir_ml"),

    # Perfumes
    path("perfumes/", views.lista_perfumes, name="lista_perfumes"),
    path("perfumes/estoque-baixo/", views.lista_perfumes, name="estoque_baixo"),
    path("perfumes/nome/<str:nome_perfume>/", views.detalhe_perfume, name="detalhe_perfume"),
]