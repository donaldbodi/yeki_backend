"""
ProfilUpdateView (PATCH /api/profil/update/) — cursus/niveau passent en
lecture seule (demande explicite : aucun utilisateur ne doit pouvoir
modifier ses informations de scolarité depuis son profil, seulement les
consulter). Vérifie que ces 2 champs sont bien ignorés silencieusement
par le serveur (barrière fiable même en contournant le formulaire
Flutter), sans que ça n'empêche la mise à jour des autres champs
autorisés.
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_patch_ignore_cursus_et_niveau(user_apprenant):
    profile = user_apprenant.profile
    profile.cursus = "Secondaire Francophone"
    profile.niveau = "Terminale"
    profile.save()

    client = APIClient()
    client.force_authenticate(user=user_apprenant)
    response = client.patch(
        reverse("profil-update"),
        {"cursus": "Licence 1", "niveau": "Première", "bio": "Nouvelle bio"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    profile.refresh_from_db()
    # cursus/niveau inchangés malgré la tentative de PATCH — ignorés
    assert profile.cursus == "Secondaire Francophone"
    assert profile.niveau == "Terminale"
    # les autres champs autorisés continuent de fonctionner normalement
    assert profile.bio == "Nouvelle bio"


@pytest.mark.django_db
def test_patch_champs_autorises_toujours_modifiables(user_apprenant):
    client = APIClient()
    client.force_authenticate(user=user_apprenant)
    response = client.patch(
        reverse("profil-update"),
        {"phone": "699000000", "sub_cursus": "Série C", "filiere": "Sciences"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    profile = user_apprenant.profile
    profile.refresh_from_db()
    assert profile.phone == "699000000"
    assert profile.sub_cursus == "Série C"
    assert profile.filiere == "Sciences"
