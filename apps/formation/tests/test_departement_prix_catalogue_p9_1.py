"""
Tests P9.1 : les 4 prix par département (prix_mensuel/prix_annuel
obligatoires, prix_presentiel_mensuel/prix_presentiel_annuel facultatifs)
et les labels catalogue "Offre gratuite"/"Promotion" (Departement.
label_catalogue, basé sur HistoriquePrixDepartement — P2.4). Vérifie aussi
que les prix legacy (prix/prix_presentiel) ne donnent jamais accès Premium
(AccesService), les deux axes étant orthogonaux.
"""

import pytest

from apps.core.services import AccesService
from apps.formation.models import CHAMPS_PRIX_HISTORISES, Departement, HistoriquePrixDepartement
from apps.formation.serializers import ApprenantDepartementDetailSerializer


@pytest.mark.django_db
def test_prix_mensuel_zero_donne_offre_gratuite(departement):
    assert departement.prix_mensuel == 0
    assert departement.label_catalogue() == "Offre gratuite"


@pytest.mark.django_db
def test_prix_mensuel_positif_sans_historique_ne_donne_aucun_label(departement):
    departement.prix_mensuel = 5000
    departement.save()
    assert departement.label_catalogue() is None


@pytest.mark.django_db
def test_baisse_de_prix_mensuel_donne_promotion(departement):
    departement.prix_mensuel = 5000
    departement.save()
    departement.prix_mensuel = 3000  # baisse -> "Promotion"
    departement.save()
    assert departement.label_catalogue() == "Promotion"


@pytest.mark.django_db
def test_baisse_de_prix_annuel_donne_promotion(departement):
    departement.prix_mensuel = 5000
    departement.prix_annuel = 50000
    departement.save()
    departement.prix_annuel = 30000  # baisse -> "Promotion"
    departement.save()
    assert departement.label_catalogue() == "Promotion"


@pytest.mark.django_db
def test_hausse_de_prix_ne_donne_aucun_label(departement):
    departement.prix_mensuel = 3000
    departement.save()
    departement.prix_mensuel = 5000  # hausse
    departement.save()
    assert departement.label_catalogue() is None


@pytest.mark.django_db
def test_champs_prix_historises_couvre_desormais_mensuel_et_annuel():
    assert "prix_mensuel" in CHAMPS_PRIX_HISTORISES
    assert "prix_annuel" in CHAMPS_PRIX_HISTORISES
    # Facultatifs — volontairement non historisés (motivation CDC limitée
    # aux champs obligatoires).
    assert "prix_presentiel_mensuel" not in CHAMPS_PRIX_HISTORISES
    assert "prix_presentiel_annuel" not in CHAMPS_PRIX_HISTORISES


@pytest.mark.django_db
def test_changement_de_prix_mensuel_cree_une_ligne_historique(departement):
    departement.prix_mensuel = 5000
    departement.save()
    ligne = HistoriquePrixDepartement.objects.get(departement=departement, champ="prix_mensuel")
    assert ligne.ancienne_valeur == 0
    assert ligne.nouvelle_valeur == 5000


@pytest.mark.django_db
def test_serializer_apprenant_departement_expose_les_4_prix_et_label(departement, user_apprenant):
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    departement.prix_mensuel = 5000
    departement.prix_annuel = 50000
    departement.prix_presentiel_mensuel = 1000
    departement.prix_presentiel_annuel = 10000
    departement.save()

    # `Request.user` a son propre getter/setter — l'affecter sur la requête
    # Django brute avant de l'envelopper dans `Request(...)` n'a aucun effet.
    drf_request = Request(APIRequestFactory().get("/"))
    drf_request.user = user_apprenant
    data = ApprenantDepartementDetailSerializer(departement, context={"request": drf_request}).data

    assert data["prix_mensuel"] == 5000
    assert data["prix_annuel"] == 50000
    assert data["prix_presentiel_mensuel"] == 1000
    assert data["prix_presentiel_annuel"] == 10000
    assert data["label_catalogue"] is None


@pytest.mark.django_db
def test_creation_departement_accepte_les_4_prix(client_enseignant_admin, user_enseignant_admin, parcours):
    from apps.accounts.models import Profile

    profile = Profile.objects.get(user=user_enseignant_admin)
    parcours.admin = profile
    parcours.save(update_fields=["admin"])

    response = client_enseignant_admin.post(
        "/api/departements/creer/",
        {
            "nom": "Nouveau département",
            "parcours_id": parcours.id,
            "periode": 6,
            "prix_mensuel": 5000,
            "prix_annuel": 50000,
            "prix_presentiel_mensuel": 1000,
            "prix_presentiel_annuel": 10000,
        },
        format="multipart",
    )
    assert response.status_code == 201
    departement = Departement.objects.get(nom="Nouveau département")
    assert departement.prix_mensuel == 5000
    assert departement.prix_annuel == 50000
    assert departement.prix_presentiel_mensuel == 1000
    assert departement.prix_presentiel_annuel == 10000


@pytest.mark.django_db
def test_mise_a_jour_manuelle_departement_cadre_accepte_les_4_prix(
    client_enseignant_cadre, user_enseignant_cadre, departement
):
    from apps.accounts.models import Profile

    profile = Profile.objects.get(user=user_enseignant_cadre)
    departement.cadre = profile
    departement.save(update_fields=["cadre"])

    response = client_enseignant_cadre.patch(
        f"/api/enseignant/cadre/departement/{departement.id}/update/",
        {
            "prix_mensuel": 6000,
            "prix_annuel": 60000,
            "prix_presentiel_mensuel": 2000,
            "prix_presentiel_annuel": 20000,
        },
        format="json",
    )
    assert response.status_code == 200
    departement.refresh_from_db()
    assert departement.prix_mensuel == 6000
    assert departement.prix_annuel == 60000
    assert departement.prix_presentiel_mensuel == 2000
    assert departement.prix_presentiel_annuel == 20000


@pytest.mark.django_db
def test_prix_et_prix_presentiel_legacy_ne_donnent_jamais_acces_premium(user_apprenant):
    """Régression explicite (le ticket demande de « vérifier que le code
    respecte » cette règle) : payer prix/prix_presentiel d'un département
    n'a jamais donné — et ne doit jamais donner — accès à AbonnementPremium,
    les deux axes de tarification étant orthogonaux."""
    assert AccesService.est_premium(user_apprenant) is False
