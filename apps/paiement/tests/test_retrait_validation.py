"""
Tests P9.4 : validation/refus des demandes de retrait par le Service
Client. Miroir de test_paiement_manuel_validation.py (P9.2), avec une
différence clé : un retrait a déjà débité (gelé) le wallet à la création
(DemanderRetraitView) — valider NE credite/débite RIEN, refuser DOIT
créditer `montant_brut` pour libérer le gel (l'inverse du paiement manuel,
qui ne débite jamais rien avant validation).
"""

import pytest
from django.urls import reverse

from apps.core.models import HistoriqueActivite
from apps.notifications.models import Notification
from apps.paiement.models import DemandeRetrait, YekiWallet


def _creer_demande(beneficiaire_profile, **kwargs):
    defaults = dict(
        montant_brut=3000,
        frais_operateur=0,
        montant_net=3000,
        operateur="orange_money",
        numero_destination="237690000000",
    )
    defaults.update(kwargs)
    return DemandeRetrait.objects.create(beneficiaire=beneficiaire_profile, **defaults)


def _url_valider(pk):
    return reverse("service-client-retrait-valider", args=[pk])


def _url_refuser(pk):
    return reverse("service-client-retrait-refuser", args=[pk])


@pytest.fixture
def demande_retrait(db, user_enseignant_cadre):
    return _creer_demande(user_enseignant_cadre.profile)


# ── Mes demandes / file d'attente ───────────────────────────────────────


@pytest.mark.django_db
def test_mes_demandes_liste_uniquement_celles_du_cadre_connecte(
    client_enseignant_cadre, user_enseignant_cadre, user_enseignant
):
    _creer_demande(user_enseignant_cadre.profile, numero_destination="237690000001")
    _creer_demande(user_enseignant.profile, numero_destination="237690000002")

    response = client_enseignant_cadre.get(reverse("retrait-mes-demandes"))
    assert response.status_code == 200
    numeros = {d["numero_destination"] for d in response.data["results"]}
    assert numeros == {"237690000001"}


