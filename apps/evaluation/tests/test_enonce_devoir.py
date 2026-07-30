"""
Tests P2.3/P7.1 : EnonceDevoir — un devoir peut avoir plusieurs énoncés,
chacun avec ses propres questions (CDC §7.2.1/§7.2.2). Couvre la création
automatique de l'énoncé d'ordre 1, le CRUD complet des énoncés
(GET/POST liste, PATCH/DELETE détail), l'ajout de questions rattachées à
un énoncé précis, le verrouillage à la publication (409 partout), et la
logique de migration de données (backfill depuis l'ancien modèle
enonce/enonces_supplementaires).
"""

import importlib
from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.evaluation.models import ChoixReponse, Devoir, EnonceDevoir, QuestionDevoir


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
        reverse("devoir-enonces", args=[devoir.id]),
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
        reverse("devoir-enonces", args=[devoir.id]),
        {"contenu": "Trop tard"},
        format="json",
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"]["code"] == "CONFLICT"


@pytest.mark.django_db
def test_lister_enonces_devoir_ordonnes_avec_questions_imbriquees(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
    )
    e2 = EnonceDevoir.objects.create(devoir=devoir, contenu="Énoncé 2", ordre=2)
    e1 = EnonceDevoir.objects.create(devoir=devoir, contenu="Énoncé 1", ordre=1)
    QuestionDevoir.objects.create(
        devoir=devoir, enonce_devoir=e1, enonce="Q2", type_question="texte", ordre=2
    )
    QuestionDevoir.objects.create(
        devoir=devoir, enonce_devoir=e1, enonce="Q1", type_question="texte", ordre=1
    )

    response = client_enseignant.get(reverse("devoir-enonces", args=[devoir.id]))
    assert response.status_code == status.HTTP_200_OK
    # Ordonné par `ordre` malgré un ordre de création inverse.
    assert [e["ordre"] for e in response.data] == [1, 2]
    assert [q["enonce"] for q in response.data[0]["questions"]] == ["Q1", "Q2"]


