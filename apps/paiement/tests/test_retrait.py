"""
Tests P2.4 : DemandeRetrait — montant minimum, solde suffisant, et gel
(débit immédiat) du solde à la création (CDC §5.6).
"""

import pytest
from django.urls import reverse
from rest_framework import status

from apps.paiement.models import DemandeRetrait, YekiWallet


@pytest.mark.django_db
def test_montant_sous_le_minimum_400(client_apprenant, user_apprenant):
    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    wallet.solde = 5000
    wallet.save()

    response = client_apprenant.post(
        reverse("retrait-demander"),
        {"montant_brut": 500, "operateur": "orange_money", "numero_destination": "237690000000"},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_solde_insuffisant_402(client_apprenant, user_apprenant):
    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    wallet.solde = 500
    wallet.save()

    response = client_apprenant.post(
        reverse("retrait-demander"),
        {"montant_brut": 2000, "operateur": "orange_money", "numero_destination": "237690000000"},
        format="json",
    )
    assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
    assert response.data["error"]["code"] == "INSUFFICIENT_BALANCE"


@pytest.mark.django_db
def test_creation_gele_le_solde_immediatement(client_apprenant, user_apprenant):
    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    wallet.solde = 5000
    wallet.save()

    response = client_apprenant.post(
        reverse("retrait-demander"),
        {"montant_brut": 3000, "operateur": "orange_money", "numero_destination": "237690000000"},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["statut"] == "en_attente"
    assert (
        response.data["montant_net"] == 3000
    )  # aucune grille FraisOperateur configurée -> frais=0

    wallet.refresh_from_db()
    assert wallet.solde == 2000  # gelé : débité immédiatement

    demande = DemandeRetrait.objects.get(beneficiaire=user_apprenant.profile)
    assert demande.montant_brut == 3000
    assert demande.frais_operateur == 0
