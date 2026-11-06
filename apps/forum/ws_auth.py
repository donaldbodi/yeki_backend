"""
Authentification WebSocket du forum par jeton DRF.

Le client Flutter s'authentifie par `Token` DRF (pas de cookie de session) :
`AuthMiddlewareStack` laissait donc tout client mobile/web anonyme. Le jeton
voyage dans `Sec-WebSocket-Protocol` (`["yeki", "token.<jeton>"]`), seul canal
utilisable aussi depuis un navigateur (pas d'en-tête `Authorization` possible
sur un WebSocket) et, contrairement au `?token=` de l'ancien client, absent des
journaux d'accès : ces jetons n'expirent pas.
"""

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework.authtoken.models import Token

SOUS_PROTOCOLE = "yeki"
PREFIXE_JETON = "token."


def extraire_jeton(sous_protocoles):
    for sous_protocole in sous_protocoles:
        if sous_protocole.startswith(PREFIXE_JETON):
            return sous_protocole[len(PREFIXE_JETON) :]
    return None


@database_sync_to_async
def _utilisateur_du_jeton(jeton):
    try:
        utilisateur = Token.objects.select_related("user").get(key=jeton).user
    except Token.DoesNotExist:
        return AnonymousUser()
    return utilisateur if utilisateur.is_active else AnonymousUser()


class JetonSousProtocoleMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        jeton = extraire_jeton(scope.get("subprotocols", []))
        utilisateur = await _utilisateur_du_jeton(jeton) if jeton else AnonymousUser()
        return await super().__call__({**scope, "user": utilisateur}, receive, send)
