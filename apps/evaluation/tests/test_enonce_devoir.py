"""
Tests P2.3 : EnonceDevoir — un devoir peut avoir plusieurs énoncés, chacun
avec ses propres questions (CDC §7.2.1). Couvre la création automatique de
l'énoncé d'ordre 1, l'ajout d'énoncés supplémentaires, le verrouillage à la
publication (409), et la logique de migration de données (backfill depuis
l'ancien modèle enonce/enonces_supplementaires).
"""

import importlib
from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.evaluation.models import Devoir, EnonceDevoir, QuestionDevoir


@pytest.fixture
def cours_enseignant(cours, user_enseignant):
    cours.enseignant_principal = user_enseignant.profile
    cours.save(update_fields=["enseignant_principal"])
    return cours


@pytest.mark.django_db
def test_creation_devoir_alimente_enonce_ordre_1(client_enseignant, cours_enseignant):
    payload = {
        "titre": "Devoir Test",
        "enonce": "Voici l'énoncé principal.",
        "date_limite": (timezone.now() + timedelta(days=7)).isoformat(),
    }
    response = client_enseignant.post(
        reverse("devoir-creer", args=[cours_enseignant.id]), payload, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED

    devoir = Devoir.objects.get(pk=response.data["id"])
    enonces = list(devoir.enonces.all())
    assert len(enonces) == 1
    assert enonces[0].ordre == 1
    assert enonces[0].contenu == "Voici l'énoncé principal."


@pytest.mark.django_db
def test_ajouter_enonce_sur_devoir_non_publie_201(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
    )
    EnonceDevoir.objects.create(devoir=devoir, contenu="Énoncé 1", ordre=1)

    response = client_enseignant.post(
        reverse("devoir-enonce-ajouter", args=[devoir.id]),
        {"contenu": "Deuxième énoncé"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["ordre"] == 2
    assert devoir.enonces.count() == 2


@pytest.mark.django_db
def test_ajouter_enonce_sur_devoir_publie_409(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=True,
    )
    response = client_enseignant.post(
        reverse("devoir-enonce-ajouter", args=[devoir.id]),
        {"contenu": "Trop tard"},
        format="json",
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"]["code"] == "CONFLICT"


@pytest.mark.django_db
def test_migration_backfill_rattache_questions_et_eclate_enonces_supplementaires(cours):
    """
    Simule l'état AVANT P2.3 (enonce/enonces_supplementaires en JSON, pas
    d'EnonceDevoir, questions non rattachées) puis rejoue la logique de
    migration de données pour vérifier : 3 EnonceDevoir créés (ordres 1/2/3),
    toutes les QuestionDevoir existantes rattachées à l'ordre 1.
    """
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé principal",
        enonces_supplementaires=["Énoncé bonus A", "Énoncé bonus B"],
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours,
    )
    q1 = QuestionDevoir.objects.create(devoir=devoir, enonce="Q1", type_question="texte")
    q2 = QuestionDevoir.objects.create(devoir=devoir, enonce="Q2", type_question="texte")

    migration = importlib.import_module(
        "apps.evaluation.migrations.0003_alter_devoir_enonces_supplementaires_enoncedevoir_and_more"
    )
    migration.backfill_enoncedevoir(django_apps, None)

    enonces = list(devoir.enonces.order_by("ordre"))
    assert [e.ordre for e in enonces] == [1, 2, 3]
    assert enonces[0].contenu == "Énoncé principal"
    assert enonces[1].contenu == "Énoncé bonus A"
    assert enonces[2].contenu == "Énoncé bonus B"

    q1.refresh_from_db()
    q2.refresh_from_db()
    assert q1.enonce_devoir_id == enonces[0].id
    assert q2.enonce_devoir_id == enonces[0].id
