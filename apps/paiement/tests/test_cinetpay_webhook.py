"""
Tests P9.7 : sécurisation du webhook CinetPay — signature HMAC obligatoire
et revérification du montant/statut auprès de l'API CinetPay avant tout
crédit. Avant ce ticket, AUCUNE de ces deux vérifications n'existait
(confirmé par lecture du code — un commentaire mort, jamais lu, et un
appel de vérification dont le résultat était explicitement jeté).

Vérifie aussi la parité manuel/CinetPay introduite par `finaliser_paiement`
(apps/paiement/services.py) : un paiement CinetPay pour une olympiade ou
une formation doit désormais créditer le cadre (80/20 ou 30/70) et
débloquer l'accès EXACTEMENT comme le ferait le flux manuel — ce qui
n'était jamais le cas avant ce ticket.
"""

import hashlib
import hmac
import json
from unittest.mock import Mock, patch

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import Profile
from apps.formation.models import DemandeAccesFormation
from apps.paiement.models import CinetPayTransaction, Paiement, PaiementOlympiade, YekiWallet

WEBHOOK_SECRET = "secret-test-p9-7"


def _signer(corps: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), corps, hashlib.sha256).hexdigest()


def _poster_webhook(client, payload, *, signature="__auto__", secret=WEBHOOK_SECRET):
    corps = json.dumps(payload).encode("utf-8")
    signature_finale = _signer(corps, secret) if signature == "__auto__" else signature
    headers = {}
    if signature_finale is not None:
        headers["HTTP_X_TOKEN"] = signature_finale
    with override_settings(CINETPAY_WEBHOOK_SECRET=secret):
        return client.post(
            reverse("cinetpay-webhook"), data=corps, content_type="application/json", **headers
        )


def _mock_check_cinetpay(status="ACCEPTED", amount=None):
    reponse = Mock(status_code=200)
    reponse.json.return_value = {"code": 200, "data": {"status": status, "amount": amount}}
    reponse.raise_for_status = Mock()
    return reponse


@pytest.fixture
def transaction_recharge(db, user_apprenant):
    return CinetPayTransaction.objects.create(
        user=user_apprenant,
        amount=2000,
        reference="YEKI-TEST-001",
        transaction_id="CP-TEST-001",
        payment_method="mtn_momo",
        status="pending",
    )


@pytest.mark.django_db
def test_signature_absente_401_rien_credite(client_apprenant, transaction_recharge):
    payload = {
        "cpm_trans_id": transaction_recharge.transaction_id,
        "cpm_result": "00",
        "metadata": json.dumps({"type_paiement": "wallet_recharge"}),
    }
    from rest_framework.test import APIClient

    anonyme = APIClient()
    response = _poster_webhook(anonyme, payload, signature=None)
    assert response.status_code == 401

    transaction_recharge.refresh_from_db()
    assert transaction_recharge.status == "pending"
    wallet = YekiWallet.get_or_create_wallet(transaction_recharge.user)
    assert wallet.solde == 0


@pytest.mark.django_db
def test_signature_invalide_401_rien_credite(transaction_recharge):
    from rest_framework.test import APIClient

    payload = {
        "cpm_trans_id": transaction_recharge.transaction_id,
        "cpm_result": "00",
        "metadata": json.dumps({"type_paiement": "wallet_recharge"}),
    }
    response = _poster_webhook(APIClient(), payload, signature="signature-bidon-invalide")
    assert response.status_code == 401

    transaction_recharge.refresh_from_db()
    assert transaction_recharge.status == "pending"


@pytest.mark.django_db
def test_secret_non_configure_fail_closed_401(transaction_recharge):
    """Secret vide côté serveur → refus systématique, jamais interprété
    comme "vérification non nécessaire"."""
    from rest_framework.test import APIClient

    payload = {
        "cpm_trans_id": transaction_recharge.transaction_id,
        "cpm_result": "00",
        "metadata": json.dumps({"type_paiement": "wallet_recharge"}),
    }
    response = _poster_webhook(APIClient(), payload, signature="peu-importe", secret="")
    assert response.status_code == 401

    transaction_recharge.refresh_from_db()
    assert transaction_recharge.status == "pending"


@pytest.mark.django_db
def test_montant_ne_correspond_pas_a_cinetpay_rien_credite(transaction_recharge):
    from rest_framework.test import APIClient

    payload = {
        "cpm_trans_id": transaction_recharge.transaction_id,
        "cpm_result": "00",
        "metadata": json.dumps({"type_paiement": "wallet_recharge"}),
    }
    # CinetPay confirme un montant DIFFÉRENT de celui enregistré localement
    # (2000) — scénario exact de la vulnérabilité visée par ce ticket.
    with patch(
        "apps.paiement.views.requests.post",
        return_value=_mock_check_cinetpay(status="ACCEPTED", amount=1),
    ):
        response = _poster_webhook(APIClient(), payload)
    assert response.status_code == 200
    assert response.data["status"] == "rejected_verification_failed"

    transaction_recharge.refresh_from_db()
    assert transaction_recharge.status == "pending"
    wallet = YekiWallet.get_or_create_wallet(transaction_recharge.user)
    assert wallet.solde == 0


@pytest.mark.django_db
def test_echec_communication_cinetpay_rien_credite(transaction_recharge):
    import requests as requests_module
    from rest_framework.test import APIClient

    payload = {
        "cpm_trans_id": transaction_recharge.transaction_id,
        "cpm_result": "00",
        "metadata": json.dumps({"type_paiement": "wallet_recharge"}),
    }
    with patch(
        "apps.paiement.views.requests.post",
        side_effect=requests_module.exceptions.ConnectionError,
    ):
        response = _poster_webhook(APIClient(), payload)
    assert response.status_code == 200
    assert response.data["status"] == "rejected_verification_failed"

    transaction_recharge.refresh_from_db()
    assert transaction_recharge.status == "pending"


