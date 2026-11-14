"""
Cycles d'un département (apps/formation/cycles.py) : calcul des dates,
limites, création par l'enseignant admin, fin d'abonnement et classement.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.formation.cycles import (
    cycle_pour,
    cycles_de_l_annee,
    erreurs_configuration,
    libelle_abonnement_cycle,
    nombre_max_cycles,
)
from apps.formation.models import Departement


def _dept(debut, duree, nombre, placement="suite", nom="Terminale C"):
    return SimpleNamespace(
        nom=nom,
        cycle_date_debut=debut,
        cycle_duree_mois=duree,
        cycle_nombre=nombre,
        cycle_placement=placement,
        periode=duree,
        date_debut_periode=None,
        created_at=None,
    )


def _bornes(dept, annee=0):
    return [(c.debut, c.dernier_jour) for c in cycles_de_l_annee(dept, annee)]


# ── Calcul ────────────────────────────────────────────────────────────────


def test_nombre_max_cycles():
    assert nombre_max_cycles(1) == 12
    assert nombre_max_cycles(3) == 4
    assert nombre_max_cycles(5) == 2
    assert nombre_max_cycles(12) == 1
    assert nombre_max_cycles(13) == 0


def test_cycles_a_la_suite():
    dept = _dept(date(2027, 1, 1), 3, 2, "suite")
    assert _bornes(dept) == [
        (date(2027, 1, 1), date(2027, 3, 31)),
        (date(2027, 4, 1), date(2027, 6, 30)),
    ]


def test_cycles_repartis_sur_l_annee():
    dept = _dept(date(2027, 1, 1), 3, 2, "repartis")
    assert _bornes(dept) == [
        (date(2027, 1, 1), date(2027, 3, 31)),
        (date(2027, 7, 1), date(2027, 9, 30)),
    ]


def test_reprise_automatique_l_annee_suivante():
    dept = _dept(date(2027, 1, 1), 6, 2)
    assert _bornes(dept, 1) == [
        (date(2028, 1, 1), date(2028, 6, 30)),
        (date(2028, 7, 1), date(2028, 12, 31)),
    ]
    assert cycle_pour(dept, date(2028, 8, 15)).debut == date(2028, 7, 1)


def test_cycle_en_cours_et_entre_deux_cycles():
    dept = _dept(date(2027, 1, 1), 3, 2, "repartis")
    assert cycle_pour(dept, date(2027, 2, 10)).numero == 1
    # Entre deux cycles : le cycle suivant.
    suivant = cycle_pour(dept, date(2027, 5, 1))
    assert (suivant.numero, suivant.debut) == (2, date(2027, 7, 1))
    # Avant le tout premier cycle : le premier.
    assert cycle_pour(dept, date(2026, 12, 1)).debut == date(2027, 1, 1)


def test_erreurs_configuration():
    assert erreurs_configuration(date(2027, 1, 1), 3, 4, "suite") == []
    assert erreurs_configuration(date(2027, 1, 1), 3, 5, "suite")  # > 12 // 3
    assert erreurs_configuration(date(2027, 1, 1), 0, 1, "suite")
    assert erreurs_configuration(None, 3, 1, "suite")
    assert erreurs_configuration(date(2027, 1, 1), 3, 1, "autre")


def test_libelle_abonnement():
    # Décision produit : toujours « Abonnement annuel », quel que soit le cycle.
    assert libelle_abonnement_cycle(_dept(date(2027, 1, 1), 12, 1)) == "Abonnement annuel"
    assert libelle_abonnement_cycle(_dept(date(2027, 1, 1), 4, 3)) == "Abonnement annuel"


# ── Création par l'enseignant admin ─────────────────────────────────────────


@pytest.fixture
def admin_avec_parcours(user_enseignant_admin, parcours):
    parcours.admin = user_enseignant_admin.profile
    parcours.save(update_fields=["admin"])
    return user_enseignant_admin


@pytest.mark.django_db
def test_creer_departement_avec_cycles(client_enseignant_admin, admin_avec_parcours):
    debut = timezone.localdate()
    response = client_enseignant_admin.post(
        reverse("departements-creer"),
        {
            "nom": "Terminale D",
            "cycle_date_debut": debut.isoformat(),
            "cycle_duree_mois": 4,
            "cycle_nombre": 3,
            "cycle_placement": "suite",
            "prix_annuel": 5000,
            "prix_mensuel": 1500,
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    assert response.data["libelle_abonnement_cycle"] == "Abonnement annuel"
    assert len(response.data["cycles"]) == 3
    departement = Departement.objects.get(pk=response.data["id"])
    assert departement.periode == 4
    # Le classement se termine à la fin du premier cycle.
    assert timezone.localtime(departement.date_fin_periode).date() == cycle_pour(departement).fin


@pytest.mark.django_db
def test_creer_departement_trop_de_cycles_400(client_enseignant_admin, admin_avec_parcours):
    response = client_enseignant_admin.post(
        reverse("departements-creer"),
        {
            "nom": "Terminale D",
            "cycle_date_debut": "2027-01-01",
            "cycle_duree_mois": 5,
            "cycle_nombre": 3,
        },
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "entre 1 et 2" in response.data["detail"]


# ── Abonnement annuel et forum ──────────────────────────────────────────────


@pytest.mark.django_db
def test_abonnement_annuel_dure_365_jours(departement, user_apprenant):
    from apps.paiement.models import AbonnementPremium
    from apps.paiement.services import finaliser_paiement

    departement.cycle_date_debut = timezone.localdate() - timedelta(days=10)
    departement.cycle_duree_mois = 3
    departement.cycle_nombre = 4
    departement.save()

    avant = timezone.now()
    finaliser_paiement(
        user_apprenant=user_apprenant,
        categorie="abonnement",
        montant=4000,
        moyen="manuel",
        departement=departement,
        type_abonnement="annuel",
    )
    abo = AbonnementPremium.objects.get(utilisateur=user_apprenant, departement=departement)
    assert abo.fin - avant >= timedelta(days=365)
    assert abo.fin - avant < timedelta(days=366)
    assert abo.est_actif


def _abonner(user, departement):
    from apps.paiement.models import AbonnementPremium

    AbonnementPremium.objects.create(
        utilisateur=user,
        departement=departement,
        type_abonnement="annuel",
        actif=True,
        fin=timezone.now() + timedelta(days=365),
    )


@pytest.mark.django_db
def test_forum_ouvert_pendant_un_cycle(departement, user_apprenant):
    from apps.core.services import AccesService
    from apps.forum.models import QuestionForum

    _abonner(user_apprenant, departement)
    departement.cycle_date_debut = timezone.localdate() - timedelta(days=10)
    departement.cycle_duree_mois = 3
    departement.cycle_nombre = 1
    departement.save()
    assert AccesService.peut_voir(user_apprenant, QuestionForum, departement=departement)
    assert AccesService.peut_soumettre(user_apprenant, QuestionForum, departement=departement)


@pytest.mark.django_db
def test_forum_ferme_hors_cycle_meme_abonne(departement, user_apprenant):
    from apps.core.services import AccesService
    from apps.forum.models import QuestionForum

    _abonner(user_apprenant, departement)
    # Un seul cycle de 3 mois, terminé il y a ~5 mois : on est entre deux cycles.
    departement.cycle_date_debut = timezone.localdate() - timedelta(days=240)
    departement.cycle_duree_mois = 3
    departement.cycle_nombre = 1
    departement.save()
    assert not AccesService.peut_voir(user_apprenant, QuestionForum, departement=departement)
    assert not AccesService.peut_soumettre(user_apprenant, QuestionForum, departement=departement)


@pytest.mark.django_db
def test_forum_ferme_sans_abonnement(departement, user_apprenant):
    from apps.core.services import AccesService
    from apps.forum.models import QuestionForum

    departement.cycle_date_debut = timezone.localdate() - timedelta(days=10)
    departement.save()
    assert not AccesService.peut_voir(user_apprenant, QuestionForum, departement=departement)
