# Toutes les vues ont été déplacées vers les apps/{core,accounts,formation,
# evaluation,forum,paiement,ia,notifications,repetiteurs}/views.py (voir
# docs/SPLIT_VIEWS.md). Conservé, réduit à un ré-export minimal, uniquement
# pour ne pas casser l'ancien urlconf racine `yeki_backend/urls.py`
# (non actif — ROOT_URLCONF pointe vers `config.urls`), qui fait encore
# `from yeki.views import landing`.
from apps.core.views import landing  # noqa: F401,E402
