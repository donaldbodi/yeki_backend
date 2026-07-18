"""
Tests de pagination (P1.6) : toute vue de liste doit répondre avec l'enveloppe
YekiPageNumberPagination (count/next/previous/results), voir
docs/API_FOUNDATIONS.md.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from apps.formation.models import Parcours


@pytest.mark.django_db
def test_liste_parcours_paginee(client_apprenant, parcours):
    for i in range(3):
        Parcours.objects.create(nom=f"Parcours {i}", type_parcours="autre")

    response = client_apprenant.get(reverse("liste-parcours"))

    assert response.status_code == status.HTTP_200_OK
    for cle in ("count", "next", "previous", "results"):
        assert cle in response.data
    assert response.data["count"] == Parcours.objects.count()


@pytest.mark.django_db
def test_liste_parcours_respecte_page_size(client_apprenant, parcours):
    for i in range(5):
        Parcours.objects.create(nom=f"Parcours {i}", type_parcours="autre")

    response = client_apprenant.get(reverse("liste-parcours"), {"page_size": 2})

    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 2
