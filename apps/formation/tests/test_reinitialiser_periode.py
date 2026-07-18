"""
Tests P2.3 : Departement.reinitialiser_periode() doit archiver le
classement (RangApprenant/ScoreDetail) dans ClassementHistorique AVANT
d'écraser les dates de période — auparavant, le classement de la période
précédente était purement et simplement perdu.
"""

import pytest
from django.utils import timezone

from apps.evaluation.models import ClassementHistorique, RangApprenant, ScoreDetail


@pytest.mark.django_db
def test_reinitialiser_periode_archive_avant_reset(departement, user_apprenant):
    ancien_debut = departement.date_debut_periode

    rang = RangApprenant.objects.create(
        apprenant=user_apprenant, departement=departement, score=87.5, rang=1
    )
    ScoreDetail.objects.create(rang_apprenant=rang, categorie="devoirs", score=30.0, poids=1.0)
    ScoreDetail.objects.create(rang_apprenant=rang, categorie="exercices", score=57.5, poids=2.0)

    avant = timezone.now()
    departement.reinitialiser_periode()
    apres = timezone.now()

    historique = ClassementHistorique.objects.get(departement=departement, apprenant=user_apprenant)
    assert historique.periode_debut == ancien_debut
    assert avant <= historique.periode_fin <= apres
    assert historique.rang == 1
    assert historique.points == 87.5
    assert historique.detail == {"devoirs": 30.0, "exercices": 57.5}

    departement.refresh_from_db()
    assert departement.date_debut_periode > ancien_debut
    assert departement.date_fin_periode > departement.date_debut_periode


@pytest.mark.django_db
def test_reinitialiser_periode_sans_classement_ne_plante_pas(departement):
    """Aucun RangApprenant pour ce département : reset des dates seul, pas d'erreur."""
    departement.reinitialiser_periode()
    assert ClassementHistorique.objects.filter(departement=departement).count() == 0
