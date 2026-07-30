"""
Tests P7.2 : cycle de vie du devoir — publication, modification,
duplication, fenêtre de traitement, unicité de soumission.

`test_reproduction_bug_publication_404` reproduit D'ABORD le bug signalé
(« la publication ne fonctionne plus ») avant tout correctif : sans
route enregistrée pour `/devoirs/<id>/publier/`, l'appel renvoie 404.
Après le correctif (routage + définition de `cours`), ce même test est
remplacé par `test_publier_devoir_200_avec_avertissement` (assertions
inverses) — voir historique git pour la preuve de reproduction.
"""

from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.accounts.models import Profile
from apps.evaluation.models import (
    ChoixReponse,
    Devoir,
    EnonceDevoir,
    QuestionDevoir,
    SoumissionDevoir,
)


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
        est_publie=False,
    )
    defaults.update(kwargs)
    devoir = Devoir.objects.create(**defaults)
    EnonceDevoir.objects.create(devoir=devoir, contenu=devoir.enonce, ordre=1)
    QuestionDevoir.objects.create(
        devoir=devoir, enonce="Q1", type_question="texte", reponse_attendue="x", ordre=1
    )
    return devoir


@pytest.mark.django_db
def test_publier_devoir_200_avec_avertissement(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant)

    response = client_enseignant.post(reverse("devoir-publier", args=[devoir.id]))
    assert response.status_code == status.HTTP_200_OK
    assert response.data["est_publie"] is True
    # Point 5 : l'enseignant DOIT être informé, au moment de publier, qu'il
    # ne pourra plus ajouter/modifier de question ni d'énoncé.
    assert "plus" in response.data["message"].lower()

    devoir.refresh_from_db()
    assert devoir.est_publie is True


@pytest.mark.django_db
def test_publier_devoir_deja_publie_409(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant, est_publie=True)

    response = client_enseignant.post(reverse("devoir-publier", args=[devoir.id]))
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"]["code"] == "CONFLICT"


