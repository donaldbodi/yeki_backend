"""
Tests P6.1 : abandon des moyennes.

- La note officielle d'un exercice (`EvaluationExercice`) doit être les
  points de la DERNIÈRE tentative — jamais une moyenne, jamais un maximum.
- Le score de classement à travers plusieurs exercices est la SOMME BRUTE
  des points — pas de moyenne, pas de pondération (décision actée avec
  l'utilisateur).
"""

import pytest

from apps.evaluation.models import EvaluationExercice, Exercice, ExerciceTentative
from apps.evaluation.services import ClassementService


def _creer_tentative(apprenant, exercice, numero, score, total_points=10.0):
    return ExerciceTentative.objects.create(
        apprenant=apprenant,
        exercice=exercice,
        tentative_numero=numero,
        score=score,
        total_points=total_points,
        est_soumise=True,
        est_terminee=True,
    )


@pytest.mark.django_db
def test_note_officielle_est_la_derniere_tentative_pas_une_moyenne_ni_un_maximum(
    user_apprenant, cours
):
    exercice = Exercice.objects.create(
        cours=cours, titre="Ex", enonce="E", etoiles=1, tentatives_max=3
    )

    # 3 tentatives de scores différents : 5, 8, 3 — moyenne = 5.33, max = 8.
    for numero, score in enumerate([5.0, 8.0, 3.0], start=1):
        tentative = _creer_tentative(user_apprenant, exercice, numero, score)
        ClassementService.enregistrer_evaluation_finale(user_apprenant, exercice, tentative)

    evaluation = EvaluationExercice.objects.get(user=user_apprenant, exercice=exercice)
    assert evaluation.score == 3.0  # dernière tentative, ni 5.33 (moyenne) ni 8 (max)
    assert evaluation.total == 10.0


@pytest.mark.django_db
def test_score_departement_est_une_somme_pas_une_moyenne(user_apprenant, departement, cours):
    # Même étoile (1★) pour les deux exercices : la pondération par étoile
    # (P6.3) ne doit pas fausser cette assertion sur somme-vs-moyenne, qui
    # ne concerne QUE l'agrégation entre plusieurs exercices (P6.1).
    exercice1 = Exercice.objects.create(
        cours=cours, titre="Ex1", enonce="E", etoiles=1, tentatives_max=1
    )
    exercice2 = Exercice.objects.create(
        cours=cours, titre="Ex2", enonce="E", etoiles=1, tentatives_max=1
    )

    for exercice, score in [(exercice1, 6.0), (exercice2, 9.0)]:
        tentative = _creer_tentative(user_apprenant, exercice, 1, score)
        ClassementService.enregistrer_evaluation_finale(user_apprenant, exercice, tentative)

    score = ClassementService.score_departement(user_apprenant, departement)
    assert score == 15.0  # 6 + 9, pas (6+9)/2 = 7.5


@pytest.mark.django_db
def test_calculer_classement_departement_ordonne_par_score_decroissant(departement, cours):
    from django.contrib.auth.models import User
    from apps.accounts.models import Profile

    exercice = Exercice.objects.create(
        cours=cours, titre="Ex", enonce="E", etoiles=1, tentatives_max=1
    )

    alice = User.objects.create_user(username="alice_test", password="Test1234!")
    Profile.objects.create(user=alice, user_type="apprenant", departement=departement, is_active=True)
    bob = User.objects.create_user(username="bob_test", password="Test1234!")
    Profile.objects.create(user=bob, user_type="apprenant", departement=departement, is_active=True)

    for apprenant, score in [(alice, 4.0), (bob, 12.0)]:
        tentative = _creer_tentative(apprenant, exercice, 1, score)
        ClassementService.enregistrer_evaluation_finale(apprenant, exercice, tentative)

    classement = ClassementService.calculer_classement_departement(departement)

    assert [c["apprenant_id"] for c in classement] == [bob.id, alice.id]
    assert classement[0]["rang"] == 1
    assert classement[0]["score"] == 12.0
    # P11.8 : `nom`/`username` étaient absents de la réponse alors que le
    # frontend les lisait déjà — noms systématiquement vides à l'affichage.
    assert classement[0]["username"] == "bob_test"
    assert classement[1]["username"] == "alice_test"
    assert classement[1]["rang"] == 2


@pytest.mark.django_db
def test_mettre_a_jour_rangs_departement_persiste_dans_rangapprenant(
    user_apprenant, departement, cours
):
    from apps.evaluation.models import RangApprenant, ScoreDetail

    exercice = Exercice.objects.create(
        cours=cours, titre="Ex", enonce="E", etoiles=1, tentatives_max=1
    )
    tentative = _creer_tentative(user_apprenant, exercice, 1, 7.0)
    ClassementService.enregistrer_evaluation_finale(user_apprenant, exercice, tentative)

    count = ClassementService.mettre_a_jour_rangs_departement(departement)

    assert count == 1
    rang = RangApprenant.objects.get(apprenant=user_apprenant, departement=departement)
    assert rang.score == 7.0
    assert rang.rang == 1
    detail = ScoreDetail.objects.get(rang_apprenant=rang, categorie="exercices")
    assert detail.score == 7.0
