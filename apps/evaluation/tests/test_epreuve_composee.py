"""
Test P6.3 : le score d'une épreuve (Exercice avec est_epreuve=True) est
la SOMME des scores actuels des exercices composés
(`exercice.exercices_composes`) — jamais ses propres questions (souvent
vides pour un pur conteneur), jamais une moyenne.
"""

import pytest

from apps.evaluation.models import Exercice, ExerciceTentative, Question


@pytest.mark.django_db
def test_score_epreuve_est_la_somme_des_exercices_composes(client_apprenant, cours):
    exo1 = Exercice.objects.create(
        cours=cours, titre="Exo 1", enonce="E", etoiles=1, tentatives_max=1
    )
    q1 = Question.objects.create(
        exercice=exo1, text="Q1", type_question="texte", bonne_reponse="a", points=3.0
    )
    exo2 = Exercice.objects.create(
        cours=cours, titre="Exo 2", enonce="E", etoiles=1, tentatives_max=1
    )
    Question.objects.create(
        exercice=exo2, text="Q2", type_question="texte", bonne_reponse="b", points=5.0
    )

    # L'apprenant a déjà réussi exo1 (3/3) mais jamais touché exo2.
    client_apprenant.post(
        f"/api/exercices/{exo1.id}/evaluer/",
        {"reponses": {str(q1.id): "a"}},
        format="json",
    )

    # etoiles=1 : valeur sans rapport avec ce que ce test vérifie (la
    # composition du score), mais depuis P9.1 les étoiles pilotent aussi
    # l'accès Gratuit/Premium (AccesService) — un apprenant gratuit
    # (client_apprenant) ne doit pas être bloqué ici pour une raison hors
    # sujet du test.
    epreuve = Exercice.objects.create(
        cours=cours, titre="Épreuve", enonce="E", etoiles=1, tentatives_max=1, est_epreuve=True
    )
    epreuve.exercices_composes.set([exo1, exo2])

    reponse = client_apprenant.post(f"/api/exercices/{epreuve.id}/evaluer/", {}, format="json")

    assert reponse.status_code == 200
    assert reponse.data["score"] == 3.0  # exo1 réussi (3) + exo2 jamais tenté (0)
    assert reponse.data["total"] == 8.0  # 3 (exo1) + 5 (exo2) : total plein même non tenté

    tentative = ExerciceTentative.objects.get(exercice=epreuve)
    assert "exercices" in tentative.reponses
    composants = {d["exercice_id"]: d for d in tentative.reponses["exercices"]}
    assert composants[exo1.id]["score"] == 3.0
    assert composants[exo1.id]["total"] == 3.0
    assert composants[exo2.id]["score"] == 0.0
    assert composants[exo2.id]["total"] == 5.0
