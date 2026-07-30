"""
Tests P6.2 : chaque tentative d'exercice doit porter un snapshot
auto-suffisant (réponses ET corrections figées au moment de la tentative)
— pas une re-dérivation live contre l'état actuel de Question/Choix.
"""

import importlib

import pytest
from django.apps import apps as django_apps
from django.urls import reverse

from apps.evaluation.models import Choix, EvaluationExercice, Exercice, ExerciceTentative, Question


def _creer_exercice_qcm(cours, tentatives_max=1):
    exercice = Exercice.objects.create(
        cours=cours, titre="Ex QCM", enonce="E", etoiles=1, tentatives_max=tentatives_max
    )
    question = Question.objects.create(
        exercice=exercice,
        text="2 + 2 = ?",
        type_question="qcm",
        bonne_reponse="4",
        points=2.0,
        explication="L'addition de 2 et 2 donne 4.",
    )
    Choix.objects.create(question=question, texte="3", est_correct=False)
    Choix.objects.create(question=question, texte="4", est_correct=True)
    return exercice, question


@pytest.mark.django_db
def test_snapshot_complet_stocke_a_la_soumission(client_apprenant, cours):
    exercice, question = _creer_exercice_qcm(cours)

    reponse = client_apprenant.post(
        f"/api/exercices/{exercice.id}/evaluer/",
        {"reponses": {str(question.id): "4"}},
        format="json",
    )
    assert reponse.status_code == 200

    tentative = ExerciceTentative.objects.get(exercice=exercice)
    snapshot = tentative.reponses
    assert snapshot["score"] == 2.0
    assert snapshot["total"] == 2.0
    assert snapshot["date"] is not None

    (detail,) = snapshot["questions"]
    assert detail["question_id"] == question.id
    assert detail["enonce_snapshot"] == "2 + 2 = ?"
    assert detail["type"] == "qcm"
    assert {"3", "4"} == {c["texte"] for c in detail["choix_snapshot"]}
    assert detail["reponse_apprenant"] == "4"
    assert detail["bonne_reponse"] == "4"
    assert detail["est_correct"] is True
    assert detail["points_obtenus"] == 2.0
    assert detail["points_max"] == 2.0
    assert detail["explication"] == "L'addition de 2 et 2 donne 4."


@pytest.mark.django_db
def test_modifier_question_apres_tentative_ne_change_pas_lhistorique(client_apprenant, cours):
    exercice, question = _creer_exercice_qcm(cours)

    client_apprenant.post(
        f"/api/exercices/{exercice.id}/evaluer/",
        {"reponses": {str(question.id): "4"}},
        format="json",
    )

    # L'enseignant modifie la question APRÈS la tentative : nouvel énoncé,
    # le choix "4" (jusque-là correct) devient incorrect.
    question.text = "Nouvel énoncé (modifié après coup)"
    question.save(update_fields=["text"])
    Choix.objects.filter(question=question, texte="4").update(est_correct=False)
    Choix.objects.filter(question=question, texte="3").update(est_correct=True)

    reponse = client_apprenant.get(reverse("resultat-exercice", kwargs={"exercice_id": exercice.id}))
    assert reponse.status_code == 200
    (detail,) = reponse.data["detail"]
    # Le snapshot reste celui d'AVANT la modification.
    assert detail["question"] == "2 + 2 = ?"
    assert detail["correct"] is True

    reponse_hist = client_apprenant.get(
        reverse("historique-tentatives-exercice", kwargs={"exercice_id": exercice.id})
    )
    assert reponse_hist.status_code == 200
    (tentative_hist,) = reponse_hist.data["results"]
    (detail_hist,) = tentative_hist["reponses"]
    assert detail_hist["question"] == "2 + 2 = ?"
    assert detail_hist["est_correct"] is True


@pytest.mark.django_db
def test_question_supprimee_reste_visible_dans_historique(client_apprenant, cours):
    exercice, question = _creer_exercice_qcm(cours)

    client_apprenant.post(
        f"/api/exercices/{exercice.id}/evaluer/",
        {"reponses": {str(question.id): "4"}},
        format="json",
    )

    question.delete()

    reponse = client_apprenant.get(
        reverse("historique-tentatives-exercice", kwargs={"exercice_id": exercice.id})
    )
    assert reponse.status_code == 200
    (tentative_hist,) = reponse.data["results"]
    assert len(tentative_hist["reponses"]) == 1  # ne disparaît plus silencieusement
    assert tentative_hist["reponses"][0]["question"] == "2 + 2 = ?"


@pytest.mark.django_db
def test_soumettre_une_fois_epuise_est_accepte_sans_effet(client_apprenant, cours):
    exercice, question = _creer_exercice_qcm(cours, tentatives_max=1)

    client_apprenant.post(
        f"/api/exercices/{exercice.id}/evaluer/",
        {"reponses": {str(question.id): "4"}},
        format="json",
    )
    evaluation_avant = EvaluationExercice.objects.get(exercice=exercice)

    reponse = client_apprenant.post(
        f"/api/exercices/{exercice.id}/evaluer/",
        {"reponses": {str(question.id): "3"}},  # tenterait de changer la note
        format="json",
    )

    assert reponse.status_code == 200
    assert reponse.data["tentatives_epuisees"] is True
    assert ExerciceTentative.objects.filter(exercice=exercice).count() == 1  # aucune nouvelle
    evaluation_apres = EvaluationExercice.objects.get(exercice=exercice)
    assert evaluation_apres.score == evaluation_avant.score  # note inchangée


@pytest.mark.django_db
def test_migration_backfill_reconstruit_snapshot_exploitable(cours, user_apprenant):
    exercice, question = _creer_exercice_qcm(cours)

    # Simule une tentative créée AVANT P6.2 : format brut, pas de snapshot.
    tentative = ExerciceTentative.objects.create(
        apprenant=user_apprenant,
        exercice=exercice,
        tentative_numero=1,
        reponses={str(question.id): "4"},
        score=2.0,
        total_points=2.0,
        est_soumise=True,
        est_terminee=True,
    )

    migration = importlib.import_module(
        "apps.evaluation.migrations.0008_backfill_snapshots_tentatives"
    )
    migration.backfill_snapshots(django_apps, None)

    tentative.refresh_from_db()
    assert "questions" in tentative.reponses
    (detail,) = tentative.reponses["questions"]
    assert detail["question_id"] == question.id
    assert detail["est_correct"] is True
    assert detail["points_obtenus"] == 2.0
