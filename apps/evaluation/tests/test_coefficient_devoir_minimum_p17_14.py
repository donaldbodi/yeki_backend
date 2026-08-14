"""
Tests P17.14 : le coefficient d'un devoir ne doit jamais être inférieur
à la valeur (poids) d'un exercice 3 étoiles — `ParametreClassement`
(source `etoile_3`), jamais une constante en dur (règle 3).
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.evaluation.models import Devoir, ParametreClassement


@pytest.fixture
def cours_enseignant(cours, user_enseignant):
    cours.enseignant_principal = user_enseignant.profile
    cours.save(update_fields=["enseignant_principal"])
    return cours


def _payload(cours_enseignant, coefficient):
    return {
        "titre": "Devoir P17.14",
        "description": "",
        "type_devoir": "cursus",
        "enonce": "Énoncé du devoir",
        "date_debut": timezone.now().isoformat(),
        "date_limite": (timezone.now() + timedelta(days=7)).isoformat(),
        "duree_minutes": 30,
        "note_sur": 20,
        "coefficient": coefficient,
        "tentatives_max": 1,
        "cours_lie": cours_enseignant.id,
        "type_correction": "auto",
    }


@pytest.mark.django_db
def test_creer_devoir_coefficient_sous_le_plancher_refuse(client_enseignant, cours_enseignant):
    ParametreClassement.objects.update_or_create(source="etoile_3", defaults={"poids": 4.0})

    response = client_enseignant.post(
        reverse("devoir-creer", args=[cours_enseignant.id]),
        data=_payload(cours_enseignant, coefficient=1.0),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "coefficient" in response.data["error"]["fields"]


@pytest.mark.django_db
def test_creer_devoir_coefficient_au_dessus_du_plancher_reussit(client_enseignant, cours_enseignant):
    ParametreClassement.objects.update_or_create(source="etoile_3", defaults={"poids": 4.0})

    response = client_enseignant.post(
        reverse("devoir-creer", args=[cours_enseignant.id]),
        data=_payload(cours_enseignant, coefficient=4.0),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert Devoir.objects.get(id=response.data["id"]).coefficient == 4.0


@pytest.mark.django_db
def test_creer_devoir_coefficient_sans_parametre_configure_replie_sur_0_1(
    client_enseignant, cours_enseignant
):
    ParametreClassement.objects.filter(source="etoile_3").delete()

    response = client_enseignant.post(
        reverse("devoir-creer", args=[cours_enseignant.id]),
        data=_payload(cours_enseignant, coefficient=0.5),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_modifier_devoir_coefficient_sous_le_plancher_refuse(client_enseignant, cours_enseignant):
    ParametreClassement.objects.update_or_create(source="etoile_3", defaults={"poids": 4.0})
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé",
        date_debut=timezone.now() - timedelta(days=1),
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
        coefficient=4.0,
    )

    response = client_enseignant.patch(
        reverse("devoir-modifier", args=[devoir.id]),
        data={"coefficient": 2.0},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "coefficient" in response.data["error"]["fields"]
