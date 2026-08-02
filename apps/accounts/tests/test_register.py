"""
Tests d'inscription (P1.6) : parcours/département/niveau obligatoires
(CDC_BACKEND §13.2 — voir docs/API_FOUNDATIONS.md pour la justification du
changement de comportement : ces 3 champs n'étaient pas exigés auparavant).
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.formation.models import Parcours

User = get_user_model()


def _payload_base(**overrides):
    payload = {
        "email": "nouvel.apprenant@yeki.test",
        "name": "Nouvel Apprenant",
        "username": "nouvel_apprenant",
        "password": "MotDePasse123",
        "user_type": "apprenant",
        # Ajoutés au ticket "inscription (2 champs + filtre parcours)" —
        # required=True côté RegisterSerializer, voir docs/ecarts/
        # p2_inscription_cursus_root_cause.md.
        "phone": "690000000",
        "date_naissance": "2005-01-01",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_inscription_sans_parcours_departement_niveau_400(departement):
    client = APIClient()
    response = client.post(reverse("register"), _payload_base(), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    fields = response.data["error"]["fields"]
    assert "parcours" in fields
    assert "departement" in fields
    assert "niveau" in fields


@pytest.mark.django_db
def test_inscription_departement_hors_parcours_400(departement):
    """Le département fourni n'appartient pas au parcours fourni → incohérence."""
    autre_parcours = Parcours.objects.create(nom="Autre Parcours", type_parcours="formation")

    client = APIClient()
    response = client.post(
        reverse("register"),
        _payload_base(
            parcours=autre_parcours.id,
            departement=departement.id,
            niveau="Terminale",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "parcours" in response.data["error"]["fields"]


@pytest.mark.django_db
def test_inscription_complete_valide_201(parcours, departement):
    client = APIClient()
    response = client.post(
        reverse("register"),
        _payload_base(parcours=parcours.id, departement=departement.id, niveau="Terminale"),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["role"] == "apprenant"


@pytest.mark.django_db
def test_inscription_name_persiste_sur_user_first_last_name(parcours, departement):
    """
    P5.4 : "name" était exigé par le sérialiseur mais jamais écrit nulle
    part (ni User, ni Profile) — corrigé, scindé sur le premier espace.
    """
    client = APIClient()
    response = client.post(
        reverse("register"),
        _payload_base(
            name="Aïcha Ndongo",
            parcours=parcours.id,
            departement=departement.id,
            niveau="Terminale",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    user = User.objects.get(username="nouvel_apprenant")
    assert user.first_name == "Aïcha"
    assert user.last_name == "Ndongo"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "user_type",
    ["admin", "enseignant_admin", "enseignant_cadre", "enseignant_principal", "service_client"],
)
def test_inscription_publique_refuse_les_roles_privilegies(parcours, departement, user_type):
    """
    P5.4 : faille de sécurité corrigée — l'auto-inscription publique
    (AllowAny) ne doit jamais permettre de choisir un rôle privilégié.
    """
    client = APIClient()
    response = client.post(
        reverse("register"),
        _payload_base(
            user_type=user_type,
            parcours=parcours.id,
            departement=departement.id,
            niveau="Terminale",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "user_type" in response.data["error"]["fields"]
    assert not User.objects.filter(username="nouvel_apprenant").exists()


@pytest.mark.django_db
def test_inscription_derive_cursus_depuis_parcours_selectionne(parcours, departement):
    """
    Bug corrigé : `profile.cursus` n'était jamais rempli (le frontend ne
    l'envoyait jamais, le champ restait optionnel) — `ApprenantCursusAPIView`
    exige pourtant `profile.cursus` non vide et correspondant à un vrai
    `Parcours.nom` pour lister le moindre cours : un nouvel apprenant ne
    voyait donc jamais aucun cours. `cursus` est désormais dérivé
    directement de l'objet `Parcours` réellement sélectionné (déjà
    obligatoire à l'inscription), garantissant la correspondance par
    construction. Voir docs/ecarts/p2_inscription_cursus_root_cause.md.
    """
    client = APIClient()
    response = client.post(
        reverse("register"),
        _payload_base(parcours=parcours.id, departement=departement.id, niveau="Terminale"),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    profile = User.objects.get(username="nouvel_apprenant").profile
    assert profile.cursus == parcours.nom
    assert Parcours.objects.get(nom=profile.cursus, type_parcours="cursus") == parcours


@pytest.mark.django_db
def test_inscription_publique_accepte_enseignant(parcours, departement):
    """« enseignant » reste autorisé sur l'inscription publique (contrairement
    aux rôles enseignant_admin/enseignant_cadre/enseignant_principal, réservés
    à apps/accounts/views/admin_enseignants.py)."""
    client = APIClient()
    response = client.post(
        reverse("register"),
        _payload_base(
            user_type="enseignant",
            parcours=parcours.id,
            departement=departement.id,
            niveau="Terminale",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["role"] == "enseignant"
