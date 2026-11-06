"""
Diffusion temps réel du forum (voir docs/FORUM_TEMPS_REEL.md).

Le WebSocket ne fait que SIGNALER un changement : l'événement ne porte que des
identifiants, jamais de contenu. Le client recharge ensuite par l'API REST, qui
reste seule à appliquer la matrice Gratuit/Premium et à valider les écritures.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

logger = logging.getLogger(__name__)

GROUPE_GLOBAL = "forum_global"


def groupe_cours(cours_id):
    return f"forum_cours_{cours_id}"


def _envoyer(evenement, groupes):
    # Le temps réel est un confort : Redis indisponible ne doit jamais faire
    # échouer l'écriture REST déjà validée (le client se rattrape par sondage).
    try:
        couche = get_channel_layer()
        for groupe in groupes:
            async_to_sync(couche.group_send)(groupe, {"type": "forum.evenement", **evenement})
    except Exception:
        logger.exception("Diffusion forum impossible : %s", evenement.get("evenement"))


def diffuser(evenement, *, question_id, cours_id=None, reponse_id=None):
    """Signale un changement au forum global (qui liste toutes les questions)
    et, si la question est rattachée à un cours, à la salle de ce cours."""
    groupes = [GROUPE_GLOBAL]
    if cours_id is not None:
        groupes.append(groupe_cours(cours_id))
    charge = {
        "evenement": evenement,
        "question_id": question_id,
        "reponse_id": reponse_id,
        "cours_id": cours_id,
    }
    # Après le commit seulement : sinon le client rechargerait avant que la
    # donnée ne soit visible.
    transaction.on_commit(lambda: _envoyer(charge, groupes))
