"""
Test P2.4 : le split compte Yéki / compte du cadre organisateur, pour le
paiement de participation à une olympiade, est lu depuis
ParametreSysteme['part_yeki_olympiade'] — plus de valeur en dur (0.20/0.80).
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.core.models import ParametreSysteme
from apps.evaluation.models import Olympiade
from apps.paiement.models import YekiWallet


@pytest.fixture
def olympiade_payante(user_enseignant_cadre):
    now = timezone.now()
    return Olympiade.objects.create(
        titre="Olympiade Test",
        date_ouverture_inscription=now - timedelta(days=1),
        date_cloture_inscription=now + timedelta(days=1),
        date_debut_olympiade=now + timedelta(days=2),
        date_fin_olympiade=now + timedelta(days=3),
        organisateur=user_enseignant_cadre.profile,
        demande_paiement_participants=True,
        prix_participation=1000,
    )


@pytest.mark.django_db
def test_split_utilise_le_parametre_configure(
    client_apprenant, user_apprenant, user_enseignant_cadre, olympiade_payante
):
    ParametreSysteme.objects.filter(cle="part_yeki_olympiade").update(valeur="80")

    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    wallet.solde = 2000
    wallet.save()

    response = client_apprenant.post(
        reverse("payer-participation-olympiade", args=[olympiade_payante.id]),
        {"montant": 1000},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["part_yeki"] == 800
    assert response.data["part_cadre"] == 200


@pytest.mark.django_db
def test_split_change_si_le_parametre_change(
    client_apprenant, user_apprenant, user_enseignant_cadre, olympiade_payante
):
    ParametreSysteme.objects.filter(cle="part_yeki_olympiade").update(valeur="50")

    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    wallet.solde = 2000
    wallet.save()

    response = client_apprenant.post(
        reverse("payer-participation-olympiade", args=[olympiade_payante.id]),
        {"montant": 1000},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["part_yeki"] == 500
    assert response.data["part_cadre"] == 500
