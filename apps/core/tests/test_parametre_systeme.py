"""
Tests P2.4 : ParametreSysteme — cache mémoire invalidé à l'écriture.
"""

import pytest

from apps.core.models import ParametreSysteme

# Nettoyage du cache déjà assuré par la fixture autouse `_cache_vide`
# (conftest.py racine, introduite en P1.6 pour les tests de throttling).


@pytest.mark.django_db
def test_get_retourne_le_default_si_absent():
    assert (
        ParametreSysteme.get("cle_inexistante", default="valeur_par_defaut") == "valeur_par_defaut"
    )


@pytest.mark.django_db
def test_get_lit_la_valeur_en_base():
    ParametreSysteme.objects.create(cle="test_p24", valeur="42")
    assert ParametreSysteme.get("test_p24") == "42"


@pytest.mark.django_db
def test_ecriture_invalide_le_cache_immediatement():
    p = ParametreSysteme.objects.create(cle="test_p24_cache", valeur="600")
    assert ParametreSysteme.get("test_p24_cache") == "600"  # peuple le cache

    p.valeur = "650"
    p.save()

    assert ParametreSysteme.get("test_p24_cache") == "650"


@pytest.mark.django_db
def test_suppression_invalide_le_cache():
    p = ParametreSysteme.objects.create(cle="test_p24_del", valeur="1")
    assert ParametreSysteme.get("test_p24_del") == "1"

    p.delete()

    assert ParametreSysteme.get("test_p24_del", default="absent") == "absent"


@pytest.mark.django_db
def test_valeur_vide_nest_pas_traitee_comme_absente():
    """Une chaîne vide ('') est une valeur réelle stockée, pas un cache miss."""
    ParametreSysteme.objects.create(cle="test_p24_vide", valeur="")
    assert ParametreSysteme.get("test_p24_vide", default="DEFAUT") == ""