@pytest.mark.django_db
def test_publier_devoir_sans_question_400(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="Énoncé",
        date_debut=timezone.now() - timedelta(days=1),
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
    )
    EnonceDevoir.objects.create(devoir=devoir, contenu=devoir.enonce, ordre=1)

    response = client_enseignant.post(reverse("devoir-publier", args=[devoir.id]))
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_publier_devoir_non_enseignant_principal_403(client_apprenant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant)

    response = client_apprenant.post(reverse("devoir-publier", args=[devoir.id]))
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_modifier_devoir_non_publie_200(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant)

    response = client_enseignant.patch(
        reverse("devoir-modifier", args=[devoir.id]), {"titre": "Nouveau titre"}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK
    devoir.refresh_from_db()
    assert devoir.titre == "Nouveau titre"


@pytest.mark.django_db
def test_modifier_devoir_publie_409(client_enseignant, cours_enseignant):
    """Point 4 : « même contrôle » que les questions — AUCUN champ n'est
    modifiable une fois le devoir publié, pas seulement `enonce`."""
    devoir = _devoir_avec_question(cours_enseignant, est_publie=True)

    response = client_enseignant.patch(
        reverse("devoir-modifier", args=[devoir.id]), {"titre": "Trop tard"}, format="json"
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"]["code"] == "CONFLICT"
    devoir.refresh_from_db()
    assert devoir.titre == "D"


@pytest.mark.django_db
def test_modifier_devoir_enonce_vide_400(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant)

    response = client_enseignant.patch(
        reverse("devoir-modifier", args=[devoir.id]), {"enonce": "   "}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "enonce" in response.data["error"]["fields"]


@pytest.mark.django_db
def test_creation_devoir_ignore_est_publie_force_false(client_enseignant, cours_enseignant):
    payload = {
        "titre": "D",
        "enonce": "Énoncé",
        "date_limite": (timezone.now() + timedelta(days=7)).isoformat(),
        "est_publie": True,
    }
    response = client_enseignant.post(
        reverse("devoir-creer", args=[cours_enseignant.id]), payload, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED
    devoir = Devoir.objects.get(pk=response.data["id"])
    assert devoir.est_publie is False


@pytest.mark.django_db
def test_modifier_devoir_ignore_est_publie(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant)

    response = client_enseignant.patch(
        reverse("devoir-modifier", args=[devoir.id]), {"est_publie": True}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK
    devoir.refresh_from_db()
    assert devoir.est_publie is False


@pytest.mark.django_db
def test_modifier_question_devoir_non_publie_200(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant)
    question = devoir.questions.first()

    response = client_enseignant.patch(
        reverse("devoir-question-modifier", args=[question.id]),
        {"enonce": "Q1 modifiée"},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    question.refresh_from_db()
    assert question.enonce == "Q1 modifiée"


@pytest.mark.django_db
def test_modifier_question_devoir_publie_409(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant, est_publie=True)
    question = devoir.questions.first()

    response = client_enseignant.patch(
        reverse("devoir-question-modifier", args=[question.id]),
        {"enonce": "Trop tard"},
        format="json",
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"]["code"] == "CONFLICT"


@pytest.mark.django_db
def test_supprimer_question_devoir_non_publie_204(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant)
    question = devoir.questions.first()

    response = client_enseignant.delete(reverse("devoir-question-supprimer", args=[question.id]))
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not QuestionDevoir.objects.filter(pk=question.id).exists()


@pytest.mark.django_db
def test_supprimer_question_devoir_publie_409(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant, est_publie=True)
    question = devoir.questions.first()

    response = client_enseignant.delete(reverse("devoir-question-supprimer", args=[question.id]))
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"]["code"] == "CONFLICT"
    assert QuestionDevoir.objects.filter(pk=question.id).exists()


@pytest.mark.django_db
def test_dupliquer_devoir_enseignant_principal_201_copie_profonde(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant)
    q1 = devoir.questions.first()
    ChoixReponse.objects.create(question=q1, texte="A", est_correct=True, ordre=1)
    ChoixReponse.objects.create(question=q1, texte="B", est_correct=False, ordre=2)
    EnonceDevoir.objects.create(devoir=devoir, contenu="Énoncé bonus", ordre=2)

    response = client_enseignant.post(reverse("devoir-dupliquer", args=[devoir.id]))
    assert response.status_code == status.HTTP_201_CREATED

    copie = Devoir.objects.get(pk=response.data["id"])
    assert copie.est_publie is False
    assert copie.source_devoir_id == devoir.id
    assert copie.enonces.count() == devoir.enonces.count() == 2
    assert copie.questions.count() == devoir.questions.count() == 1
    copie_q1 = copie.questions.first()
    assert copie_q1.choix.count() == 2
    assert set(copie_q1.choix.values_list("texte", "est_correct")) == {("A", True), ("B", False)}


@pytest.mark.django_db
def test_dupliquer_devoir_publie_autorise_copie_non_publiee(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant, est_publie=True)

    response = client_enseignant.post(reverse("devoir-dupliquer", args=[devoir.id]))
    assert response.status_code == status.HTTP_201_CREATED
    copie = Devoir.objects.get(pk=response.data["id"])
    assert copie.est_publie is False


def _client_authentifie(user):
    from rest_framework.authtoken.models import Token
    from rest_framework.test import APIClient

    token, _ = Token.objects.get_or_create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client


@pytest.mark.django_db
def test_dupliquer_devoir_par_le_createur_201(user_enseignant, cours, django_user_model):
    """Élargissement de permission propre à la duplication : le créateur
    du devoir, même s'il n'est plus/pas l'enseignant_principal actuel du
    cours, peut dupliquer son propre devoir."""
    autre_enseignant = django_user_model.objects.create_user(
        username="autre_prof", email="autre@yeki.test", password="Test1234!"
    )
    Profile.objects.create(user=autre_enseignant, user_type="enseignant_principal", is_active=True)
    cours.enseignant_principal = autre_enseignant.profile
    cours.save(update_fields=["enseignant_principal"])

    devoir = _devoir_avec_question(cours, cree_par=user_enseignant.profile)

    response = _client_authentifie(user_enseignant).post(reverse("devoir-dupliquer", args=[devoir.id]))
    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_dupliquer_devoir_enseignant_tiers_403(django_user_model, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant)

    tiers = django_user_model.objects.create_user(
        username="tiers", email="tiers@yeki.test", password="Test1234!"
    )
    Profile.objects.create(user=tiers, user_type="enseignant_principal", is_active=True)

    response = _client_authentifie(tiers).post(reverse("devoir-dupliquer", args=[devoir.id]))
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_demarrer_devoir_avant_date_debut_403(client_apprenant, cours_enseignant):
    devoir = _devoir_avec_question(
        cours_enseignant,
        date_debut=timezone.now() + timedelta(days=1),
        est_publie=True,
    )
    response = client_apprenant.post(reverse("demarrer-devoir", args=[devoir.id]))
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_soumettre_devoir_non_publie_404(client_apprenant_premium, cours_enseignant, user_apprenant_premium):
    # P9.1 : soumettre un devoir exige Premium — client_apprenant_premium
    # utilisé ici pour tester le 404 (devoir non publié), pas la matrice
    # d'accès, sans rapport avec ce que ce test vérifie.
    devoir = _devoir_avec_question(cours_enseignant, est_publie=False)
    SoumissionDevoir.objects.create(utilisateur=user_apprenant_premium, devoir=devoir, statut="en_cours")

    response = client_apprenant_premium.post(
        reverse("soumettre-devoir", args=[devoir.id]), {}, format="json"
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_soumettre_devoir_en_retard_reste_accepte(
    client_apprenant_premium, cours_enseignant, user_apprenant_premium
):
    """Décision actée : une soumission démarrée à temps mais rendue après
    date_limite reste ACCEPTÉE (200), pas rejetée — `SoumissionDevoir.est_en_retard`
    reste vrai pour le signaler, indépendamment du `statut` final (qui
    dépend de `type_correction`, hors périmètre P7.2 : un devoir en
    correction "auto", comme ici, passe directement à "corrige").
    P9.1 : client_apprenant_premium (soumettre un devoir exige Premium),
    sans rapport avec ce que ce test vérifie."""
    devoir = _devoir_avec_question(
        cours_enseignant,
        date_debut=timezone.now() - timedelta(days=2),
        date_limite=timezone.now() - timedelta(days=1),
        est_publie=True,
    )
    SoumissionDevoir.objects.create(
        utilisateur=user_apprenant_premium,
        devoir=devoir,
        statut="en_cours",
        debut=timezone.now() - timedelta(days=2),
    )

    response = client_apprenant_premium.post(
        reverse("soumettre-devoir", args=[devoir.id]), {"reponses": {}}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK
    soum = SoumissionDevoir.objects.get(utilisateur=user_apprenant_premium, devoir=devoir)
    assert soum.statut in ("soumis", "en_retard", "corrige")
    assert soum.est_en_retard is True


@pytest.mark.django_db
def test_une_seule_soumission_par_devoir_et_apprenant(cours_enseignant, user_apprenant):
    """Point 8 : déjà satisfait par `unique_together` — non-régression."""
    devoir = _devoir_avec_question(cours_enseignant, est_publie=True)
    SoumissionDevoir.objects.create(utilisateur=user_apprenant, devoir=devoir)

    with pytest.raises(IntegrityError):
        SoumissionDevoir.objects.create(utilisateur=user_apprenant, devoir=devoir)