@pytest.mark.django_db
def test_modifier_enonce_devoir_200(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
    )
    enonce = EnonceDevoir.objects.create(devoir=devoir, contenu="Ancien contenu", ordre=1)

    response = client_enseignant.patch(
        reverse("devoir-enonce-detail", args=[enonce.id]),
        {"contenu": "Nouveau contenu"},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    enonce.refresh_from_db()
    assert enonce.contenu == "Nouveau contenu"


@pytest.mark.django_db
def test_modifier_enonce_devoir_publie_409(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=True,
    )
    enonce = EnonceDevoir.objects.create(devoir=devoir, contenu="Contenu", ordre=1)

    response = client_enseignant.patch(
        reverse("devoir-enonce-detail", args=[enonce.id]),
        {"contenu": "Trop tard"},
        format="json",
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"]["code"] == "CONFLICT"


@pytest.mark.django_db
def test_supprimer_enonce_devoir_renumerote_les_restants(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
    )
    e1 = EnonceDevoir.objects.create(devoir=devoir, contenu="E1", ordre=1)
    e2 = EnonceDevoir.objects.create(devoir=devoir, contenu="E2", ordre=2)
    e3 = EnonceDevoir.objects.create(devoir=devoir, contenu="E3", ordre=3)

    response = client_enseignant.delete(reverse("devoir-enonce-detail", args=[e2.id]))
    assert response.status_code == status.HTTP_204_NO_CONTENT

    restants = list(devoir.enonces.order_by("ordre"))
    assert [e.id for e in restants] == [e1.id, e3.id]
    assert [e.ordre for e in restants] == [1, 2]  # e3 renuméroté de 3 → 2

    # Une nouvelle création derrière ne doit pas violer unique_together.
    response = client_enseignant.post(
        reverse("devoir-enonces", args=[devoir.id]), {"contenu": "E4"}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["ordre"] == 3


@pytest.mark.django_db
def test_supprimer_enonce_devoir_publie_409(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=True,
    )
    e1 = EnonceDevoir.objects.create(devoir=devoir, contenu="E1", ordre=1)
    e2 = EnonceDevoir.objects.create(devoir=devoir, contenu="E2", ordre=2)

    response = client_enseignant.delete(reverse("devoir-enonce-detail", args=[e2.id]))
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"]["code"] == "CONFLICT"


@pytest.mark.django_db
def test_supprimer_dernier_enonce_409(client_enseignant, cours_enseignant):
    """Décision actée : un devoir doit toujours conserver au moins un énoncé."""
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
    )
    unique = EnonceDevoir.objects.create(devoir=devoir, contenu="Seul énoncé", ordre=1)

    response = client_enseignant.delete(reverse("devoir-enonce-detail", args=[unique.id]))
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"]["code"] == "CONFLICT"
    assert devoir.enonces.count() == 1


@pytest.mark.django_db
def test_ajouter_question_a_un_enonce_rattache_enonce_devoir(client_enseignant, cours_enseignant):
    """Corrige le bug dénoncé : l'ancien endpoint ne rattachait JAMAIS
    `enonce_devoir` (question orpheline malgré le modèle le permettant)."""
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
    )
    enonce = EnonceDevoir.objects.create(devoir=devoir, contenu="E1", ordre=1)

    response = client_enseignant.post(
        reverse("devoir-enonce-question-ajouter", args=[enonce.id]),
        {"enonce": "2 + 2 ?", "type_question": "texte", "reponse_attendue": "4"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED

    question = QuestionDevoir.objects.get(pk=response.data["id"])
    assert question.enonce_devoir_id == enonce.id
    assert question.devoir_id == devoir.id


@pytest.mark.django_db
def test_ajouter_question_a_un_enonce_devoir_publie_409(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=True,
    )
    enonce = EnonceDevoir.objects.create(devoir=devoir, contenu="E1", ordre=1)

    response = client_enseignant.post(
        reverse("devoir-enonce-question-ajouter", args=[enonce.id]),
        {"enonce": "Trop tard ?", "type_question": "texte", "reponse_attendue": "x"},
        format="json",
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"]["code"] == "CONFLICT"


@pytest.mark.django_db
def test_ajouter_qcm_a_un_enonce_devoir_ordre_choix_assigne(client_enseignant, cours_enseignant):
    """P7.1 : `ChoixReponse.ordre` doit refléter l'ordre d'envoi (avant
    cette correction, tous les choix retombaient sur le défaut `ordre=1`,
    ordre non déterministe)."""
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
    )
    enonce = EnonceDevoir.objects.create(devoir=devoir, contenu="E1", ordre=1)

    response = client_enseignant.post(
        reverse("devoir-enonce-question-ajouter", args=[enonce.id]),
        {
            "enonce": "Capitale du Cameroun ?",
            "type_question": "qcm",
            "choix": [
                {"texte": "Douala", "est_correct": False},
                {"texte": "Yaoundé", "est_correct": True},
                {"texte": "Garoua", "est_correct": False},
            ],
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED

    question = QuestionDevoir.objects.get(pk=response.data["id"])
    choix = list(ChoixReponse.objects.filter(question=question).order_by("ordre"))
    assert [c.ordre for c in choix] == [1, 2, 3]
    assert [c.texte for c in choix] == ["Douala", "Yaoundé", "Garoua"]
    assert choix[1].est_correct is True


@pytest.mark.django_db
def test_ajouter_qcm_a_un_enonce_devoir_sans_choix_correct_400(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
    )
    enonce = EnonceDevoir.objects.create(devoir=devoir, contenu="E1", ordre=1)

    response = client_enseignant.post(
        reverse("devoir-enonce-question-ajouter", args=[enonce.id]),
        {
            "enonce": "2 + 2 ?",
            "type_question": "qcm",
            "choix": [
                {"texte": "3", "est_correct": False},
                {"texte": "4", "est_correct": False},
            ],
        },
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "choix" in response.data["error"]["fields"]


@pytest.mark.django_db
def test_ajouter_qcm_a_un_enonce_devoir_deux_choix_corrects_400(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé 1",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
    )
    enonce = EnonceDevoir.objects.create(devoir=devoir, contenu="E1", ordre=1)

    response = client_enseignant.post(
        reverse("devoir-enonce-question-ajouter", args=[enonce.id]),
        {
            "enonce": "2 + 2 ?",
            "type_question": "qcm",
            "choix": [
                {"texte": "3", "est_correct": True},
                {"texte": "4", "est_correct": True},
            ],
        },
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "choix" in response.data["error"]["fields"]


@pytest.mark.django_db
def test_devoir_detail_renvoie_enonces_ordonnes_avec_questions_imbriquees(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé principal",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
    )
    e1 = EnonceDevoir.objects.create(devoir=devoir, contenu="Énoncé principal", ordre=1)
    e2 = EnonceDevoir.objects.create(devoir=devoir, contenu="Énoncé bonus", ordre=2)
    QuestionDevoir.objects.create(
        devoir=devoir, enonce_devoir=e2, enonce="Q bonus", type_question="texte", ordre=1
    )
    QuestionDevoir.objects.create(
        devoir=devoir, enonce_devoir=e1, enonce="Q principale", type_question="texte", ordre=1
    )

    # `DetailDevoirView` n'expose que les devoirs publiés (`est_publie=True`)
    # — on publie directement via le modèle ici, le test porte sur le
    # sérialiseur (ordre + imbrication), pas sur le flux de publication
    # (hors périmètre de P7.1, voir Contexte du plan).
    devoir.est_publie = True
    devoir.save(update_fields=["est_publie"])

    response = client_enseignant.get(reverse("detail-devoir", args=[devoir.id]))
    assert response.status_code == status.HTTP_200_OK
    assert [e["ordre"] for e in response.data["enonces"]] == [1, 2]
    assert response.data["enonces"][0]["questions"][0]["enonce"] == "Q principale"
    assert response.data["enonces"][1]["questions"][0]["enonce"] == "Q bonus"


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
