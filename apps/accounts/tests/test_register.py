"""
Tests d'inscription (P1.6) : parcours/département/niveau obligatoires
(CDC_BACKEND §13.2 — voir docs/API_FOUNDATIONS.md pour la justification du
changement de comportement : ces 3 champs n'étaient pas exigés auparavant).
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.formation.models import Parcours


def _payload_base(**overrides):
    payload = {
        "email": "nouvel.apprenant@yeki.test",
        "name": "Nouvel Apprenant",
        "username": "nouvel_apprenant",
        "password": "MotDePasse123",
        "user_type": "apprenant",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_inscription_sans_parcours_departement_niveau_400(departement):
    client = APIClient()
    response = client.post(reverse("register"), _payload_base(), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    fields = response.data["error"]["fields"]
    assert "parcours" in fields
    assert "departement" in fields
    assert "niveau" in fields


@pytest.mark.django_db
def test_inscription_departement_hors_parcours_400(departement):
    """Le département fourni n'appartient pas au parcours fourni → incohérence."""
    autre_parcours = Parcours.objects.create(nom="Autre Parcours", type_parcours="formation")

    client = APIClient()
    response = client.post(
        reverse("register"),
        _payload_base(
            parcours=autre_parcours.id,
            departement=departement.id,
            niveau="Terminale",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "parcours" in response.data["error"]["fields"]


@pytest.mark.django_db
def test_inscription_complete_valide_201(parcours, departement):
    client = APIClient()
    response = client.post(
        reverse("register"),
        _payload_base(parcours=parcours.id, departement=departement.id, niveau="Terminale"),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["role"] == "apprenant"
