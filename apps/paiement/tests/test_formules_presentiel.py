"""
Formation hybride : abonnement en ligne, en présentiel, ou les deux. Seul
le paiement des cours en ligne débloque le contenu en ligne (Premium).
"""

import pytest
from django.urls import reverse

from apps.paiement.models import AbonnementPremium, DemandePaiementManuelle
from apps.paiement.services import finaliser_paiement


def _soumettre(client, departement, **donnees):
    return client.post(
        reverse("paiement-manuel-soumettre"),
        {
            "operateur": "orange_money",
            "id_transaction": donnees.pop("id_transaction"),
            "departement_id": departement.id,
            "type_abonnement": "mensuel",
            **donnees,
        },
        format="json",
    )


@pytest.mark.django_db
def test_presentiel_seul_enregistre_la_part_presentielle(client_apprenant, departement):
    response = _soumettre(
        client_apprenant, departement, categorie="presentiel", montant=3000, id_transaction="P-1"
    )
    assert response.status_code == 201, response.data
    demande = DemandePaiementManuelle.objects.get(pk=response.data["id"])
    assert demande.montant_presentiel == 3000


@pytest.mark.django_db
def test_les_deux_enregistre_la_part_presentielle(client_apprenant, departement):
    response = _soumettre(
        client_apprenant,
        departement,
        categorie="abonnement",
        montant=5000,
        montant_presentiel=3000,
        id_transaction="P-2",
    )
    assert response.status_code == 201, response.data
    assert DemandePaiementManuelle.objects.get(pk=response.data["id"]).montant_presentiel == 3000


@pytest.mark.django_db
def test_part_presentielle_superieure_au_montant_refusee(client_apprenant, departement):
    response = _soumettre(
        client_apprenant,
        departement,
        categorie="abonnement",
        montant=2000,
        montant_presentiel=3000,
        id_transaction="P-3",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_presentiel_seul_ne_debloque_pas_le_contenu_en_ligne(user_apprenant, departement):
    paiement = finaliser_paiement(
        user_apprenant=user_apprenant,
        categorie="presentiel",
        montant=3000,
        moyen="manuel",
        departement=departement,
    )
    assert paiement.departement == departement
    assert not AbonnementPremium.objects.filter(utilisateur=user_apprenant).exists()
