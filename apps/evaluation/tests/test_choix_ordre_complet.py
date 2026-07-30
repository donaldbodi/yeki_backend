"""
Test P6.3 : la liste des choix d'un QCM revient COMPLÈTE (id + texte +
est_correct, pas juste le texte) et ORDONNÉE (Choix.ordre), pour la page
d'ajout d'exercices — et l'ajout d'une question assigne bien un ordre
séquentiel à chaque choix reçu.
"""

import pytest
from django.urls import reverse

from apps.evaluation.models import Choix, Question


@pytest.mark.django_db
def test_choix_qcm_complets_et_ordonnes_a_la_lecture(client_apprenant, exercice):
    question = Question.objects.create(
        exercice=exercice, text="Capitale ?", type_question="qcm", bonne_reponse="paris", points=1
    )
    Choix.objects.create(question=question, texte="Londres", est_correct=False, ordre=2)
    Choix.objects.create(question=question, texte="Paris", est_correct=True, ordre=1)

    reponse = client_apprenant.get(reverse("question-liste", kwargs={"exercice_id": exercice.id}))

    assert reponse.status_code == 200
    (q_data,) = reponse.data["results"]
    assert [c["texte"] for c in q_data["choix"]] == ["Paris", "Londres"]
    assert q_data["choix"][0]["est_correct"] is True
    assert q_data["choix"][1]["est_correct"] is False
    assert all("id" in c for c in q_data["choix"])


@pytest.mark.django_db
def test_ajout_qcm_assigne_ordre_sequentiel(client_enseignant, user_enseignant, cours):
    cours.enseignant_principal = user_enseignant.profile
    cours.save(update_fields=["enseignant_principal"])
    from apps.evaluation.models import Exercice

    exercice = Exercice.objects.create(cours=cours, titre="Ex", enonce="E", etoiles=1)

    reponse = client_enseignant.post(
        reverse("question-ajouter", kwargs={"exercice_id": exercice.id}),
        {
            "text": "2 + 2 = ?",
            "type_question": "qcm",
            "points": 1,
            "choix": [
                {"texte": "3", "est_correct": False},
                {"texte": "4", "est_correct": True},
            ],
        },
        format="json",
    )

    assert reponse.status_code == 201
    question_id = reponse.data["id"]
    choix = list(Choix.objects.filter(question_id=question_id).order_by("ordre"))
    assert [c.texte for c in choix] == ["3", "4"]
    assert [c.ordre for c in choix] == [1, 2]
