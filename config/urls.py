"""
URL configuration for the YÉKI project (config/ package).

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
"""

from django.conf import settings
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve as serve_static
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
    # Bug corrigé (CORS sur les médias forum/leçons en production) :
    # `django.conf.urls.static.static()` ne génère AUCUNE route dès que
    # `DEBUG=False` (comportement documenté de Django, par sécurité/perf —
    # voir sa source : `if not settings.DEBUG: return []`). En production,
    # `/media/...` est donc actuellement servi entièrement par le mapping
    # de fichiers statiques de PythonAnywhere (hors de Django), qui ne
    # transmet JAMAIS les en-têtes CORS (confirmé en prod : la console
    # navigateur montre « No 'Access-Control-Allow-Origin' header is
    # present » précisément sur ces requêtes média, alors que les mêmes
    # requêtes vers `/api/...` reçoivent bien leurs en-têtes CORS via
    # `CorsMiddleware`). Route explicite, systématique (pas conditionnée
    # par `DEBUG`), pour que ces requêtes passent enfin par Django/
    # `CorsMiddleware` — nécessite EN PLUS de retirer/ajuster le mapping
    # `/media/` du tableau de bord PythonAnywhere (onglet Web → Static
    # files), sans quoi PythonAnywhere continue d'intercepter ces requêtes
    # avant qu'elles n'atteignent Django (hors de portée d'un simple
    # correctif de code, action pour l'utilisateur — voir docs/MIGRATIONS_APPS.md).
    re_path(r"^media/(?P<path>.*)$", serve_static, {"document_root": settings.MEDIA_ROOT}),
]
