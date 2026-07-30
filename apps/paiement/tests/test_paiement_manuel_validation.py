"""
Tests P9.2 : validation/refus des demandes de paiement manuel par le
Service Client. Ne teste PAS l'IntegrityError (operateur, id_transaction)
déjà couverte dans test_paiement_manuel.py (P2.4, SoumettrePaiementManuelView
non modifiée sur ce point).
"""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.accounts.models import Profile
from apps.core.models import HistoriqueActivite
from apps.evaluation.models import Olympiade
from apps.formation.models import DemandeAccesFormation
from apps.notifications.models import Notification
from apps.paiement.models import (
    AbonnementPremium,
    DemandePaiementManuelle,
    Paiement,
    PaiementOlympiade,
    YekiWallet,
)


def _creer_demande(apprenant_profile, **kwargs):
    defaults = dict(
        categorie="recharge",
        montant=2000,
        operateur="orange_money",
        id_transaction=f"TXN-{apprenant_profile.id}-{kwargs.get('categorie', 'x')}",
    )
    defaults.update(kwargs)
    return DemandePaiementManuelle.objects.create(apprenant=apprenant_profile, **defaults)


def _url_valider(pk):
    return reverse("service-client-paiement-valider", args=[pk])


def _url_refuser(pk):
    return reverse("service-client-paiement-refuser", args=[pk])


@pytest.fixture
def demande_recharge(db, user_apprenant):
    return _creer_demande(user_apprenant.profile, categorie="recharge", montant=1500)


# ── Mes demandes / file d'attente ───────────────────────────────────────


@pytest.mark.django_db
def test_mes_demandes_liste_uniquement_celles_de_lapprenant_connecte(
    client_apprenant, user_apprenant, user_enseignant
):
    _creer_demande(user_apprenant.profile, id_transaction="TXN-MOI")
    _creer_demande(user_enseignant.profile, id_transaction="TXN-AUTRE")

    response = client_apprenant.get(reverse("paiement-manuel-mes-demandes"))
    assert response.status_code == 200
    ids_transaction = {d["id_transaction"] for d in response.data["results"]}
    assert ids_transaction == {"TXN-MOI"}


