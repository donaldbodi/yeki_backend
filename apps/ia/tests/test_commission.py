"""
Tests P2.4 : commission Yéki IA en pourcentage (remplace l'ancien montant
fixe de 5 FCFA) — apps/ia/services.py.
"""

import pytest

from apps.core.models import ParametreSysteme
from apps.ia.services import calculate_cost, commission_yeki_sur_cout


@pytest.mark.django_db
def test_calculate_cost_applique_le_pourcentage_configure():
    ParametreSysteme.objects.filter(cle="commission_ia_pourcent").update(valeur="20")
    ParametreSysteme.objects.filter(cle="usd_to_xaf").update(valeur="600")
    ParametreSysteme.objects.filter(cle="solde_min_ia").update(valeur="1")

    # 1000 tokens input, 500 output — coût de base connu, pas au plancher
    cout = calculate_cost(100_000, 100_000)
    # base_usd = (100000/1e6)*0.80 + (100000/1e6)*4.00 = 0.08 + 0.40 = 0.48
    # base_xaf = 0.48 * 600 = 288 ; total = 288 * 1.20 = 345.6 -> int = 345
    assert cout == 345


@pytest.mark.django_db
def test_commission_change_si_le_parametre_change():
    """
    Utilise `.save()` (pas `.filter().update()`, qui contourne post_save et
    donc l'invalidation du cache — comportement Django standard, pas un
    bug) pour vérifier que le paramètre est bien relu à chaque appel.
    """
    ParametreSysteme.objects.filter(cle="usd_to_xaf").update(valeur="600")
    ParametreSysteme.objects.filter(cle="solde_min_ia").update(valeur="1")

    param = ParametreSysteme.objects.get(cle="commission_ia_pourcent")
    param.valeur = "20"
    param.save()
    cout_20 = calculate_cost(100_000, 100_000)

    param.valeur = "50"
    param.save()
    cout_50 = calculate_cost(100_000, 100_000)

    assert cout_50 > cout_20


@pytest.mark.django_db
def test_commission_yeki_sur_cout_derive_la_bonne_part():
    ParametreSysteme.objects.filter(cle="commission_ia_pourcent").update(valeur="20")
    # cout_total = base * 1.20 -> commission = cout_total * 20/120
    cout_total = 120
    commission = commission_yeki_sur_cout(cout_total)
    assert commission == 20  # base=100, commission=20, total=120


@pytest.mark.django_db
def test_cout_plafonne_au_solde_minimum():
    ParametreSysteme.objects.filter(cle="solde_min_ia").update(valeur="20")
    # Très peu de tokens -> coût de base quasi nul, doit être plafonné à 20
    cout = calculate_cost(1, 1)
    assert cout == 20
