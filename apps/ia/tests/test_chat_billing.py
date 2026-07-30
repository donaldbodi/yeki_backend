"""
Tests P10.1 : séquence de facturation Yéki IA — débit UNIQUE après l'appel
Claude, sur le coût RÉEL (jamais une estimation débitée avant puis
« ajustée », l'ancien flux pouvant sous-facturer silencieusement si le
solde ne suffisait pas pour l'ajustement). Échec API = zéro débit.
"""

from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.core.models import ParametreSysteme
from apps.ia.models import YekiIAChatHistorique
from apps.ia.services import calculate_cost, commission_yeki_sur_cout
from apps.paiement.models import YekiCompteIA, YekiWallet


@pytest.fixture(autouse=True)
def _parametres_ia(db):
    ParametreSysteme.objects.filter(cle="commission_ia_pourcent").update(valeur="20")
    ParametreSysteme.objects.filter(cle="usd_to_xaf").update(valeur="600")
    ParametreSysteme.objects.filter(cle="solde_min_ia").update(valeur="20")


def _url_chat(cours_id):
    return reverse("ia-chat", args=[cours_id])


def _wallet(user, solde):
    wallet = YekiWallet.get_or_create_wallet(user)
    wallet.solde = solde
    wallet.save(update_fields=["solde"])
    return wallet


@pytest.mark.django_db
def test_debit_unique_sur_le_cout_reel_pas_une_estimation(client_apprenant, user_apprenant, cours):
    _wallet(user_apprenant, 1000)

    with patch("apps.ia.views.ANTHROPIC_API_KEY", "test-key"), patch(
        "apps.ia.views.call_claude_api"
    ) as mock_claude:
        mock_claude.return_value = ("Réponse détaillée de Claude.", 5000, 2000, None)
        response = client_apprenant.post(
            _url_chat(cours.id), {"message": "Explique les dérivées"}, format="json"
        )

    assert response.status_code == 200
    cout_attendu = calculate_cost(5000, 2000)
    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    # Le solde final correspond EXACTEMENT à solde_initial - cout_reel —
    # aucune trace d'un double débit (estimation + ajustement).
    assert wallet.solde == 1000 - cout_attendu
    assert response.data["cout_xaf"] == cout_attendu
    assert response.data["solde_avant"] == 1000
    assert response.data["solde_restant"] == 1000 - cout_attendu


@pytest.mark.django_db
def test_commission_creditee_sur_le_cout_reel(client_apprenant, user_apprenant, cours):
    _wallet(user_apprenant, 1000)
    solde_commission_avant = YekiCompteIA.objects.get_or_create(pk=1)[0].total_commissions

    with patch("apps.ia.views.ANTHROPIC_API_KEY", "test-key"), patch(
        "apps.ia.views.call_claude_api"
    ) as mock_claude:
        mock_claude.return_value = ("Réponse.", 5000, 2000, None)
        client_apprenant.post(_url_chat(cours.id), {"message": "Question"}, format="json")

    cout_reel = calculate_cost(5000, 2000)
    commission_attendue = commission_yeki_sur_cout(cout_reel)
    compte_ia = YekiCompteIA.objects.get(pk=1)
    assert compte_ia.total_commissions == solde_commission_avant + commission_attendue


@pytest.mark.django_db
def test_echec_api_zero_debit_zero_message_assistant(client_apprenant, user_apprenant, cours):
    _wallet(user_apprenant, 1000)

    with patch("apps.ia.views.call_claude_api") as mock_claude:
        mock_claude.return_value = (None, 0, 0, "Timeout de l'API Claude")
        response = client_apprenant.post(
            _url_chat(cours.id), {"message": "Question"}, format="json"
        )

    assert response.status_code == 503
    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    assert wallet.solde == 1000
    assert YekiIAChatHistorique.objects.filter(apprenant=user_apprenant, role="assistant").count() == 0


@pytest.mark.django_db
def test_solde_insuffisant_402_avant_tout_appel_claude(client_apprenant, user_apprenant, cours):
    _wallet(user_apprenant, 5)  # sous solde_min_ia=20

    with patch("apps.ia.views.call_claude_api") as mock_claude:
        response = client_apprenant.post(
            _url_chat(cours.id), {"message": "Question"}, format="json"
        )
        mock_claude.assert_not_called()

    assert response.status_code == 402
    assert response.data["solde_actuel"] == 5
    assert response.data["minimum_requis"] == 20
    assert "cout_estime_min" in response.data
    assert "cout_estime_max" in response.data
    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    assert wallet.solde == 5
