"""
Tests de permissions par rôle (P1.6) — contrôle inline `profile.user_type`
dans `apps/evaluation/views/olympiades.py::CreerOlympiadeParCadreView`, qui
réserve la création d'olympiades aux enseignants cadres.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.formation.models import Departement


def _payload_dates():
    now = timezone.now()
    return {
        "date_ouverture_inscription": now.isoformat(),
        "date_cloture_inscription": (now + timedelta(days=1)).isoformat(),
        "date_debut_olympiade": (now + timedelta(days=2)).isoformat(),
        "duree_minutes": 60,
    }


@pytest.mark.django_db
def test_creer_olympiade_refuse_pour_apprenant(client_apprenant, departement):
    payload = {"titre": "Olympiade Test", "departement_id": departement.id, **_payload_dates()}
    response = client_apprenant.post(reverse("olympiade-creer-cadre"), payload, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_creer_olympiade_autorise_pour_cadre_proprietaire(
    client_enseignant_cadre, user_enseignant_cadre, departement
):
    departement.cadre = user_enseignant_cadre.profile
    departement.save(update_fields=["cadre"])

    payload = {"titre": "Olympiade Test", "departement_id": departement.id, **_payload_dates()}
    response = client_enseignant_cadre.post(
        reverse("olympiade-creer-cadre"), payload, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_creer_olympiade_refuse_pour_cadre_dun_autre_departement(
    client_enseignant_cadre, departement
):
    """Le département fourni n'appartient pas au cadre connecté."""
    autre_departement = Departement.objects.create(
        nom="Autre Département", parcours=departement.parcours
    )

    payload = {
        "titre": "Olympiade Test",
        "departement_id": autre_departement.id,
        **_payload_dates(),
    }
    response = client_enseignant_cadre.post(
        reverse("olympiade-creer-cadre"), payload, format="json"
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
