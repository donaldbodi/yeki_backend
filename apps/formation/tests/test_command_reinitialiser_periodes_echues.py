"""
Tests P12.4 : commande de gestion `reinitialiser_periodes_echues` —
`Departement.reinitialiser_periode()` (couverte séparément par
`test_reinitialiser_periode.py`) ne vérifie elle-même aucune date ; ces
tests couvrent la sélection des départements réellement échus, faite par
la commande, ainsi que `--dry-run` et `--departement_id`.
"""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.formation.models import Departement, Parcours


def _executer_commande(**options):
    out = StringIO()
    call_command("reinitialiser_periodes_echues", stdout=out, **options)
    return out.getvalue()


@pytest.mark.django_db
def test_departement_echu_est_reinitialise(departement):
    ancien_debut = departement.date_debut_periode
    departement.date_fin_periode = timezone.now() - timedelta(days=1)
    departement.save(update_fields=["date_fin_periode"])

    _executer_commande()

    departement.refresh_from_db()
    assert departement.date_debut_periode > ancien_debut
    assert departement.date_fin_periode > departement.date_debut_periode


@pytest.mark.django_db
def test_departement_non_echu_reste_intact(departement):
    ancien_debut = departement.date_debut_periode
    ancienne_fin = timezone.now() + timedelta(days=30)
    departement.date_fin_periode = ancienne_fin
    departement.save(update_fields=["date_fin_periode"])

    _executer_commande()

    departement.refresh_from_db()
    assert departement.date_debut_periode == ancien_debut
    assert departement.date_fin_periode == ancienne_fin


@pytest.mark.django_db
def test_departement_sans_date_fin_periode_non_selectionne(departement):
    assert departement.date_fin_periode is None
    ancien_debut = departement.date_debut_periode

    _executer_commande()

    departement.refresh_from_db()
    assert departement.date_debut_periode == ancien_debut
    assert departement.date_fin_periode is None


@pytest.mark.django_db
def test_dry_run_ne_modifie_rien(departement):
    ancien_debut = departement.date_debut_periode
    ancienne_fin = timezone.now() - timedelta(days=1)
    departement.date_fin_periode = ancienne_fin
    departement.save(update_fields=["date_fin_periode"])

    sortie = _executer_commande(dry_run=True)

    departement.refresh_from_db()
    assert departement.date_debut_periode == ancien_debut
    assert departement.date_fin_periode == ancienne_fin
    assert "dry-run" in sortie


@pytest.mark.django_db
def test_departement_id_limite_la_portee(departement):
    parcours2 = Parcours.objects.create(nom="Cursus Test 2", type_parcours="cursus")
    departement2 = Departement.objects.create(nom="Département Test 2", parcours=parcours2)

    departement.date_fin_periode = timezone.now() - timedelta(days=1)
    departement.save(update_fields=["date_fin_periode"])
    departement2.date_fin_periode = timezone.now() - timedelta(days=1)
    departement2.save(update_fields=["date_fin_periode"])

    ancien_debut_2 = departement2.date_debut_periode

    _executer_commande(departement_id=departement.id)

    departement.refresh_from_db()
    departement2.refresh_from_db()
    assert departement.date_fin_periode > timezone.now()
    assert departement2.date_debut_periode == ancien_debut_2
