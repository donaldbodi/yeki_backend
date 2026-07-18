"""
Tests P2.1 : RepetiteursSearchView doit exiger is_repetiteur=True (validé
par le Service Client) avant d'apparaître dans les résultats de recherche.
"""

import pytest
from django.urls import reverse
from rest_framework import status


@pytest.mark.django_db
def test_enseignant_non_valide_absent_des_resultats(client_apprenant, user_enseignant, cours):
    cours.enseignant_principal = user_enseignant.profile
    cours.matiere = "Maths"
    cours.save(update_fields=["enseignant_principal", "matiere"])
    user_enseignant.profile.is_repetiteur = False
    user_enseignant.profile.save()

    response = client_apprenant.get(reverse("repetiteurs-search"), {"matiere": "Maths"})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["total"] == 0


@pytest.mark.django_db
def test_enseignant_valide_present_dans_les_resultats(client_apprenant, user_enseignant, cours):
    cours.enseignant_principal = user_enseignant.profile
    cours.matiere = "Maths"
    cours.save(update_fields=["enseignant_principal", "matiere"])
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()

    response = client_apprenant.get(reverse("repetiteurs-search"), {"matiere": "Maths"})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["total"] == 1
