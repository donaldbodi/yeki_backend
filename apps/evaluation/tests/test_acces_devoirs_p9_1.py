"""
Tests d'intégration P9.1 : câblage d'AccesMatricePermission sur les vues
Devoir apprenant — "PAS de devoir" en gratuit, tout-ou-rien. La logique de
la matrice elle-même est testée unitairement dans
apps/core/tests/test_acces_service.py — ici on vérifie le CÂBLAGE réel.
"""

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_liste_devoirs_bloquee_en_gratuit(client_apprenant, devoir):
    response = client_apprenant.get(reverse("liste-devoirs"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_liste_devoirs_accessible_en_premium(client_apprenant_premium, devoir):
    response = client_apprenant_premium.get(reverse("liste-devoirs"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_detail_devoir_bloque_en_gratuit(client_apprenant, devoir):
    response = client_apprenant.get(reverse("detail-devoir", args=[devoir.id]))
    assert response.status_code == 403


@pytest.mark.django_db
def test_detail_devoir_accessible_en_premium(client_apprenant_premium, devoir):
    response = client_apprenant_premium.get(reverse("detail-devoir", args=[devoir.id]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_demarrer_devoir_bloque_en_gratuit(client_apprenant, devoir):
    response = client_apprenant.post(reverse("demarrer-devoir", args=[devoir.id]))
    assert response.status_code == 403


@pytest.mark.django_db
def test_demarrer_devoir_accessible_en_premium(client_apprenant_premium, devoir):
    response = client_apprenant_premium.post(reverse("demarrer-devoir", args=[devoir.id]))
    assert response.status_code == 200
