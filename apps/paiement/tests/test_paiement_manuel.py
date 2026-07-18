"""
Tests P2.4 : DemandePaiementManuelle — la contrainte unique
(operateur, id_transaction) doit empêcher la soumission deux fois du même
ID de transaction (le premier abus qui apparaîtrait sans elle).
"""

import pytest
from django.urls import reverse
from rest_framework import status

from apps.paiement.models import DemandePaiementManuelle


@pytest.mark.django_db
def test_soumission_valide_201(client_apprenant):
    response = client_apprenant.post(
        reverse("paiement-manuel-soumettre"),
        {
            "categorie": "recharge",
            "montant": 2000,
            "operateur": "orange_money",
            "id_transaction": "TXN-ABC-123",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["statut"] == "en_attente"
    assert DemandePaiementManuelle.objects.count() == 1


@pytest.mark.django_db
def test_meme_transaction_deux_fois_409(client_apprenant, client_enseignant):
    payload = {
        "categorie": "recharge",
        "montant": 2000,
        "operateur": "orange_money",
        "id_transaction": "TXN-DUPLIQUEE",
    }
    r1 = client_apprenant.post(reverse("paiement-manuel-soumettre"), payload, format="json")
    assert r1.status_code == status.HTTP_201_CREATED

    # Même operateur + id_transaction, soumis par un AUTRE compte.
    r2 = client_enseignant.post(reverse("paiement-manuel-soumettre"), payload, format="json")
    assert r2.status_code == status.HTTP_409_CONFLICT
    assert r2.data["error"]["code"] == "CONFLICT"
    assert DemandePaiementManuelle.objects.count() == 1


@pytest.mark.django_db
def test_meme_id_transaction_operateur_different_ok(client_apprenant):
    """La contrainte est sur (operateur, id_transaction) ensemble, pas sur id_transaction seul."""
    commun = {"categorie": "recharge", "montant": 2000, "id_transaction": "TXN-PARTAGEE"}
    r1 = client_apprenant.post(
        reverse("paiement-manuel-soumettre"),
        {**commun, "operateur": "orange_money"},
        format="json",
    )
    r2 = client_apprenant.post(
        reverse("paiement-manuel-soumettre"),
        {**commun, "operateur": "mtn_momo"},
        format="json",
    )
    assert r1.status_code == status.HTTP_201_CREATED
    assert r2.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_categorie_invalide_400(client_apprenant):
    response = client_apprenant.post(
        reverse("paiement-manuel-soumettre"),
        {
            "categorie": "inexistante",
            "montant": 2000,
            "operateur": "orange_money",
            "id_transaction": "TXN-X",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
