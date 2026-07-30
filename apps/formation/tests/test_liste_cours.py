"""
P9.6 : `GET /cours/` (`liste_cours`) était écrite et documentée mais jamais
câblée dans les urls — l'onglet « Tous les cours » de l'administration
générale (frontend) était donc systématiquement vide. Vérifie que la route
répond désormais, et que le filtrage par rôle déjà écrit dans la vue est
respecté (admin voit tout, cadre seulement son département).
"""

import pytest
from django.urls import reverse
from rest_framework import status

from apps.formation.models import Cours


@pytest.mark.django_db
def test_admin_voit_tous_les_cours(client_admin, cours, departement):
    autre_departement = departement.parcours.departements.create(nom="Autre département")
    Cours.objects.create(titre="Autre cours", niveau="Terminale", departement=autre_departement)

    response = client_admin.get(reverse("liste-cours"))

    assert response.status_code == status.HTTP_200_OK
    titres = {c["titre"] for c in response.data["results"]}
    assert titres == {cours.titre, "Autre cours"}


@pytest.mark.django_db
def test_cadre_ne_voit_que_les_cours_de_son_departement(
    client_enseignant_cadre, user_enseignant_cadre, cours, departement
):
    departement.cadre = user_enseignant_cadre.profile
    departement.save(update_fields=["cadre"])
    autre_departement = departement.parcours.departements.create(nom="Autre département")
    Cours.objects.create(titre="Cours hors périmètre", niveau="Terminale", departement=autre_departement)

    response = client_enseignant_cadre.get(reverse("liste-cours"))

    assert response.status_code == status.HTTP_200_OK
    titres = {c["titre"] for c in response.data["results"]}
    assert titres == {cours.titre}


@pytest.mark.django_db
def test_apprenant_recoit_403(client_apprenant):
    response = client_apprenant.get(reverse("liste-cours"))
    assert response.status_code == status.HTTP_403_FORBIDDEN
