"""
Tests P9.6 : `GET /api/admin/transactions/` (filtres département/catégorie/
date/statut) et `GET /api/admin/dashboard-financier/` (agrégats). Vérifie
en particulier le point comptable explicitement signalé par le ticket :
les splits 30/70 (formation) et 80/20 (olympiade) doivent apparaître comme
des champs SÉPARÉS et correctement signés, jamais fusionnés, et la dette
envers les cadres (`total_du_aux_cadres`) ne doit JAMAIS être mélangée au
"total encaissé".
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile
from apps.paiement.models import Paiement, YekiWallet


def _creer_paiement(utilisateur, **kwargs):
    defaults = dict(
        type_paiement="recharge_wallet",
        moyen="cinetpay",
        montant=1000,
        statut="succes",
    )
    defaults.update(kwargs)
    return Paiement.objects.create(utilisateur=utilisateur, **defaults)


@pytest.mark.django_db
def test_transactions_403_si_non_admin(client_apprenant):
    response = client_apprenant.get(reverse("admin-transactions"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_dashboard_financier_403_si_non_admin(client_apprenant):
    response = client_apprenant.get(reverse("admin-dashboard-financier"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_filtre_departement_isole(client_admin, user_apprenant, departement, user_enseignant_cadre):
    departement.cadre = Profile.objects.get(user=user_enseignant_cadre)
    departement.save(update_fields=["cadre"])

    p1 = _creer_paiement(
        user_apprenant, type_paiement="acces_departement", montant=10000,
        commission_yeki=3000, departement=departement,
    )
    _creer_paiement(user_apprenant, type_paiement="recharge_wallet", montant=2000)

    response = client_admin.get(reverse("admin-transactions"), {"departement": departement.id})
    assert response.status_code == 200
    ids = [row["id"] for row in response.data["results"]]
    assert ids == [p1.id]


@pytest.mark.django_db
def test_filtre_categorie_isole(client_admin, user_apprenant):
    p_olymp = _creer_paiement(
        user_apprenant, type_paiement="olympiade", montant=100, commission_yeki=80
    )
    _creer_paiement(user_apprenant, type_paiement="recharge_wallet", montant=2000)

    response = client_admin.get(reverse("admin-transactions"), {"categorie": "olympiade"})
    assert response.status_code == 200
    ids = [row["id"] for row in response.data["results"]]
    assert ids == [p_olymp.id]


@pytest.mark.django_db
def test_filtre_statut_isole(client_admin, user_apprenant):
    p_echec = _creer_paiement(user_apprenant, statut="echec")
    _creer_paiement(user_apprenant, statut="succes")

    response = client_admin.get(reverse("admin-transactions"), {"statut": "echec"})
    assert response.status_code == 200
    ids = [row["id"] for row in response.data["results"]]
    assert ids == [p_echec.id]


@pytest.mark.django_db
def test_filtre_dates_isole(client_admin, user_apprenant):
    p_ancien = _creer_paiement(user_apprenant, montant=500)
    Paiement.objects.filter(pk=p_ancien.id).update(date=timezone.now() - timedelta(days=30))
    p_recent = _creer_paiement(user_apprenant, montant=700)

    du = (timezone.now() - timedelta(days=1)).date().isoformat()
    response = client_admin.get(reverse("admin-transactions"), {"du": du})
    assert response.status_code == 200
    ids = [row["id"] for row in response.data["results"]]
    assert ids == [p_recent.id]


@pytest.mark.django_db
def test_splits_30_70_et_80_20_separes_et_signes(
    client_admin, user_apprenant, departement, user_enseignant_cadre
):
    departement.cadre = Profile.objects.get(user=user_enseignant_cadre)
    departement.save(update_fields=["cadre"])

    p_formation = _creer_paiement(
        user_apprenant, type_paiement="acces_departement", montant=10000,
        commission_yeki=3000, departement=departement,
    )
    p_olympiade = _creer_paiement(
        user_apprenant, type_paiement="olympiade", montant=100, commission_yeki=80
    )
    p_recharge = _creer_paiement(user_apprenant, type_paiement="recharge_wallet", montant=2000)

    response = client_admin.get(reverse("admin-transactions"))
    assert response.status_code == 200
    par_id = {row["id"]: row for row in response.data["results"]}

    # Formation : 30% Yéki / 70% tiers (cadre).
    assert par_id[p_formation.id]["part_yeki"] == 3000
    assert par_id[p_formation.id]["part_tiers_beneficiaire"] == 7000

    # Olympiade : 80% Yéki / 20% tiers — proportions INVERSES, sur le même
    # écran, jamais confondues.
    assert par_id[p_olympiade.id]["part_yeki"] == 80
    assert par_id[p_olympiade.id]["part_tiers_beneficiaire"] == 20

    # Recharge : aucun tiers par construction — 0, pas le montant entier.
    assert par_id[p_recharge.id]["part_yeki"] == 0
    assert par_id[p_recharge.id]["part_tiers_beneficiaire"] == 0


@pytest.mark.django_db
def test_wallet_exclu_du_total_encaisse_et_de_la_ventilation(client_admin, user_apprenant):
    """
    Un paiement `moyen="wallet"` redistribue de l'argent DÉJÀ compté comme
    encaissé lors de la recharge d'origine — il est donc exclu à la fois du
    total ET de la ventilation par catégorie (les deux partagent la même
    base, pour que leur somme reste cohérente). Il reste néanmoins visible
    ligne par ligne dans `AdminTransactionsView` (non testé ici), qui liste
    tous les `Paiement` sans cette exclusion.
    """
    _creer_paiement(user_apprenant, type_paiement="olympiade_participation", montant=500, moyen="wallet")
    _creer_paiement(user_apprenant, type_paiement="recharge_wallet", montant=1000, moyen="cinetpay")

    response = client_admin.get(reverse("admin-dashboard-financier"))
    assert response.status_code == 200
    data = response.data

    assert data["total_encaisse"] == 1000  # le paiement wallet (500) est exclu
    assert data["ventilation_categorie"]["olympiade"] == 0  # exclu ici aussi
    assert data["ventilation_categorie"]["recharge"] == 1000


@pytest.mark.django_db
def test_wallet_reste_visible_ligne_par_ligne_dans_la_liste_transactions(client_admin, user_apprenant):
    p_wallet = _creer_paiement(
        user_apprenant, type_paiement="olympiade_participation", montant=500, moyen="wallet"
    )

    response = client_admin.get(reverse("admin-transactions"))
    assert response.status_code == 200
    ids = [row["id"] for row in response.data["results"]]
    assert p_wallet.id in ids  # visible en détail, même si exclu des agrégats


@pytest.mark.django_db
def test_total_du_aux_cadres_jamais_dans_total_encaisse(
    client_admin, user_apprenant, user_enseignant_cadre
):
    wallet_cadre = YekiWallet.get_or_create_wallet(user_enseignant_cadre)
    wallet_cadre.solde = 15000
    wallet_cadre.save()

    _creer_paiement(user_apprenant, type_paiement="recharge_wallet", montant=1000, moyen="cinetpay")

    response = client_admin.get(reverse("admin-dashboard-financier"))
    assert response.status_code == 200
    data = response.data

    assert data["total_du_aux_cadres"] == 15000
    assert data["total_encaisse"] == 1000  # jamais additionné à la dette cadre


@pytest.mark.django_db
def test_solde_compte_ia_reutilise_le_modele_existant(client_admin):
    from apps.paiement.models import YekiCompteIA

    YekiCompteIA.crediter_commission(250)
    YekiCompteIA.crediter_commission(150)

    response = client_admin.get(reverse("admin-dashboard-financier"))
    assert response.status_code == 200
    assert response.data["solde_compte_ia"] == 400


@pytest.mark.django_db
def test_demandes_en_attente_et_delai_moyen(client_admin, user_apprenant, user_enseignant_cadre):
    from apps.paiement.models import DemandePaiementManuelle, DemandeRetrait

    DemandePaiementManuelle.objects.create(
        apprenant=user_apprenant.profile,
        categorie="recharge",
        montant=1000,
        operateur="orange_money",
        id_transaction="TXN-DASH-1",
        statut="en_attente",
    )
    demande_traitee = DemandePaiementManuelle.objects.create(
        apprenant=user_apprenant.profile,
        categorie="recharge",
        montant=1000,
        operateur="orange_money",
        id_transaction="TXN-DASH-2",
        statut="validee",
    )
    DemandePaiementManuelle.objects.filter(pk=demande_traitee.id).update(
        date_creation=timezone.now() - timedelta(minutes=30),
        date_traitement=timezone.now(),
    )

    response = client_admin.get(reverse("admin-dashboard-financier"))
    assert response.status_code == 200
    data = response.data

    assert data["demandes_en_attente"]["paiement"] == 1
    assert data["delai_moyen_minutes"]["paiement"] >= 29
