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
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from yeki.routing import websocket_urlpatterns

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
