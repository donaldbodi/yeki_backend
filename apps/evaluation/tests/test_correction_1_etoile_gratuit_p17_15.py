"""
Tests P17.15 : « Voir les corrections : Gratuit → 1★ uniquement »
(CDC §5.2, écart trouvé lors de l'audit du modèle économique) —
`HistoriqueTentativesExerciceView`/`ResultatExerciceView` n'avaient
jusqu'ici aucune vérification d'étoile, permettant à un apprenant
gratuit de consulter la correction d'un exercice 2★+ en connaissant
son `exercice_id`.
"""

import pytest
from django.urls import reverse

from apps.evaluation.models import Exercice, EvaluationExercice, ExerciceTentative


@pytest.fixture
def exercice_2_etoiles(cours):
    return Exercice.objects.create(cours=cours, titre="E2", enonce="x", etoiles=2)


@pytest.fixture
def exercice_1_etoile(cours):
    return Exercice.objects.create(cours=cours, titre="E1", enonce="x", etoiles=1)


def _avec_tentative(exercice, user):
    tentative = ExerciceTentative.objects.create(
        apprenant=user,
        exercice=exercice,
        tentative_numero=1,
        reponses={"questions": [], "score": 5, "total": 10},
        est_soumise=True,
        est_terminee=True,
        score=5,
        total_points=10,
    )
    EvaluationExercice.objects.create(
        user=user, exercice=exercice, score=5, total=10, tentative_finale=tentative
    )
    return tentative


@pytest.mark.django_db
def test_resultat_exercice_2_etoiles_refuse_apprenant_gratuit(
    client_apprenant, user_apprenant, exercice_2_etoiles
):
    _avec_tentative(exercice_2_etoiles, user_apprenant)

    response = client_apprenant.get(reverse("resultat-exercice", args=[exercice_2_etoiles.id]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_historique_exercice_2_etoiles_refuse_apprenant_gratuit(
    client_apprenant, user_apprenant, exercice_2_etoiles
):
    _avec_tentative(exercice_2_etoiles, user_apprenant)

    response = client_apprenant.get(reverse("historique-tentatives-exercice", args=[exercice_2_etoiles.id]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_resultat_exercice_1_etoile_reussit_apprenant_gratuit(
    client_apprenant, user_apprenant, exercice_1_etoile
):
    _avec_tentative(exercice_1_etoile, user_apprenant)

    response = client_apprenant.get(reverse("resultat-exercice", args=[exercice_1_etoile.id]))

    assert response.status_code == 200


@pytest.mark.django_db
def test_resultat_exercice_2_etoiles_reussit_apprenant_premium(
    client_apprenant_premium, user_apprenant_premium, exercice_2_etoiles
):
    _avec_tentative(exercice_2_etoiles, user_apprenant_premium)

    response = client_apprenant_premium.get(reverse("resultat-exercice", args=[exercice_2_etoiles.id]))

    assert response.status_code == 200
