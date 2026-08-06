"""
ASGI config for the YÉKI project (config/ package).

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/

Historique : ce fichier n'était jusqu'ici JAMAIS chargé en production
(PythonAnywhere ne sert que du WSGI) et son import `channels.routing`
échouait dès que le module était sollicité (`channels` n'était pas installé,
voir docs/FORUM_TEMPS_REEL.md, constat du 2026-07-16). Réellement actif
depuis la migration vers un VPS + Daphne (serveur ASGI) — `channels` est
maintenant une dépendance installée (requirements.txt) et
`ASGI_APPLICATION`/`CHANNEL_LAYERS` sont configurés (config/settings/
production.py). Note : `yeki/consumers.py` (le `ForumConsumer` routé
ci-dessous) reste, lui, à réviser avant un usage réel en production — sa
sérialisation interne est en partie périmée par rapport à
`apps/forum/serializers.py` (voir le ticket de migration d'hébergement pour
le détail) ; il tourne mais ne doit pas encore être branché côté client.
"""

import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

# Bug réel révélé par le tout premier vrai chargement de ce fichier
# (déploiement Railway, 2026-08-06) — jamais détecté avant puisqu'il n'avait
# jamais tourné en production. `django.setup()` doit être appelé
# EXPLICITEMENT et AVANT tout import qui touche des modèles Django
# (`yeki.routing` → `yeki.consumers` → `from django.contrib.auth.models
# import User`) : sans lui, l'app registry n'est pas encore prête
# (`AppRegistryNotReady`) au moment de cet import — `get_asgi_application()`
# déclenche bien un `django.setup()` interne, mais seulement APRÈS avoir été
# appelé, trop tard pour un import de niveau module placé plus haut.
django.setup()

from yeki.routing import websocket_urlpatterns  # noqa: E402 — doit rester après django.setup()

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
