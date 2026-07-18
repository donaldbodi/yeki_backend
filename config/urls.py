"""
URL configuration for the YÉKI project (config/ package).

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from apps.core.views import landing

urlpatterns = [
    path("", landing, name="landing"),
    path("admin/", admin.site.urls),
    # ── Documentation API (P1.6) ────────────────────────────────────────────
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/", include("apps.core.urls")),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.formation.urls")),
    path("api/", include("apps.evaluation.urls")),
    path("api/", include("apps.forum.urls")),
    path("api/", include("apps.paiement.urls")),
    path("api/", include("apps.ia.urls")),
    path("api/", include("apps.notifications.urls")),
    path("api/", include("apps.repetiteurs.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
