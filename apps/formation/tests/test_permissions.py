"""
Tests de permissions par rôle (P1.6) — contrôle inline `profile.user_type`
dans `apps/formation/views/parcours.py::CreerParcoursView`, qui réserve la
création de parcours à l'administrateur général.
"""

import pytest
from django.urls import reverse
from rest_framework import status


@pytest.mark.django_db
def test_creer_parcours_refuse_pour_non_admin(client_enseignant):
    response = client_enseignant.post(
        reverse("parcours-creer"),
        {"nom": "Nouveau Parcours"},
        format="json",
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_creer_parcours_autorise_pour_admin(client_admin):
    response = client_admin.post(
        reverse("parcours-creer"),
        {"nom": "Nouveau Parcours"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
