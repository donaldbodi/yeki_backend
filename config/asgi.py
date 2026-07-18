"""
ASGI config for the YÉKI project (config/ package).

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/

Note : ce fichier n'est aujourd'hui jamais chargé en production
(PythonAnywhere sert uniquement du WSGI, voir docs/FORUM_TEMPS_REEL.md) et
son import `channels.routing` échouerait s'il l'était (`channels` n'est pas
installé). Conservé à l'identique lors de la restructuration config/ —
réparer ce fichier est hors périmètre de cette tâche (structure uniquement).
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