@pytest.mark.django_db
def test_file_attente_403_si_non_service_client(client_apprenant):
    response = client_apprenant.get(reverse("service-client-paiements-liste"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_file_attente_filtre_en_attente_par_defaut_et_trie_par_fifo(
    client_service_client, user_apprenant
):
    d1 = _creer_demande(user_apprenant.profile, id_transaction="TXN-1")
    d2 = _creer_demande(user_apprenant.profile, id_transaction="TXN-2")
    d3 = _creer_demande(user_apprenant.profile, id_transaction="TXN-3")
    d3.statut = "validee"
    d3.save()

    response = client_service_client.get(reverse("service-client-paiements-liste"))
    assert response.status_code == 200
    resultats = response.data["results"]
    ids = [d["id"] for d in resultats]
    assert d3.id not in ids  # filtré par défaut (statut != en_attente)
    assert ids == [d1.id, d2.id]  # FIFO


# ── Valider — gardes de sécurité ────────────────────────────────────────


@pytest.mark.django_db
def test_valider_403_si_apprenant_egale_traite_par(client_service_client, user_service_client):
    demande = _creer_demande(user_service_client.profile, id_transaction="TXN-SELF")
    response = client_service_client.post(_url_valider(demande.id))
    assert response.status_code == 403
    demande.refresh_from_db()
    assert demande.statut == "en_attente"


@pytest.mark.django_db
def test_valider_409_si_demande_deja_traitee(client_service_client, demande_recharge):
    demande_recharge.statut = "validee"
    demande_recharge.save()
    response = client_service_client.post(_url_valider(demande_recharge.id))
    assert response.status_code == 409


# ── Valider — catégorie recharge ────────────────────────────────────────


@pytest.mark.django_db
def test_valider_categorie_recharge_credite_le_wallet_sans_commission(
    client_service_client, user_apprenant, demande_recharge
):
    response = client_service_client.post(_url_valider(demande_recharge.id))
    assert response.status_code == 200

    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    assert wallet.solde == 1500

    paiement = Paiement.objects.get(demande_manuelle=demande_recharge)
    assert paiement.type_paiement == "recharge_wallet"
    assert paiement.commission_yeki == 0
    assert paiement.montant == 1500

    demande_recharge.refresh_from_db()
    assert demande_recharge.statut == "validee"
    assert demande_recharge.montant_constate == 1500


# ── Valider — catégorie abonnement ──────────────────────────────────────


@pytest.mark.django_db
def test_valider_categorie_abonnement_nouveau_cree_labonnement(
    client_service_client, user_apprenant
):
    demande = _creer_demande(
        user_apprenant.profile, categorie="abonnement", montant=1500,
        type_abonnement="mensuel", id_transaction="TXN-ABO-NEW",
    )
    response = client_service_client.post(_url_valider(demande.id))
    assert response.status_code == 200

    abo = AbonnementPremium.objects.get(utilisateur=user_apprenant)
    assert abo.est_actif is True
    assert abo.type_abonnement == "mensuel"


@pytest.mark.django_db
def test_valider_categorie_abonnement_existant_renouvelle(
    client_service_client, user_apprenant
):
    AbonnementPremium.objects.create(
        utilisateur=user_apprenant, type_abonnement="mensuel", actif=True,
        fin=timezone.now() + timedelta(days=2),
    )
    demande = _creer_demande(
        user_apprenant.profile, categorie="abonnement", montant=13000,
        type_abonnement="annuel", id_transaction="TXN-ABO-RENEW",
    )
    response = client_service_client.post(_url_valider(demande.id))
    assert response.status_code == 200

    abo = AbonnementPremium.objects.get(utilisateur=user_apprenant)
    assert abo.type_abonnement == "annuel"
    assert (abo.fin - timezone.now()).days >= 300


# ── Valider — catégorie olympiade ────────────────────────────────────────


@pytest.fixture
def olympiade_avec_cadre(db, departement):
    cadre = Profile.objects.create(
        user=User.objects.create_user(username="cadre_olympiade_test", password="Test1234!"),
        user_type="enseignant_cadre",
    )
    now = timezone.now()
    return Olympiade.objects.create(
        titre="Olympiade Test P9.2",
        organisateur=cadre,
        date_ouverture_inscription=now,
        date_cloture_inscription=now + timedelta(days=1),
        date_debut_olympiade=now + timedelta(days=2),
        date_fin_olympiade=now + timedelta(days=2, hours=2),
        demande_paiement_participants=True,
        prix_participation=100,
    )


@pytest.mark.django_db
def test_valider_categorie_olympiade_credite_80_20_et_debloque_paiementolympiade(
    client_service_client, user_apprenant, olympiade_avec_cadre
):
    demande = _creer_demande(
        user_apprenant.profile, categorie="olympiade", montant=100,
        objet_id=olympiade_avec_cadre.id, id_transaction="TXN-OLYMP",
    )
    response = client_service_client.post(_url_valider(demande.id))
    assert response.status_code == 200

    paiement_olympiade = PaiementOlympiade.objects.get(
        apprenant=user_apprenant, olympiade=olympiade_avec_cadre
    )
    assert paiement_olympiade.statut == "paye"
    assert paiement_olympiade.montant == 100

    wallet_cadre = YekiWallet.get_or_create_wallet(olympiade_avec_cadre.organisateur.user)
    assert wallet_cadre.solde == 20  # 20% de 100

    paiement = Paiement.objects.get(demande_manuelle=demande)
    assert paiement.commission_yeki == 80  # 80% de 100


# ── Valider — catégorie formation ───────────────────────────────────────


@pytest.mark.django_db
def test_valider_categorie_formation_credite_30_70_et_ajoute_apprenants_autorises(
    client_service_client, user_apprenant, departement, user_enseignant_cadre
):
    departement.cadre = Profile.objects.get(user=user_enseignant_cadre)
    departement.save(update_fields=["cadre"])

    demande = _creer_demande(
        user_apprenant.profile, categorie="formation", montant=10000,
        departement=departement, id_transaction="TXN-FORM",
    )
    response = client_service_client.post(_url_valider(demande.id))
    assert response.status_code == 200

    demande_acces = DemandeAccesFormation.objects.get(
        apprenant=user_apprenant, departement=departement
    )
    assert demande_acces.statut == "acceptee"
    # Le vrai critère d'accès (ApprenantDepartementDetailSerializer.get_est_accessible)
    assert user_apprenant in departement.apprenants_autorises.all()

    wallet_cadre = YekiWallet.get_or_create_wallet(user_enseignant_cadre)
    assert wallet_cadre.solde == 7000  # 70% de 10000

    paiement = Paiement.objects.get(demande_manuelle=demande)
    assert paiement.commission_yeki == 3000  # 30% de 10000


# ── Valider — catégorie présentiel ──────────────────────────────────────


@pytest.mark.django_db
def test_valider_categorie_presentiel_trace_le_paiement_sans_deblocage_supplementaire(
    client_service_client, user_apprenant
):
    demande = _creer_demande(
        user_apprenant.profile, categorie="presentiel", montant=5000, id_transaction="TXN-PRES"
    )
    response = client_service_client.post(_url_valider(demande.id))
    assert response.status_code == 200

    paiement = Paiement.objects.get(demande_manuelle=demande)
    assert paiement.type_paiement == "supplement_presentiel"
    assert paiement.commission_yeki == 0


# ── Écart de montant / montant constaté ─────────────────────────────────


@pytest.mark.django_db
def test_valider_ecart_montant_journalise_dans_historiqueactivite(
    client_service_client, demande_recharge
):
    response = client_service_client.post(
        _url_valider(demande_recharge.id), {"montant_constate": 1400}, format="json"
    )
    assert response.status_code == 200
    assert response.data["ecart"] == -100

    ligne = HistoriqueActivite.objects.get(action="ecart_montant_paiement")
    assert ligne.data["declare"] == 1500
    assert ligne.data["constate"] == 1400
    assert ligne.data["ecart"] == -100


@pytest.mark.django_db
def test_valider_sans_montant_constate_utilise_le_montant_declare(
    client_service_client, demande_recharge, user_apprenant
):
    response = client_service_client.post(_url_valider(demande_recharge.id))
    assert response.status_code == 200
    assert response.data["ecart"] == 0
    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    assert wallet.solde == demande_recharge.montant


@pytest.mark.django_db
def test_valider_paiement_visible_dans_historique_paiements_view(
    client_service_client, client_apprenant, demande_recharge
):
    client_service_client.post(_url_valider(demande_recharge.id))
    response = client_apprenant.get(reverse("paiements-historique"))
    assert response.status_code == 200
    # HistoriquePaiementsView sérialise via get_type_paiement_display() (le
    # libellé humain), pas la clé brute du choix.
    types = [p["type_paiement"] for p in response.data["results"]]
    assert "Recharge portefeuille (manuel)" in types


@pytest.mark.django_db
def test_valider_notifie_lapprenant(client_service_client, user_apprenant, demande_recharge):
    client_service_client.post(_url_valider(demande_recharge.id))
    assert Notification.objects.filter(utilisateur=user_apprenant, type="paiement").exists()


# ── Refuser ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_refuser_400_si_motif_absent(client_service_client, demande_recharge):
    response = client_service_client.post(_url_refuser(demande_recharge.id))
    assert response.status_code == 400
    demande_recharge.refresh_from_db()
    assert demande_recharge.statut == "en_attente"


@pytest.mark.django_db
def test_refuser_ok_change_statut_et_notifie(
    client_service_client, user_apprenant, demande_recharge
):
    response = client_service_client.post(
        _url_refuser(demande_recharge.id), {"motif_refus": "ID de transaction introuvable"},
        format="json",
    )
    assert response.status_code == 200
    demande_recharge.refresh_from_db()
    assert demande_recharge.statut == "refusee"
    assert demande_recharge.motif_refus == "ID de transaction introuvable"
    assert Notification.objects.filter(utilisateur=user_apprenant, type="paiement").exists()
    # Aucun rollback financier nécessaire : rien n'a été crédité.
    wallet = YekiWallet.get_or_create_wallet(user_apprenant)
    assert wallet.solde == 0


@pytest.mark.django_db
def test_refuser_403_si_apprenant_egale_traite_par(client_service_client, user_service_client):
    demande = _creer_demande(user_service_client.profile, id_transaction="TXN-SELF-REFUS")
    response = client_service_client.post(
        _url_refuser(demande.id), {"motif_refus": "test"}, format="json"
    )
    assert response.status_code == 403
