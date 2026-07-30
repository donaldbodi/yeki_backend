"""
Test P11.8 : accès aux périodes de classement archivées
(`ClassementHistorique`) — n'avait jusqu'ici aucune exposition API
(confirmé par recherche exhaustive avant ce ticket), nécessaire pour
brancher `YkLeaderboard` avec un historique consultable côté Flutter.
"""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from apps.accounts.models import Profile
from apps.evaluation.models import ClassementHistorique


@pytest.fixture
def periode_archivee(departement, user_apprenant):
    debut = timezone.now() - timedelta(days=60)
    fin = timezone.now() - timedelta(days=1)
    ClassementHistorique.objects.create(
        departement=departement,
        apprenant=user_apprenant,
        periode_debut=debut,
        periode_fin=fin,
        rang=1,
        points=42.0,
        detail={"exercices": 42.0},
    )
    return {"debut": debut, "fin": fin}


@pytest.mark.django_db
def test_liste_periodes_archivees(client_apprenant, user_apprenant, departement, periode_archivee):
    user_apprenant.profile.cursus = departement.parcours.nom
    user_apprenant.profile.save()

    reponse = client_apprenant.get(f"/api/classement/departement/{departement.id}/periodes/")

    assert reponse.status_code == 200
    assert len(reponse.data) == 1


@pytest.mark.django_db
def test_classement_historique_dune_periode(client_apprenant, user_apprenant, departement, periode_archivee):
    user_apprenant.profile.cursus = departement.parcours.nom
    user_apprenant.profile.save()

    debut_iso = periode_archivee["debut"].isoformat()
    reponse = client_apprenant.get(
        f"/api/classement/departement/{departement.id}/historique/",
        {"periode_debut": debut_iso},
    )

    assert reponse.status_code == 200, reponse.data
    assert reponse.data["classement"][0]["rang"] == 1
    assert reponse.data["classement"][0]["score"] == 42.0
    assert reponse.data["classement"][0]["username"] == user_apprenant.username


@pytest.mark.django_db
def test_classement_historique_sans_periode_debut_rejete(client_apprenant, user_apprenant, departement):
    user_apprenant.profile.cursus = departement.parcours.nom
    user_apprenant.profile.save()

    reponse = client_apprenant.get(f"/api/classement/departement/{departement.id}/historique/")

    assert reponse.status_code == 400


@pytest.mark.django_db
def test_apprenant_dun_autre_cursus_refuse(client_apprenant, departement):
    reponse = client_apprenant.get(f"/api/classement/departement/{departement.id}/periodes/")
    assert reponse.status_code == 403
