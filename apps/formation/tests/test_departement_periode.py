"""
Tests P2.3 : Departement.periode obligatoire à la création (CDC §6.4/§7.4).
`DepartementCreateSerializer` n'étant câblé à aucune vue réelle
(CreerDepartementView construit le département à la main), la règle est
appliquée directement dans CreerDepartementView.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from apps.formation.models import Departement


@pytest.fixture
def user_admin_avec_parcours(user_enseignant_admin, parcours):
    parcours.admin = user_enseignant_admin.profile
    parcours.save(update_fields=["admin"])
    return user_enseignant_admin


@pytest.mark.django_db
def test_creer_departement_sans_periode_400(client_enseignant_admin, user_admin_avec_parcours):
    response = client_enseignant_admin.post(
        reverse("departements-creer"), {"nom": "Nouveau département"}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_creer_departement_avec_periode_201(client_enseignant_admin, user_admin_avec_parcours):
    response = client_enseignant_admin.post(
        reverse("departements-creer"),
        {"nom": "Nouveau département", "periode": 3},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    departement = Departement.objects.get(pk=response.data["id"])
    assert departement.periode == 3
