"""
Tests P8.1 — deux bugs réels trouvés en vérifiant les règles métier du
ticket « réparer la création d'olympiades » :
1. La répartition 80/20 (paiement de participation) n'était PAS atomique
   (deux `@transaction.atomic` indépendants sur `debiter()`/`crediter()`).
2. La visibilité par niveau/cursus n'était appliquée NULLE PART à la
   lecture (ni la liste, ni l'inscription) — seulement à la notification
   lors de la création.

Couvre aussi le recalcul serveur de `date_fin_olympiade` en modification
(PATCH), sur le même principe qu'à la création : jamais acceptée du
client.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.evaluation.models import Olympiade
from apps.formation.models import Departement, Parcours
from apps.paiement.models import PaiementOlympiade, YekiWallet


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


# ── 1. Atomicité du paiement de participation (bug réel trouvé) ────────


@pytest.mark.django_db
def test_echec_credit_cadre_annule_le_debit_apprenant(
    monkeypatch, client_apprenant, user_apprenant, user_enseignant_cadre, olympiade_payante
):
    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    wallet.solde = 2000
    wallet.save()
    solde_initial = wallet.solde

    def _crediter_qui_echoue(self, *args, **kwargs):
        raise RuntimeError("panne simulée après le débit de l'apprenant")

    monkeypatch.setattr(YekiWallet, "crediter", _crediter_qui_echoue)

    # Le gestionnaire d'exceptions global du projet (apps/core/exceptions.py)
    # convertit l'exception non gérée en réponse 500 plutôt que de la
    # laisser remonter au client de test — on vérifie donc l'état en base,
    # pas une exception Python.
    response = client_apprenant.post(
        reverse("payer-participation-olympiade", args=[olympiade_payante.id]),
        {"montant": 1000},
        format="json",
    )
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    # Sans le `@transaction.atomic` ajouté sur la vue, `debiter()` (son
    # propre `@transaction.atomic` interne) aurait DÉJÀ committé avant que
    # `crediter()` n'échoue — l'apprenant resterait débité pour rien.
    wallet.refresh_from_db()
    assert wallet.solde == solde_initial
    assert not PaiementOlympiade.objects.filter(
        apprenant=user_apprenant, olympiade=olympiade_payante
    ).exists()


# ── 2. date_fin_olympiade recalculée au PATCH, jamais acceptée brute ───


@pytest.fixture
def olympiade_modifiable(user_enseignant_cadre):
    now = timezone.now()
    return Olympiade.objects.create(
        titre="Olympiade modifiable",
        date_ouverture_inscription=now - timedelta(days=1),
        date_cloture_inscription=now + timedelta(days=1),
        date_debut_olympiade=now + timedelta(days=2),
        date_fin_olympiade=now + timedelta(days=2, hours=2),
        duree_minutes=120,
        organisateur=user_enseignant_cadre.profile,
        est_validee=False,
    )


@pytest.mark.django_db
def test_modifier_ignore_date_fin_brute_et_la_recalcule(
    client_enseignant_cadre, olympiade_modifiable
):
    nouveau_debut = olympiade_modifiable.date_debut_olympiade + timedelta(days=1)
    date_fin_trompeuse = nouveau_debut + timedelta(days=99)  # valeur volontairement fausse

    response = client_enseignant_cadre.patch(
        reverse("modifier-olympiade", args=[olympiade_modifiable.id]),
        {
            "date_debut_olympiade": nouveau_debut.isoformat(),
            "duree_minutes": 90,
            "date_fin_olympiade": date_fin_trompeuse.isoformat(),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    olympiade_modifiable.refresh_from_db()
    assert olympiade_modifiable.date_fin_olympiade == nouveau_debut + timedelta(minutes=90)
    assert olympiade_modifiable.date_fin_olympiade != date_fin_trompeuse


# ── 3. Visibilité par niveau/cursus (bug réel trouvé) ──────────────────


@pytest.fixture
def departement_cible(user_enseignant_cadre):
    parcours = Parcours.objects.create(nom="Cursus Cible P8.1", type_parcours="cursus")
    return Departement.objects.create(
        nom="Département Cible P8.1", parcours=parcours, cadre=user_enseignant_cadre.profile
    )


@pytest.fixture
def olympiade_ciblee(user_enseignant_cadre, departement_cible):
    now = timezone.now()
    return Olympiade.objects.create(
        titre="Olympiade ciblée",
        date_ouverture_inscription=now - timedelta(days=1),
        date_cloture_inscription=now + timedelta(days=1),
        date_debut_olympiade=now + timedelta(days=2),
        date_fin_olympiade=now + timedelta(days=2, hours=2),
        duree_minutes=120,
        organisateur=user_enseignant_cadre.profile,
        niveaux_accessibles="Licence 1",  # ne correspond PAS au niveau par défaut de l'apprenant
    )


@pytest.mark.django_db
def test_liste_exclut_une_olympiade_hors_niveau_pour_un_apprenant(
    client_apprenant, olympiade_ciblee
):
    response = client_apprenant.get(reverse("liste-olympiades"))

    assert response.status_code == status.HTTP_200_OK
    ids = [o["id"] for o in response.data["results"]]
    assert olympiade_ciblee.id not in ids


@pytest.mark.django_db
def test_liste_exclut_une_olympiade_hors_cursus_pour_un_apprenant(
    client_apprenant, user_apprenant, user_enseignant_cadre, departement_cible
):
    now = timezone.now()
    olympiade = Olympiade.objects.create(
        titre="Olympiade autre cursus",
        date_ouverture_inscription=now - timedelta(days=1),
        date_cloture_inscription=now + timedelta(days=1),
        date_debut_olympiade=now + timedelta(days=2),
        date_fin_olympiade=now + timedelta(days=2, hours=2),
        duree_minutes=120,
        organisateur=user_enseignant_cadre.profile,
        niveaux_accessibles="Terminale",  # correspond au niveau de l'apprenant
    )
    # Cursus explicitement différent de celui de l'olympiade (departement_cible).
    user_apprenant.profile.cursus = "Cursus totalement différent"
    user_apprenant.profile.save()

    response = client_apprenant.get(reverse("liste-olympiades"))

    ids = [o["id"] for o in response.data["results"]]
    assert olympiade.id not in ids


@pytest.mark.django_db
def test_liste_montre_tout_a_un_enseignant(client_enseignant_cadre, olympiade_ciblee):
    response = client_enseignant_cadre.get(reverse("liste-olympiades"))

    assert response.status_code == status.HTTP_200_OK
    ids = [o["id"] for o in response.data["results"]]
    assert olympiade_ciblee.id in ids


@pytest.mark.django_db
def test_inscription_refusee_hors_niveau(client_apprenant, olympiade_ciblee):
    response = client_apprenant.post(reverse("inscrire-olympiade", args=[olympiade_ciblee.id]))

    assert response.status_code == status.HTTP_403_FORBIDDEN
