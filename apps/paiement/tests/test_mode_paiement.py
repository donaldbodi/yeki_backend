"""
Tests P9.7 : `ParametreSysteme['mode_paiement']` gate, À L'EXÉCUTION, quel
parcours de paiement est autorisé — sans redéploiement. Vérifie la garde
serveur ajoutée à `SoumettrePaiementManuelView`/`InitierPaiementCinetPayView`
(défense en profondeur : un appel direct à l'API ne doit pas pouvoir
contourner ce que le frontend masquerait déjà).
"""

from unittest.mock import Mock, patch

import pytest
from django.urls import reverse

from apps.core.models import ParametreSysteme


def _set_mode_paiement(valeur):
    ParametreSysteme.objects.filter(cle="mode_paiement").update(valeur=valeur)


@pytest.mark.django_db
def test_mode_manuel_bloque_cinetpay_403(client_apprenant):
    _set_mode_paiement("manuel")
    response = client_apprenant.post(
        reverse("cinetpay-initier"),
        {"type_paiement": "wallet_recharge", "montant": 2000, "payment_method": "mtn_momo"},
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_mode_manuel_autorise_paiement_manuel(client_apprenant):
    _set_mode_paiement("manuel")
    response = client_apprenant.post(
        reverse("paiement-manuel-soumettre"),
        {
            "categorie": "recharge",
            "montant": 2000,
            "operateur": "orange_money",
            "id_transaction": "TXN-MODE-MANUEL",
        },
        format="json",
    )
    assert response.status_code == 201


@pytest.mark.django_db
def test_mode_cinetpay_bloque_paiement_manuel_403(client_apprenant):
    _set_mode_paiement("cinetpay")
    response = client_apprenant.post(
        reverse("paiement-manuel-soumettre"),
        {
            "categorie": "recharge",
            "montant": 2000,
            "operateur": "orange_money",
            "id_transaction": "TXN-MODE-CINETPAY",
        },
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_mode_cinetpay_autorise_cinetpay(client_apprenant):
    _set_mode_paiement("cinetpay")
    reponse_cinetpay = Mock(status_code=200)
    reponse_cinetpay.json.return_value = {
        "code": 201,
        "data": {"payment_url": "https://checkout.cinetpay.com/x", "transaction_id": "CP-1"},
    }
    with patch("apps.paiement.views.requests.post", return_value=reponse_cinetpay):
        response = client_apprenant.post(
            reverse("cinetpay-initier"),
            {"type_paiement": "wallet_recharge", "montant": 2000, "payment_method": "mtn_momo"},
            format="json",
        )
    assert response.status_code == 200


@pytest.mark.django_db
def test_mode_les_deux_autorise_les_deux_parcours(client_apprenant):
    _set_mode_paiement("les_deux")

    response_manuel = client_apprenant.post(
        reverse("paiement-manuel-soumettre"),
        {
            "categorie": "recharge",
            "montant": 2000,
            "operateur": "orange_money",
            "id_transaction": "TXN-MODE-LESDEUX",
        },
        format="json",
    )
    assert response_manuel.status_code == 201

    reponse_cinetpay = Mock(status_code=200)
    reponse_cinetpay.json.return_value = {
        "code": 201,
        "data": {"payment_url": "https://checkout.cinetpay.com/x", "transaction_id": "CP-2"},
    }
    with patch("apps.paiement.views.requests.post", return_value=reponse_cinetpay):
        response_cinetpay = client_apprenant.post(
            reverse("cinetpay-initier"),
            {"type_paiement": "wallet_recharge", "montant": 2000, "payment_method": "mtn_momo"},
            format="json",
        )
    assert response_cinetpay.status_code == 200
