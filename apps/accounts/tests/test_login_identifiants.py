"""Connexion avec le nom d'utilisateur, l'e-mail ou le numéro de téléphone."""

import pytest
from django.urls import reverse

from apps.accounts.serializers import normaliser_telephone


def _connexion(api_client, identifiant, mot_de_passe="Test1234!"):
    return api_client.post(
        reverse("login"), {"identifier": identifiant, "password": mot_de_passe}, format="json"
    )


def test_normaliser_telephone():
    assert normaliser_telephone("+237 6 99 12 34 56") == "699123456"
    assert normaliser_telephone("00237699123456") == "699123456"
    assert normaliser_telephone("699-12-34-56") == "699123456"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "identifiant",
    ["apprenant_test", "apprenant_test@yeki.test", "APPRENANT_TEST@yeki.test", "699123456", "+237 699 12 34 56"],
)
def test_connexion_par_identifiant(api_client, user_apprenant, identifiant):
    user_apprenant.profile.phone = "699123456"
    user_apprenant.profile.save(update_fields=["phone"])
    response = _connexion(api_client, identifiant)
    assert response.status_code == 200, response.data
    assert response.data["token"]


@pytest.mark.django_db
def test_connexion_mauvais_mot_de_passe(api_client, user_apprenant):
    user_apprenant.profile.phone = "699123456"
    user_apprenant.profile.save(update_fields=["phone"])
    assert _connexion(api_client, "699123456", "faux").status_code == 400


@pytest.mark.django_db
def test_numero_deja_utilise_refuse_a_l_inscription(api_client, user_apprenant):
    user_apprenant.profile.phone = "699123456"
    user_apprenant.profile.save(update_fields=["phone"])
    from apps.accounts.serializers import RegisterSerializer

    serializer = RegisterSerializer()
    with pytest.raises(Exception, match="déjà utilisé"):
        serializer.validate_phone("+237 699 12 34 56")
