"""
Tests P7.4 : petits ajouts backend indispensables à l'écran de gestion
enseignant des devoirs — `enonce_devoir` exposé par
`QuestionDevoirAdminSerializer`, garde de permission sur
`ListeQuestionsDevoirView` (fuite des bonnes réponses corrigée), et
`coefficient`/`fichier_correction_url` dans `DevoirsCoursView`.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.evaluation.models import Devoir, EnonceDevoir, QuestionDevoir


@pytest.fixture
def cours_enseignant(cours, user_enseignant):
    cours.enseignant_principal = user_enseignant.profile
    cours.save(update_fields=["enseignant_principal"])
    return cours


def _devoir_avec_question(cours_enseignant, **kwargs):
    defaults = dict(
        titre="D",
        enonce="Énoncé",
        date_debut=timezone.now() - timedelta(days=1),
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=True,
        coefficient=2.0,
    )
    defaults.update(kwargs)
    devoir = Devoir.objects.create(**defaults)
    enonce_devoir = EnonceDevoir.objects.create(devoir=devoir, contenu=devoir.enonce, ordre=1)
    question = QuestionDevoir.objects.create(
        devoir=devoir,
        enonce_devoir=enonce_devoir,
        enonce="Q1",
        type_question="texte",
        reponse_attendue="x",
        ordre=1,
    )
    return devoir, enonce_devoir, question


@pytest.mark.django_db
def test_liste_questions_devoir_expose_enonce_devoir(client_enseignant, cours_enseignant):
    devoir, enonce_devoir, question = _devoir_avec_question(cours_enseignant)

    response = client_enseignant.get(reverse("devoir-questions-liste", args=[devoir.id]))

    assert response.status_code == status.HTTP_200_OK
    resultat = response.data["results"][0]
    assert resultat["enonce_devoir"] == enonce_devoir.id


@pytest.mark.django_db
def test_liste_questions_devoir_refuse_apprenant_403(client_apprenant, cours_enseignant):
    """Corrige la fuite des bonnes réponses : cette vue renvoie
    `est_correct`/`reponse_attendue`, réservée à l'enseignant qui gère
    le devoir."""
    devoir, _, _ = _devoir_avec_question(cours_enseignant)

    response = client_apprenant.get(reverse("devoir-questions-liste", args=[devoir.id]))

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_liste_questions_devoir_refuse_enseignant_tiers_403(
    django_user_model, cours_enseignant
):
    from apps.accounts.models import Profile

    devoir, _, _ = _devoir_avec_question(cours_enseignant)

    tiers = django_user_model.objects.create_user(
        username="tiers_devoir", email="tiers_devoir@yeki.test", password="Test1234!"
    )
    Profile.objects.create(user=tiers, user_type="enseignant_principal", is_active=True)

    from rest_framework.authtoken.models import Token
    from rest_framework.test import APIClient

    token, _ = Token.objects.get_or_create(user=tiers)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    response = client.get(reverse("devoir-questions-liste", args=[devoir.id]))
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_devoirs_cours_expose_coefficient_et_fichier_correction(
    client_enseignant, cours_enseignant
):
    devoir, _, _ = _devoir_avec_question(cours_enseignant, coefficient=1.5)

    response = client_enseignant.get(reverse("devoirs-cours", args=[cours_enseignant.id]))

    assert response.status_code == status.HTTP_200_OK
    resultat = next(r for r in response.data["results"] if r["id"] == devoir.id)
    assert resultat["coefficient"] == 1.5
    assert resultat["fichier_correction_url"] is None
