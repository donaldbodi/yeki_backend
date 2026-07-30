"""
Tests d'intégration P9.1 : câblage d'AccesMatricePermission sur les vues
Forum — "PAS de forum" en gratuit (couvre aussi "pas de préoccupation
depuis une leçon", un post source=lecon). La logique de la matrice
elle-même est testée unitairement dans apps/core/tests/test_acces_service.py
— ici on vérifie le CÂBLAGE réel.
"""

import pytest

from apps.forum.models import QuestionForum


@pytest.fixture
def question(db, user_apprenant_premium):
    return QuestionForum.objects.create(
        auteur=user_apprenant_premium, contenu="Une question", source="libre"
    )


@pytest.fixture
def question_depuis_lecon(db, user_apprenant_premium):
    return QuestionForum.objects.create(
        auteur=user_apprenant_premium, contenu="Une question depuis une leçon", source="lecon", lecon_id=1
    )


@pytest.mark.django_db
def test_liste_questions_bloquee_en_gratuit(client_apprenant, question):
    response = client_apprenant.get("/api/forum/questions/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_liste_questions_accessible_en_premium(client_apprenant_premium, question):
    response = client_apprenant_premium.get("/api/forum/questions/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_detail_question_bloquee_en_gratuit(client_apprenant, question):
    response = client_apprenant.get(f"/api/forum/questions/{question.id}/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_detail_question_depuis_lecon_bloquee_en_gratuit(client_apprenant, question_depuis_lecon):
    """« pas de préoccupation depuis une leçon » = un post forum
    source=lecon, couvert par la règle générale « PAS de forum »."""
    response = client_apprenant.get(f"/api/forum/questions/{question_depuis_lecon.id}/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_repondre_question_bloque_en_gratuit(client_apprenant, question):
    response = client_apprenant.post(
        f"/api/forum/questions/{question.id}/repondre/", {"contenu": "Réponse"}, format="json"
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_repondre_question_accessible_en_premium(client_apprenant_premium, question):
    response = client_apprenant_premium.post(
        f"/api/forum/questions/{question.id}/repondre/", {"contenu": "Réponse"}, format="json"
    )
    assert response.status_code == 201


@pytest.mark.django_db
def test_stats_forum_bloquees_en_gratuit(client_apprenant):
    response = client_apprenant.get("/api/forum/stats/")
    assert response.status_code == 403
