"""
ASGI config for the YÉKI project (config/ package).

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/

Le WebSocket du forum est authentifié par jeton, jamais par cookie : un site
tiers ne peut donc pas ouvrir de connexion au nom d'un visiteur, et aucune
validation d'origine n'est nécessaire. `AllowedHostsOriginValidator` serait
même bloquant : il refuse les clients sans en-tête `Origin` (applications
mobiles) et l'origine de l'app web (Firebase Hosting, absente d'ALLOWED_HOSTS).
Voir docs/FORUM_TEMPS_REEL.md.
"""

import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

# Bug réel révélé par le tout premier vrai chargement de ce fichier
# (premier déploiement ASGI, 2026-08-06) — jamais détecté avant puisqu'il n'avait
# jamais tourné en production. `django.setup()` doit être appelé
# EXPLICITEMENT et AVANT tout import qui touche des modèles Django
# (`apps.forum.routing` → `apps.forum.consumers` → modèles) : sans lui, l'app registry n'est pas encore prête
# (`AppRegistryNotReady`) au moment de cet import — `get_asgi_application()`
# déclenche bien un `django.setup()` interne, mais seulement APRÈS avoir été
# appelé, trop tard pour un import de niveau module placé plus haut.
django.setup()

# Imports à garder après django.setup().
from apps.forum.routing import websocket_urlpatterns  # noqa: E402
from apps.forum.ws_auth import JetonSousProtocoleMiddleware  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": JetonSousProtocoleMiddleware(URLRouter(websocket_urlpatterns)),
    }
)
