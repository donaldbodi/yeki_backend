"""
Tests P9.2 : GET /api/parametres/publics/ — endpoint public (AllowAny)
exposant les paramètres nécessaires à l'écran de paiement manuel (USSD,
numéros de dépôt, nom affiché, WhatsApp Service Client, délai de
validation annoncé).
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import ParametreSysteme


@pytest.mark.django_db
def test_parametres_publics_accessible_sans_authentification():
    client = APIClient()
    response = client.get(reverse("parametres-publics"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_parametres_publics_retourne_les_cles_attendues():
    ParametreSysteme.objects.filter(cle="numero_depot_orange").update(valeur="694000000")
    client = APIClient()
    response = client.get(reverse("parametres-publics"))
    data = response.data
    for cle in [
        "ussd_orange_money",
        "ussd_mtn_momo",
        "numero_depot_orange",
        "numero_depot_mtn",
        "nom_affiche_depot",
        "whatsapp_service_client",
        "delai_validation_paiement_minutes",
        "mode_paiement",
    ]:
        assert cle in data
    assert data["numero_depot_orange"] == "694000000"
    assert isinstance(data["delai_validation_paiement_minutes"], int)
