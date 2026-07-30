"""
Tests P2.2 : Question.points / QuestionDevoir.points doivent être un
multiple de 0.25, au moins 0.25.

P6.3 : le validateur de modèle n'était jamais invoqué via l'API (aucun
`full_clean()` dans les vues) — les tests ci-dessous prouvent qu'un
POST avec des points invalides est désormais bien rejeté (400), pas
seulement `Question.full_clean()` appelé directement.
"""

from django.urls import reverse

import pytest
from django.core.exceptions import ValidationError

from apps.evaluation.models import Devoir, Exercice, Question, QuestionDevoir
from apps.evaluation.validators import valider_pas_de_0_25


@pytest.mark.parametrize("valeur", [0.25, 0.5, 1, 1.75, 20])
def test_valeurs_valides_ne_levent_pas(valeur):
    valider_pas_de_0_25(valeur)  # ne doit pas lever


@pytest.mark.parametrize("valeur", [0.1, 0.3, 1.4, 0.2])
def test_valeurs_invalides_levent(valeur):
    with pytest.raises(ValidationError):
        valider_pas_de_0_25(valeur)


@pytest.mark.django_db
def test_question_points_pas_invalide_leve_en_full_clean(exercice):
    question = Question(
        exercice=exercice,
        text="Q",
        type_question="texte",
        bonne_reponse="R",
        points=0.3,
    )
    with pytest.raises(ValidationError) as exc:
        question.full_clean()
    assert "points" in exc.value.message_dict


@pytest.mark.django_db
def test_question_points_en_dessous_du_minimum_leve(exercice):
    question = Question(
        exercice=exercice,
        text="Q",
        type_question="texte",
        bonne_reponse="R",
        points=0.1,
    )
    with pytest.raises(ValidationError) as exc:
        question.full_clean()
    assert "points" in exc.value.message_dict


@pytest.mark.django_db
def test_questiondevoir_points_pas_invalide_leve(cours):
    from django.utils import timezone
    from datetime import timedelta

    devoir = Devoir.objects.create(
        titre="D", enonce="E", date_limite=timezone.now() + timedelta(days=1)
    )
    question = QuestionDevoir(devoir=devoir, enonce="Q", type_question="texte", points=0.6)
    with pytest.raises(ValidationError) as exc:
        question.full_clean()
    assert "points" in exc.value.message_dict


@pytest.mark.django_db
def test_ajout_question_points_invalides_rejete_via_api(client_enseignant, user_enseignant, cours):
    cours.enseignant_principal = user_enseignant.profile
    cours.save(update_fields=["enseignant_principal"])
    exercice = Exercice.objects.create(cours=cours, titre="Ex", enonce="E", etoiles=1)

    reponse = client_enseignant.post(
        reverse("question-ajouter", kwargs={"exercice_id": exercice.id}),
        {"text": "Q", "type_question": "texte", "bonne_reponse": "R", "points": 0.3},
        format="json",
    )

    assert reponse.status_code == 400
    assert "points" in reponse.data["error"]["fields"]
