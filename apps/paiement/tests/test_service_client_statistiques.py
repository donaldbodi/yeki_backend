"""
Tests P9.5 : `GET /api/service-client/statistiques/` — demandes en attente,
délai moyen, taux de refus (paiements manuels + retraits). Distinct du
tableau de bord financier admin général (P9.6, réservé à l'admin) — celui-
ci est accessible au Service Client.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.paiement.models import DemandePaiementManuelle


def _creer_demande(apprenant_profile, **kwargs):
    defaults = dict(
        categorie="recharge", montant=1000, operateur="orange_money",
        id_transaction=f"TXN-STATS-{apprenant_profile.id}-{kwargs.get('statut', 'x')}",
    )
    defaults.update(kwargs)
    return DemandePaiementManuelle.objects.create(apprenant=apprenant_profile, **defaults)


@pytest.mark.django_db
def test_403_si_non_service_client(client_apprenant):
    response = client_apprenant.get(reverse("service-client-statistiques"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_taux_refus_et_delai_moyen(client_service_client, user_apprenant):
    validee = _creer_demande(user_apprenant.profile, statut="validee", id_transaction="TXN-S1")
    DemandePaiementManuelle.objects.filter(pk=validee.id).update(
        date_creation=timezone.now() - timedelta(minutes=20), date_traitement=timezone.now()
    )
    refusee = _creer_demande(user_apprenant.profile, statut="refusee", id_transaction="TXN-S2")
    DemandePaiementManuelle.objects.filter(pk=refusee.id).update(
        date_creation=timezone.now() - timedelta(minutes=40), date_traitement=timezone.now()
    )
    _creer_demande(user_apprenant.profile, statut="en_attente", id_transaction="TXN-S3")

    response = client_service_client.get(reverse("service-client-statistiques"))
    assert response.status_code == 200
    data = response.data

    assert data["demandes_en_attente"]["paiement"] == 1
    assert data["taux_refus_pourcent"]["paiement"] == 50.0  # 1 refusée / 2 traitées
    assert data["delai_moyen_minutes"]["paiement"] >= 29


@pytest.mark.django_db
def test_aucune_demande_traitee_renvoie_none_pas_une_division_par_zero(client_service_client):
    response = client_service_client.get(reverse("service-client-statistiques"))
    assert response.status_code == 200
    data = response.data
    assert data["taux_refus_pourcent"]["paiement"] is None
    assert data["delai_moyen_minutes"]["retrait"] is None
