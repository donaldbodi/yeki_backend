"""
Tests d'intégration P9.1 : câblage d'AccesMatricePermission sur les vues
Exercice (liste filtrée par étoiles, détail/démarrer/soumettre gatés par
instance). La logique de la matrice elle-même est testée unitairement dans
apps/core/tests/test_acces_service.py — ici on vérifie le CÂBLAGE réel
(réponses HTTP des vraies URLs), pas la règle.
"""

import pytest
from django.urls import reverse

from apps.evaluation.models import Exercice


@pytest.fixture
def exercice_2_etoiles(db, cours):
    return Exercice.objects.create(cours=cours, titre="Ex 2★", enonce="…", etoiles=2)


@pytest.fixture
def exercice_3_etoiles(db, cours):
    return Exercice.objects.create(cours=cours, titre="Ex 3★", enonce="…", etoiles=3)


@pytest.mark.django_db
def test_liste_exercices_gratuit_ne_voit_pas_au_dela_de_2_etoiles(
    client_apprenant, cours, exercice, exercice_2_etoiles, exercice_3_etoiles
):
    response = client_apprenant.get(f"/api/cours/{cours.id}/exercices/")
    assert response.status_code == 200
    ids = {e["id"] for e in response.data["results"]}
    assert exercice.id in ids
    assert exercice_2_etoiles.id in ids
    assert exercice_3_etoiles.id not in ids


@pytest.mark.django_db
def test_liste_exercices_premium_voit_tout(
    client_apprenant_premium, cours, exercice, exercice_2_etoiles, exercice_3_etoiles
):
    response = client_apprenant_premium.get(f"/api/cours/{cours.id}/exercices/")
    assert response.status_code == 200
    ids = {e["id"] for e in response.data["results"]}
    assert {exercice.id, exercice_2_etoiles.id, exercice_3_etoiles.id} <= ids


@pytest.mark.django_db
def test_detail_exercice_3_etoiles_bloque_en_gratuit(client_apprenant, exercice_3_etoiles):
    response = client_apprenant.get(f"/api/exercices/{exercice_3_etoiles.id}/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_detail_exercice_3_etoiles_accessible_en_premium(
    client_apprenant_premium, exercice_3_etoiles
):
    response = client_apprenant_premium.get(f"/api/exercices/{exercice_3_etoiles.id}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_demarrer_exercice_1_etoile_accessible_meme_gratuit(client_apprenant, exercice):
    response = client_apprenant.post(f"/api/exercices/{exercice.id}/demarrer/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_demarrer_exercice_2_etoiles_bloque_en_gratuit(client_apprenant, exercice_2_etoiles):
    response = client_apprenant.post(f"/api/exercices/{exercice_2_etoiles.id}/demarrer/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_demarrer_exercice_2_etoiles_accessible_en_premium(
    client_apprenant_premium, exercice_2_etoiles
):
    response = client_apprenant_premium.post(f"/api/exercices/{exercice_2_etoiles.id}/demarrer/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_evaluer_exercice_2_etoiles_bloque_en_gratuit(client_apprenant, exercice_2_etoiles):
    response = client_apprenant.post(
        f"/api/exercices/{exercice_2_etoiles.id}/evaluer/", {"reponses": {}}, format="json"
    )
    assert response.status_code == 403
