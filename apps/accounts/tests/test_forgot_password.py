"""
Tests du flux mot de passe oublié (P5.5) : demande de code, vérification
OTP, réinitialisation, throttling anti-abus (CDC_BACKEND §2.5 : scope
"otp" → 3/10min sur /api/auth/forgot-password/).
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import PasswordResetOTP


@pytest.mark.django_db
def test_forgot_password_throttle_429_au_4e_appel(user_apprenant):
    """
    throttle_scope="otp" → 3/10min. Les 3 premiers appels passent (200,
    réponse générique anti-énumération) ; le 4e doit être bloqué.
    """
    client = APIClient()
    reponses = []
    for _ in range(4):
        reponses.append(
            client.post(
                reverse("forgot-password"),
                {"email": user_apprenant.email},
                format="json",
            )
        )

    for reponse in reponses[:3]:
        assert reponse.status_code == status.HTTP_200_OK

    derniere = reponses[3]
    assert derniere.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert derniere.data["error"]["code"] == "THROTTLED"
    assert "retry_after" in derniere.data["error"]["fields"]


@pytest.mark.django_db
def test_forgot_password_email_inconnu_reponse_generique(user_apprenant):
    """Anti-énumération : un email inexistant renvoie le même 200 générique."""
    client = APIClient()
    reponse = client.post(
        reverse("forgot-password"),
        {"email": "inconnu@yeki.test"},
        format="json",
    )
    assert reponse.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_flux_complet_verification_et_reinitialisation(user_apprenant):
    """
    Parcours complet : demande de code → vérification OTP → nouveau mot
    de passe. Le code n'est pas exposé par la réponse (anti-énumération,
    `debug_code` n'apparaît qu'en mode DEBUG) : on le lit directement en
    base, comme le ferait l'email reçu par l'utilisateur.
    """
    client = APIClient()

    reponse_demande = client.post(
        reverse("forgot-password"),
        {"email": user_apprenant.email},
        format="json",
    )
    assert reponse_demande.status_code == status.HTTP_200_OK

    otp = PasswordResetOTP.objects.get(user=user_apprenant, used=False)

    reponse_verif = client.post(
        reverse("verify-otp"),
        {"email": user_apprenant.email, "code": otp.code},
        format="json",
    )
    assert reponse_verif.status_code == status.HTTP_200_OK
    reset_token = reponse_verif.data["reset_token"]

    reponse_reset = client.post(
        reverse("reset-password"),
        {
            "email": user_apprenant.email,
            "reset_token": reset_token,
            "new_password": "NouveauMdp123",
            "confirm_password": "NouveauMdp123",
        },
        format="json",
    )
    assert reponse_reset.status_code == status.HTTP_200_OK

    # Le nouveau mot de passe fonctionne bien pour se connecter.
    reponse_login = client.post(
        reverse("login"),
        {"identifier": user_apprenant.username, "password": "NouveauMdp123"},
        format="json",
    )
    assert reponse_login.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_verify_otp_code_incorrect(user_apprenant):
    client = APIClient()
    client.post(reverse("forgot-password"), {"email": user_apprenant.email}, format="json")

    reponse = client.post(
        reverse("verify-otp"),
        {"email": user_apprenant.email, "code": "000000"},
        format="json",
    )
    assert reponse.status_code == status.HTTP_400_BAD_REQUEST
    assert "detail" in reponse.data
