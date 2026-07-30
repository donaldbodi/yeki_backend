"""
Tests P10.3 : endpoints DeviceToken — POST enregistre/actualise, DELETE
désactive (jamais ne supprime, règle 5). Aucun test de vue n'existait
avant ce ticket (seulement test_device_token.py, qui teste le modèle nu).
"""

import pytest
from django.urls import reverse

from apps.notifications.models import DeviceToken


@pytest.mark.django_db
def test_enregistrer_token_cree_une_ligne(client_apprenant, user_apprenant):
    response = client_apprenant.post(
        reverse("notifications-device-token"),
        {"token": "TOKEN-ABC", "plateforme": "android"},
        format="json",
    )
    assert response.status_code == 200
    token = DeviceToken.objects.get(token="TOKEN-ABC")
    assert token.user == user_apprenant
    assert token.plateforme == "android"
    assert token.actif is True


@pytest.mark.django_db
def test_enregistrer_token_existant_le_met_a_jour(client_apprenant, user_apprenant):
    DeviceToken.objects.create(
        user=user_apprenant, token="TOKEN-ABC", plateforme="ios", actif=False
    )
    response = client_apprenant.post(
        reverse("notifications-device-token"),
        {"token": "TOKEN-ABC", "plateforme": "android"},
        format="json",
    )
    assert response.status_code == 200
    assert DeviceToken.objects.filter(token="TOKEN-ABC").count() == 1
    token = DeviceToken.objects.get(token="TOKEN-ABC")
    assert token.plateforme == "android"
    assert token.actif is True


@pytest.mark.django_db
def test_enregistrer_sans_plateforme_valide_400(client_apprenant):
    response = client_apprenant.post(
        reverse("notifications-device-token"),
        {"token": "TOKEN-ABC", "plateforme": "playstation"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_enregistrer_sans_authentification_401(api_client):
    response = api_client.post(
        reverse("notifications-device-token"),
        {"token": "TOKEN-ABC", "plateforme": "android"},
        format="json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_supprimer_desactive_jamais_ne_supprime(client_apprenant, user_apprenant):
    DeviceToken.objects.create(user=user_apprenant, token="TOKEN-ABC", plateforme="android")

    response = client_apprenant.delete(
        reverse("notifications-device-token-delete", args=["TOKEN-ABC"])
    )

    assert response.status_code == 204
    token = DeviceToken.objects.get(token="TOKEN-ABC")
    assert token.actif is False


@pytest.mark.django_db
def test_supprimer_le_token_dun_autre_utilisateur_ne_fait_rien(
    client_apprenant, user_enseignant
):
    DeviceToken.objects.create(user=user_enseignant, token="TOKEN-AUTRE", plateforme="android")

    response = client_apprenant.delete(
        reverse("notifications-device-token-delete", args=["TOKEN-AUTRE"])
    )

    assert response.status_code == 204
    token = DeviceToken.objects.get(token="TOKEN-AUTRE")
    assert token.actif is True
