from django.urls import include, path

# Toutes les routes vivent désormais dans les urls.py des 9 apps (voir
# docs/SPLIT_VIEWS.md) ; config/urls.py les inclut directement et n'utilise
# plus ce module. Conservé, réduit à une simple ré-inclusion, uniquement pour
# ne pas casser l'ancien urlconf racine `yeki_backend/urls.py` (non actif —
# ROOT_URLCONF pointe vers `config.urls` depuis la restructuration en apps),
# qui fait encore `include('yeki.urls')`.
urlpatterns = [
    path('', include('apps.core.urls')),
    path('', include('apps.accounts.urls')),
    path('', include('apps.formation.urls')),
    path('', include('apps.evaluation.urls')),
    path('', include('apps.forum.urls')),
    path('', include('apps.paiement.urls')),
    path('', include('apps.ia.urls')),
    path('', include('apps.notifications.urls')),
    path('', include('apps.repetiteurs.urls')),
]