@pytest.mark.django_db
def test_wallet_recharge_credite_apres_verification_reussie(transaction_recharge):
    from rest_framework.test import APIClient

    payload = {
        "cpm_trans_id": transaction_recharge.transaction_id,
        "cpm_result": "00",
        "metadata": json.dumps({"type_paiement": "wallet_recharge"}),
    }
    with patch(
        "apps.paiement.views.requests.post",
        return_value=_mock_check_cinetpay(status="ACCEPTED", amount=2000),
    ):
        response = _poster_webhook(APIClient(), payload)
    assert response.status_code == 200

    transaction_recharge.refresh_from_db()
    assert transaction_recharge.status == "success"
    wallet = YekiWallet.get_or_create_wallet(transaction_recharge.user)
    assert wallet.solde == 2000

    paiement = Paiement.objects.get(transaction_id=transaction_recharge.transaction_id)
    assert paiement.moyen == "cinetpay"
    assert paiement.type_paiement == "recharge_wallet"


@pytest.mark.django_db
def test_deja_traite_renvoie_already_processed_sans_reverifier(transaction_recharge):
    from rest_framework.test import APIClient

    transaction_recharge.status = "success"
    transaction_recharge.save()

    payload = {
        "cpm_trans_id": transaction_recharge.transaction_id,
        "cpm_result": "00",
        "metadata": json.dumps({"type_paiement": "wallet_recharge"}),
    }
    with patch("apps.paiement.views.requests.post") as mock_post:
        response = _poster_webhook(APIClient(), payload)
    assert response.status_code == 200
    assert response.data["status"] == "already_processed"
    mock_post.assert_not_called()


@pytest.mark.django_db
def test_olympiade_credite_80_20_et_debloque_paiementolympiade(db, user_apprenant):
    from datetime import timedelta

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from apps.evaluation.models import Olympiade

    cadre = Profile.objects.create(
        user=User.objects.create_user(username="cadre_cinetpay_test", password="Test1234!"),
        user_type="enseignant_cadre",
    )

    now = timezone.now()
    olympiade = Olympiade.objects.create(
        titre="Olympiade CinetPay Test",
        organisateur=cadre,
        date_ouverture_inscription=now,
        date_cloture_inscription=now + timedelta(days=1),
        date_debut_olympiade=now + timedelta(days=2),
        date_fin_olympiade=now + timedelta(days=2, hours=2),
        demande_paiement_participants=True,
        prix_participation=100,
    )
    transaction = CinetPayTransaction.objects.create(
        user=user_apprenant,
        amount=100,
        reference="YEKI-TEST-OLYMP",
        transaction_id="CP-TEST-OLYMP",
        payment_method="mtn_momo",
        status="pending",
    )
    payload = {
        "cpm_trans_id": transaction.transaction_id,
        "cpm_result": "00",
        "metadata": json.dumps({"type_paiement": "olympiade", "olympiade_id": olympiade.id}),
    }
    with patch(
        "apps.paiement.views.requests.post",
        return_value=_mock_check_cinetpay(status="ACCEPTED", amount=100),
    ):
        response = _poster_webhook(APIClient(), payload)
    assert response.status_code == 200

    paiement_olympiade = PaiementOlympiade.objects.get(apprenant=user_apprenant, olympiade=olympiade)
    assert paiement_olympiade.statut == "paye"

    wallet_cadre = YekiWallet.get_or_create_wallet(cadre.user)
    assert wallet_cadre.solde == 20  # 20% de 100

    paiement = Paiement.objects.get(transaction_id=transaction.transaction_id)
    assert paiement.commission_yeki == 80  # 80% de 100
    assert paiement.olympiade_liee == olympiade


@pytest.mark.django_db
def test_formation_credite_30_70_et_debloque_acces_departement(
    db, user_apprenant, departement, user_enseignant_cadre
):
    from rest_framework.test import APIClient

    departement.cadre = Profile.objects.get(user=user_enseignant_cadre)
    departement.save(update_fields=["cadre"])

    transaction = CinetPayTransaction.objects.create(
        user=user_apprenant,
        amount=10000,
        reference="YEKI-TEST-FORM",
        transaction_id="CP-TEST-FORM",
        payment_method="orange_money",
        status="pending",
    )
    payload = {
        "cpm_trans_id": transaction.transaction_id,
        "cpm_result": "00",
        "metadata": json.dumps(
            {"type_paiement": "acces_departement", "departement_id": departement.id}
        ),
    }
    with patch(
        "apps.paiement.views.requests.post",
        return_value=_mock_check_cinetpay(status="ACCEPTED", amount=10000),
    ):
        response = _poster_webhook(APIClient(), payload)
    assert response.status_code == 200

    demande_acces = DemandeAccesFormation.objects.get(
        apprenant=user_apprenant, departement=departement
    )
    assert demande_acces.statut == "acceptee"
    assert user_apprenant in departement.apprenants_autorises.all()

    wallet_cadre = YekiWallet.get_or_create_wallet(user_enseignant_cadre)
    assert wallet_cadre.solde == 7000  # 70% de 10000

    paiement = Paiement.objects.get(transaction_id=transaction.transaction_id)
    assert paiement.commission_yeki == 3000  # 30% de 10000
    assert paiement.departement == departement
