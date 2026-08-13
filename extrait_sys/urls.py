from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # Página inicial → /importar/
    path("", RedirectView.as_view(url="/importar/", permanent=False)),

    # Admin
    path("admin/", admin.site.urls),

    # App operacao (todas as rotas do negócio)
    path("", include("operacao.urls")),
]