@pytest.mark.django_db
def test_file_attente_403_si_non_service_client(client_enseignant_cadre):
    response = client_enseignant_cadre.get(reverse("service-client-retraits-liste"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_file_attente_filtre_en_attente_par_defaut_et_trie_par_fifo_avec_solde(
    client_service_client, user_enseignant_cadre
):
    wallet = YekiWallet.get_or_create_wallet(user_enseignant_cadre)
    wallet.solde = 7000
    wallet.save()

    d1 = _creer_demande(user_enseignant_cadre.profile, numero_destination="237690000001")
    d2 = _creer_demande(user_enseignant_cadre.profile, numero_destination="237690000002")
    d3 = _creer_demande(user_enseignant_cadre.profile, numero_destination="237690000003")
    d3.statut = "validee"
    d3.save()

    response = client_service_client.get(reverse("service-client-retraits-liste"))
    assert response.status_code == 200
    resultats = response.data["results"]
    ids = [d["id"] for d in resultats]
    assert d3.id not in ids  # filtré par défaut (statut != en_attente)
    assert ids == [d1.id, d2.id]  # FIFO

    # Exigence explicite du ticket : solde du bénéficiaire visible.
    assert all(d["solde_beneficiaire"] == 7000 for d in resultats)


# ── Valider — gardes de sécurité ────────────────────────────────────────


@pytest.mark.django_db
def test_valider_403_si_beneficiaire_egale_traite_par(client_service_client, user_service_client):
    demande = _creer_demande(user_service_client.profile)
    response = client_service_client.post(_url_valider(demande.id))
    assert response.status_code == 403
    demande.refresh_from_db()
    assert demande.statut == "en_attente"


@pytest.mark.django_db
def test_valider_409_si_demande_deja_traitee(client_service_client, demande_retrait):
    demande_retrait.statut = "validee"
    demande_retrait.save()
    response = client_service_client.post(_url_valider(demande_retrait.id))
    assert response.status_code == 409


@pytest.mark.django_db
def test_valider_403_si_non_service_client(client_enseignant_cadre, demande_retrait):
    response = client_enseignant_cadre.post(_url_valider(demande_retrait.id))
    assert response.status_code == 403


@pytest.mark.django_db
def test_valider_ne_touche_pas_au_wallet_change_juste_le_statut(
    client_service_client, user_enseignant_cadre, demande_retrait
):
    wallet = YekiWallet.get_or_create_wallet(user_enseignant_cadre)
    wallet.solde = 5000  # déjà "après-gel" — la création a déjà débité
    wallet.save()

    response = client_service_client.post(_url_valider(demande_retrait.id))
    assert response.status_code == 200
    assert response.data["statut"] == "validee"

    wallet.refresh_from_db()
    assert wallet.solde == 5000  # inchangé : aucune opération wallet à la validation

    demande_retrait.refresh_from_db()
    assert demande_retrait.statut == "validee"


@pytest.mark.django_db
def test_valider_renseigne_traite_par_et_date_traitement(
    client_service_client, user_service_client, demande_retrait
):
    response = client_service_client.post(_url_valider(demande_retrait.id))
    assert response.status_code == 200

    demande_retrait.refresh_from_db()
    assert demande_retrait.traite_par == user_service_client.profile
    assert demande_retrait.date_traitement is not None


@pytest.mark.django_db
def test_valider_journalise_dans_historiqueactivite(
    client_service_client, user_service_client, demande_retrait
):
    client_service_client.post(_url_valider(demande_retrait.id))
    assert HistoriqueActivite.objects.filter(
        action="retrait_validated", objet_id=demande_retrait.id, objet_type="DemandeRetrait"
    ).exists()


@pytest.mark.django_db
def test_valider_notifie_le_beneficiaire(
    client_service_client, user_enseignant_cadre, demande_retrait
):
    client_service_client.post(_url_valider(demande_retrait.id))
    assert Notification.objects.filter(
        utilisateur=user_enseignant_cadre, type="paiement"
    ).exists()


# ── Refuser — libération du gel ─────────────────────────────────────────


@pytest.mark.django_db
def test_refuser_400_si_motif_absent(client_service_client, demande_retrait):
    response = client_service_client.post(_url_refuser(demande_retrait.id))
    assert response.status_code == 400


@pytest.mark.django_db
def test_refuser_403_si_beneficiaire_egale_traite_par(client_service_client, user_service_client):
    demande = _creer_demande(user_service_client.profile)
    response = client_service_client.post(
        _url_refuser(demande.id), {"motif_refus": "Numéro invalide"}, format="json"
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_refuser_409_si_demande_deja_traitee(client_service_client, demande_retrait):
    demande_retrait.statut = "refusee"
    demande_retrait.save()
    response = client_service_client.post(
        _url_refuser(demande_retrait.id), {"motif_refus": "Test"}, format="json"
    )
    assert response.status_code == 409


@pytest.mark.django_db
def test_refuser_credite_exactement_montant_brut_pas_montant_net(
    client_service_client, user_enseignant_cadre
):
    wallet = YekiWallet.get_or_create_wallet(user_enseignant_cadre)
    wallet.solde = 2000  # solde après le gel (montant_brut=3000 déjà débité)
    wallet.save()

    demande = _creer_demande(
        user_enseignant_cadre.profile, montant_brut=3000, frais_operateur=300, montant_net=2700
    )

    response = client_service_client.post(
        _url_refuser(demande.id), {"motif_refus": "Numéro Mobile Money invalide"}, format="json"
    )
    assert response.status_code == 200

    wallet.refresh_from_db()
    # Libère le gel au montant BRUT (3000), pas au montant net (2700).
    assert wallet.solde == 5000

    demande.refresh_from_db()
    assert demande.statut == "refusee"
    assert demande.motif_refus == "Numéro Mobile Money invalide"


@pytest.mark.django_db
def test_refuser_journalise_dans_historiqueactivite(
    client_service_client, user_service_client, demande_retrait
):
    client_service_client.post(
        _url_refuser(demande_retrait.id), {"motif_refus": "Test"}, format="json"
    )
    assert HistoriqueActivite.objects.filter(
        action="retrait_refused", objet_id=demande_retrait.id, objet_type="DemandeRetrait"
    ).exists()


@pytest.mark.django_db
def test_refuser_notifie_le_beneficiaire(
    client_service_client, user_enseignant_cadre, demande_retrait
):
    client_service_client.post(
        _url_refuser(demande_retrait.id), {"motif_refus": "Test"}, format="json"
    )
    assert Notification.objects.filter(
        utilisateur=user_enseignant_cadre, type="paiement"
    ).exists()
