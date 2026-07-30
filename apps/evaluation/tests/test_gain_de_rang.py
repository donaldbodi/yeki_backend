"""
Test P6.3 : après une soumission qui améliore le rang de l'apprenant, la
réponse contient {"rang_gagne": true, "ancien_rang", "nouveau_rang"} et
une notification type="classement" est créée.
"""

import pytest
from django.contrib.auth.models import User

from apps.accounts.models import Profile
from apps.evaluation.models import EvaluationExercice, Exercice, Question, RangApprenant
from apps.evaluation.services import ClassementService
from apps.notifications.models import Notification


@pytest.mark.django_db
def test_gain_de_rang_signale_dans_la_reponse_et_notifie(
    client_apprenant, user_apprenant, departement, cours
):
    autre = User.objects.create_user(username="autre_test", password="Test1234!")
    Profile.objects.create(user=autre, user_type="apprenant", departement=departement, is_active=True)

    exo_a = Exercice.objects.create(
        cours=cours, titre="A", enonce="E", etoiles=1, tentatives_max=1
    )
    exo_b = Exercice.objects.create(
        cours=cours, titre="B", enonce="E", etoiles=1, tentatives_max=1
    )
    question_b = Question.objects.create(
        exercice=exo_b, text="Q", type_question="texte", bonne_reponse="a", points=10.0
    )

    # "autre" est mieux classé que user_apprenant, avant la soumission qui suit.
    EvaluationExercice.objects.create(user=autre, exercice=exo_a, score=5.0, total=5.0)
    EvaluationExercice.objects.create(user=user_apprenant, exercice=exo_a, score=0.0, total=5.0)
    ClassementService.mettre_a_jour_rangs_departement(departement)

    rang_avant = RangApprenant.objects.get(apprenant=user_apprenant, departement=departement)
    assert rang_avant.rang == 2

    reponse = client_apprenant.post(
        f"/api/exercices/{exo_b.id}/evaluer/",
        {"reponses": {str(question_b.id): "a"}},
        format="json",
    )

    assert reponse.status_code == 200
    assert reponse.data["rang_gagne"] is True
    assert reponse.data["ancien_rang"] == 2
    assert reponse.data["nouveau_rang"] == 1

    notif = Notification.objects.filter(utilisateur=user_apprenant, type="classement").first()
    assert notif is not None


@pytest.mark.django_db
def test_pas_de_rang_gagne_signale_si_le_rang_ne_change_pas(client_apprenant, user_apprenant, cours):
    exo = Exercice.objects.create(cours=cours, titre="Ex", enonce="E", etoiles=1, tentatives_max=1)
    question = Question.objects.create(
        exercice=exo, text="Q", type_question="texte", bonne_reponse="a", points=5.0
    )

    reponse = client_apprenant.post(
        f"/api/exercices/{exo.id}/evaluer/",
        {"reponses": {str(question.id): "a"}},
        format="json",
    )

    assert reponse.status_code == 200
    assert "rang_gagne" not in reponse.data  # 1er calcul : pas d'ancien rang à comparer
