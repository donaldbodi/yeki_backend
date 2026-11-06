"""
WebSocket du forum : authentification par jeton, matrice d'accès et diffusion,
à travers la vraie application ASGI (mêmes routes et middleware qu'en production).

`transaction=True` : le consumer lit la base hors de la transaction du test.
"""

from unittest import mock

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator
from rest_framework.authtoken.models import Token

from apps.forum.consumers import FERMETURE_ACCES_REFUSE, FERMETURE_NON_AUTHENTIFIE
from apps.forum.models import LikeReponse, QuestionForum, ReponseQuestion
from apps.forum.realtime import diffuser
from config.asgi import application

pytestmark = pytest.mark.django_db(transaction=True)


def _communicator(chemin, jeton=None):
    sous_protocoles = ["yeki"] + ([f"token.{jeton}"] if jeton else [])
    return WebsocketCommunicator(application, chemin, subprotocols=sous_protocoles)


def _jeton(user):
    return Token.objects.get_or_create(user=user)[0].key


async def _code_de_fermeture(communicator):
    connecte, sous_protocole = await communicator.connect()
    assert connecte and sous_protocole == "yeki"
    message = await communicator.receive_output()
    assert message["type"] == "websocket.close"
    await communicator.disconnect()
    return message["code"]


def test_connexion_sans_jeton_refusee():
    communicator = _communicator("/ws/forum/")
    assert async_to_sync(_code_de_fermeture)(communicator) == FERMETURE_NON_AUTHENTIFIE


def test_connexion_jeton_invalide_refusee():
    communicator = _communicator("/ws/forum/", "0" * 40)
    assert async_to_sync(_code_de_fermeture)(communicator) == FERMETURE_NON_AUTHENTIFIE


def test_connexion_utilisateur_inactif_refusee(user_apprenant_premium):
    jeton = _jeton(user_apprenant_premium)
    user_apprenant_premium.is_active = False
    user_apprenant_premium.save()
    communicator = _communicator("/ws/forum/", jeton)
    assert async_to_sync(_code_de_fermeture)(communicator) == FERMETURE_NON_AUTHENTIFIE


def test_apprenant_gratuit_refuse(user_apprenant):
    communicator = _communicator("/ws/forum/", _jeton(user_apprenant))
    assert async_to_sync(_code_de_fermeture)(communicator) == FERMETURE_ACCES_REFUSE


def test_apprenant_gratuit_refuse_sur_salle_de_cours(user_apprenant, cours):
    communicator = _communicator(f"/ws/forum/cours/{cours.id}/", _jeton(user_apprenant))
    assert async_to_sync(_code_de_fermeture)(communicator) == FERMETURE_ACCES_REFUSE


def test_le_jeton_n_est_jamais_renvoye_au_client(user_apprenant_premium):
    jeton = _jeton(user_apprenant_premium)

    async def scenario():
        communicator = _communicator("/ws/forum/", jeton)
        resultat = await communicator.connect()
        await communicator.disconnect()
        return resultat

    assert async_to_sync(scenario)() == (True, "yeki")


def test_question_creee_diffusee_sans_contenu(user_apprenant_premium):
    jeton = _jeton(user_apprenant_premium)

    async def scenario():
        communicator = _communicator("/ws/forum/", jeton)
        await communicator.connect()
        question = await sync_to_async(QuestionForum.objects.create)(
            auteur=user_apprenant_premium, contenu="Contenu confidentiel", source="libre"
        )
        evenement = await communicator.receive_json_from()
        await communicator.disconnect()
        return question, evenement

    question, evenement = async_to_sync(scenario)()
    assert evenement == {
        "evenement": "question_creee",
        "question_id": question.id,
        "reponse_id": None,
        "cours_id": None,
    }


def test_reponse_diffusee_dans_la_salle_du_cours(user_apprenant_premium, cours):
    jeton = _jeton(user_apprenant_premium)
    question = QuestionForum.objects.create(
        auteur=user_apprenant_premium, contenu="Q", source="libre", cours_id=cours.id
    )

    async def scenario():
        communicator = _communicator(f"/ws/forum/cours/{cours.id}/", jeton)
        await communicator.connect()
        reponse = await sync_to_async(ReponseQuestion.objects.create)(
            question=question, auteur=user_apprenant_premium, contenu="R"
        )
        evenement = await communicator.receive_json_from()
        await communicator.disconnect()
        return reponse, evenement

    reponse, evenement = async_to_sync(scenario)()
    assert evenement["evenement"] == "reponse_creee"
    assert evenement["question_id"] == question.id
    assert evenement["reponse_id"] == reponse.id


def test_salle_de_cours_isolee_des_autres_cours(user_apprenant_premium, cours):
    jeton = _jeton(user_apprenant_premium)

    async def scenario():
        communicator = _communicator(f"/ws/forum/cours/{cours.id}/", jeton)
        await communicator.connect()
        await sync_to_async(QuestionForum.objects.create)(
            auteur=user_apprenant_premium, contenu="Q", source="libre", cours_id=cours.id + 1
        )
        silence = await communicator.receive_nothing()
        await communicator.disconnect()
        return silence

    assert async_to_sync(scenario)() is True


def test_like_et_retrait_diffuses(user_apprenant_premium):
    jeton = _jeton(user_apprenant_premium)
    question = QuestionForum.objects.create(
        auteur=user_apprenant_premium, contenu="Q", source="libre"
    )
    reponse = ReponseQuestion.objects.create(
        question=question, auteur=user_apprenant_premium, contenu="R"
    )

    async def scenario():
        communicator = _communicator("/ws/forum/", jeton)
        await communicator.connect()
        like = await sync_to_async(LikeReponse.objects.create)(
            reponse=reponse, utilisateur=user_apprenant_premium
        )
        premier = await communicator.receive_json_from()
        await sync_to_async(like.delete)()
        second = await communicator.receive_json_from()
        await communicator.disconnect()
        return premier, second

    premier, second = async_to_sync(scenario)()
    assert premier["evenement"] == second["evenement"] == "like_modifie"


def test_suppression_question_avec_like_ne_plante_pas(user_apprenant_premium):
    question = QuestionForum.objects.create(
        auteur=user_apprenant_premium, contenu="Q", source="libre"
    )
    reponse = ReponseQuestion.objects.create(
        question=question, auteur=user_apprenant_premium, contenu="R"
    )
    LikeReponse.objects.create(reponse=reponse, utilisateur=user_apprenant_premium)

    question.delete()

    assert not QuestionForum.objects.filter(pk=question.pk).exists()


def test_couche_indisponible_ne_fait_pas_echouer_l_ecriture():
    with mock.patch("apps.forum.realtime.get_channel_layer", side_effect=ConnectionError):
        diffuser("question_creee", question_id=1)


def test_detail_sans_vue_ne_compte_pas_de_vue(client_apprenant_premium, user_apprenant_premium):
    question = QuestionForum.objects.create(
        auteur=user_apprenant_premium, contenu="Q", source="libre"
    )

    response = client_apprenant_premium.get(f"/api/forum/questions/{question.id}/?sans_vue=1")
    assert response.status_code == 200
    question.refresh_from_db()
    assert question.nb_vues == 0

    client_apprenant_premium.get(f"/api/forum/questions/{question.id}/")
    question.refresh_from_db()
    assert question.nb_vues == 1
