"""
Tests d'authentification (P1.6) : login, échec, throttling anti brute-force
(CDC_BACKEND §2.5 : 5 tentatives/minute sur /api/auth/login/).
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_login_reussi(user_apprenant):
    client = APIClient()
    response = client.post(
        reverse("login"),
        {"identifier": user_apprenant.username, "password": "Test1234!"},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    assert "token" in response.data


@pytest.mark.django_db
def test_login_mauvais_mot_de_passe(user_apprenant):
    client = APIClient()
    response = client.post(
        reverse("login"),
        {"identifier": user_apprenant.username, "password": "mauvais_mdp"},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_login_throttle_429_au_6e_appel(user_apprenant):
    """
    CDC_BACKEND §2.5 : throttle_scope='login' → 5/min. Les 5 premiers appels
    (même en échec) consomment le quota ; le 6e doit être bloqué.
    """
    client = APIClient()
    reponses = []
    for _ in range(6):
        reponses.append(
            client.post(
                reverse("login"),
                {"identifier": user_apprenant.username, "password": "mauvais_mdp"},
                format="json",
            )
        )

    for reponse in reponses[:5]:
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST

    derniere = reponses[5]
    assert derniere.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert derniere.data["error"]["code"] == "THROTTLED"
