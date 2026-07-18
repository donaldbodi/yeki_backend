"""
Tests P2.2 : Choix.est_correct comme source de vérité pour les QCM
(remplace la comparaison texte-à-texte contre Question.bonne_reponse,
fragile — cause confirmée du bug de création QCM échouant sur un simple
écart de casse/espace).
"""

import pytest
from django.urls import reverse
from rest_framework import status

from apps.evaluation.models import Choix, Question


@pytest.fixture
def cours_enseignant(cours, user_enseignant):
    cours.enseignant_principal = user_enseignant.profile
    cours.save(update_fields=["enseignant_principal"])
    return cours


@pytest.mark.django_db
def test_creation_qcm_avec_casse_differente_reussit(client_enseignant, cours_enseignant):
    """
    Avant P2.2 : `bonne_reponse="Paris"` vs choix `"paris"` (casse
    différente) faisait échouer la création avec un 400 (comparaison
    texte-à-texte sensible à la casse). Avec `est_correct`, ce n'est plus
    un problème : la casse du texte des choix n'a plus d'incidence sur la
    validation.
    """
    exercice = cours_enseignant.exercices.create(titre="Ex", enonce="E", etoiles=1)
    payload = {
        "text": "Quelle est la capitale de la France ?",
        "type_question": "qcm",
        "points": 1,
        "choix": [
            {"texte": "paris", "est_correct": True},
            {"texte": "Londres", "est_correct": False},
        ],
    }
    response = client_enseignant.post(
        reverse("question-ajouter", args=[exercice.id]), payload, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED

    question = Question.objects.get(pk=response.data["id"])
    assert Choix.objects.filter(question=question, est_correct=True).count() == 1
    assert question.bonne_reponse == "paris"  # mirroir dérivé auto-rempli


@pytest.mark.django_db
def test_creation_qcm_sans_choix_correct_400(client_enseignant, cours_enseignant):
    exercice = cours_enseignant.exercices.create(titre="Ex", enonce="E", etoiles=1)
    payload = {
        "text": "2 + 2 ?",
        "type_question": "qcm",
        "choix": [
            {"texte": "3", "est_correct": False},
            {"texte": "4", "est_correct": False},
        ],
    }
    response = client_enseignant.post(
        reverse("question-ajouter", args=[exercice.id]), payload, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "choix" in response.data["error"]["fields"]


@pytest.mark.django_db
def test_creation_qcm_deux_choix_corrects_400(client_enseignant, cours_enseignant):
    exercice = cours_enseignant.exercices.create(titre="Ex", enonce="E", etoiles=1)
    payload = {
        "text": "2 + 2 ?",
        "type_question": "qcm",
        "choix": [
            {"texte": "3", "est_correct": True},
            {"texte": "4", "est_correct": True},
        ],
    }
    response = client_enseignant.post(
        reverse("question-ajouter", args=[exercice.id]), payload, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "choix" in response.data["error"]["fields"]


@pytest.mark.django_db
def test_creation_texte_sans_bonne_reponse_400(client_enseignant, cours_enseignant):
    exercice = cours_enseignant.exercices.create(titre="Ex", enonce="E", etoiles=1)
    response = client_enseignant.post(
        reverse("question-ajouter", args=[exercice.id]),
        {"text": "Expliquez.", "type_question": "texte"},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "bonne_reponse" in response.data["error"]["fields"]


@pytest.mark.django_db
def test_correction_qcm_utilise_est_correct(exercice):
    """La correction (_corriger_reponses_exercice, via l'API) juge le QCM
    sur Choix.est_correct — pas sur une comparaison à bonne_reponse."""
    question = Question.objects.create(
        exercice=exercice,
        text="Capitale ?",
        type_question="qcm",
        bonne_reponse="paris",  # mirroir dérivé, casse volontairement différente
        points=1,
    )
    Choix.objects.create(question=question, texte="Paris", est_correct=True)
    Choix.objects.create(question=question, texte="Londres", est_correct=False)

    from apps.evaluation.views.exercices import _corriger_reponses_exercice

    score, total, details = _corriger_reponses_exercice(exercice, {str(question.id): "Paris"})
    assert score == 1
    assert details[0]["correct"] is True
