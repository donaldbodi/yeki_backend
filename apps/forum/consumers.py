from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.core.services import AccesService
from apps.forum.models import QuestionForum
from apps.forum.realtime import GROUPE_GLOBAL, groupe_cours
from apps.forum.ws_auth import SOUS_PROTOCOLE

# Codes de fermeture applicatifs : le client ne retente pas (voir
# docs/FORUM_TEMPS_REEL.md), une nouvelle tentative échouerait à l'identique.
FERMETURE_NON_AUTHENTIFIE = 4401
FERMETURE_ACCES_REFUSE = 4403


class ForumConsumer(AsyncJsonWebsocketConsumer):
    """
    Canal serveur → client uniquement : les écritures passent par l'API REST
    (validation, upload, matrice d'accès), et ce qui arrive du client est ignoré.
    """

    groupe = None

    async def connect(self):
        utilisateur = self.scope["user"]
        cours_id = self.scope["url_route"]["kwargs"].get("cours_id")

        refus = None
        if not utilisateur.is_authenticated:
            refus = FERMETURE_NON_AUTHENTIFIE
        elif not await self._peut_voir(utilisateur, cours_id):
            refus = FERMETURE_ACCES_REFUSE

        # Abonnement avant `accept()` : le client resynchronise à l'ouverture, et
        # aucun événement ne doit pouvoir tomber entre les deux.
        if refus is None:
            self.groupe = groupe_cours(cours_id) if cours_id else GROUPE_GLOBAL
            await self.channel_layer.group_add(self.groupe, self.channel_name)

        # `accept()` même en cas de refus : un rejet pendant le handshake arrive au
        # client en simple échec HTTP 403, sans code exploitable. Le sous-protocole
        # est toujours renvoyé s'il a été proposé (un navigateur abandonne sinon),
        # et jamais l'entrée qui porte le jeton.
        proposes = self.scope.get("subprotocols", [])
        await self.accept(SOUS_PROTOCOLE if SOUS_PROTOCOLE in proposes else None)

        if refus is not None:
            await self.close(code=refus)

    async def disconnect(self, code):
        if self.groupe:
            await self.channel_layer.group_discard(self.groupe, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        pass

    async def forum_evenement(self, message):
        await self.send_json({k: v for k, v in message.items() if k != "type"})

    @database_sync_to_async
    def _peut_voir(self, utilisateur, cours_id):
        # Même résolution que `AccesMatricePermission._departement_liste`.
        from apps.formation.models import Cours

        cours = Cours.objects.select_related("departement").filter(pk=cours_id).first()
        departement = cours.departement if cours else None
        return AccesService.peut_voir(utilisateur, QuestionForum, departement=departement)
