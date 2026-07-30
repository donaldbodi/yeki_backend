"""
Tests P7.3 : mécanique de tentative des devoirs (SORTIES de page, pas
soumissions multiples — `POST /devoirs/<id>/sortir/`) et correction
auto/manuelle.

Réutilise les fixtures déjà établies en P7.2
(`test_cycle_vie_devoir.py` : `cours_enseignant`, patron
`_devoir_avec_question`) plutôt que d'en recréer des équivalentes
(règle 1).
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.evaluation.models import (
    ChoixReponse,
    Devoir,
    EnonceDevoir,
    QuestionDevoir,
    ReponseDevoir,
    SoumissionDevoir,
)
from apps.evaluation.views.devoirs import _normaliser_texte


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
        tentatives_max=3,
    )
    defaults.update(kwargs)
    devoir = Devoir.objects.create(**defaults)
    EnonceDevoir.objects.create(devoir=devoir, contenu=devoir.enonce, ordre=1)
    return devoir


def _question_texte(devoir, reponse_attendue="Paris", points=1.0, ordre=1):
    return QuestionDevoir.objects.create(
        devoir=devoir,
        enonce=f"Q{ordre}",
        type_question="texte",
        reponse_attendue=reponse_attendue,
        points=points,
        ordre=ordre,
    )


def _question_qcm(devoir, ordre=1, points=1.0):
    q = QuestionDevoir.objects.create(
        devoir=devoir, enonce=f"Q{ordre}", type_question="qcm", points=points, ordre=ordre
    )
    ChoixReponse.objects.create(question=q, texte="Bonne", est_correct=True, ordre=1)
    ChoixReponse.objects.create(question=q, texte="Mauvaise", est_correct=False, ordre=2)
    return q


# ── _normaliser_texte ────────────────────────────────────────────────


def test_normaliser_texte_casse_accents_ponctuation_espaces():
    assert _normaliser_texte("Café") == "cafe"
    assert _normaliser_texte("PARIS") == "paris"
    assert _normaliser_texte("Paris.") == "paris"
    assert _normaliser_texte("Paris!") == "paris"
    assert _normaliser_texte("Paris   France") == "paris france"
    assert _normaliser_texte("  Paris  ") == "paris"
    assert _normaliser_texte(None) == ""


# ── SortirDevoirView — tentatives = sorties de page ─────────────────


@pytest.mark.django_db
def test_sortir_devoir_sans_epuiser_incremente_sans_soumettre(
    client_apprenant_premium, cours_enseignant, user_apprenant_premium
):
    # P9.1 : sortir/soumettre un devoir exige Premium, sans rapport avec ce
    # que ce test vérifie (mécanique de sortie de page P7.3).
    devoir = _devoir_avec_question(cours_enseignant, tentatives_max=3)
    _question_texte(devoir)
    soum = SoumissionDevoir.objects.create(
        utilisateur=user_apprenant_premium, devoir=devoir, statut="en_cours"
    )

    response = client_apprenant_premium.post(reverse("devoir-sortir", args=[devoir.id]), {}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["force_submit"] is False
    assert response.data["sorties"] == 1
    soum.refresh_from_db()
    assert soum.sorties == 1
    assert soum.statut == "en_cours"
    assert not ReponseDevoir.objects.filter(soumission=soum).exists()


@pytest.mark.django_db
def test_sortir_devoir_tentatives_epuisees_soumet_et_corrige(
    client_apprenant_premium, cours_enseignant, user_apprenant_premium
):
    """Sortie forcée = VRAIE soumission corrigée (P7.3), pas un simple
    enregistrement brut des réponses (bug de l'ancienne version).
    P9.1 : client_apprenant_premium, sans rapport avec ce test."""
    devoir = _devoir_avec_question(cours_enseignant, tentatives_max=1, type_correction="auto")
    q_texte = _question_texte(devoir, reponse_attendue="Paris", points=1.0, ordre=1)
    q_qcm = _question_qcm(devoir, ordre=2, points=1.0)
    soum = SoumissionDevoir.objects.create(
        utilisateur=user_apprenant_premium, devoir=devoir, statut="en_cours"
    )
    bonne_choix = q_qcm.choix.get(est_correct=True)

    response = client_apprenant_premium.post(
        reverse("devoir-sortir", args=[devoir.id]),
        {"reponses": {str(q_texte.id): "PARIS.", str(q_qcm.id): bonne_choix.texte}},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["force_submit"] is True
    assert response.data["statut"] == "corrige"
    assert response.data["note"] == 20.0

    soum.refresh_from_db()
    assert soum.statut == "corrige"
    assert soum.note == 20.0
    assert soum.soumis_le is not None

    rep_texte = ReponseDevoir.objects.get(soumission=soum, question=q_texte)
    assert rep_texte.est_correct is True  # "PARIS." normalisé malgré casse+ponctuation
    rep_qcm = ReponseDevoir.objects.get(soumission=soum, question=q_qcm)
    assert rep_qcm.est_correct is True


@pytest.mark.django_db
def test_sortir_devoir_epuise_avec_mauvaise_reponse_note_partielle(
    client_apprenant_premium, cours_enseignant, user_apprenant_premium
):
    # P9.1 : client_apprenant_premium, sans rapport avec ce test.
    devoir = _devoir_avec_question(cours_enseignant, tentatives_max=1, type_correction="auto")
    q_texte = _question_texte(devoir, reponse_attendue="Paris", points=1.0, ordre=1)
    q_qcm = _question_qcm(devoir, ordre=2, points=1.0)
    soum = SoumissionDevoir.objects.create(
        utilisateur=user_apprenant_premium, devoir=devoir, statut="en_cours"
    )
    mauvais_choix = q_qcm.choix.get(est_correct=False)

    response = client_apprenant_premium.post(
        reverse("devoir-sortir", args=[devoir.id]),
        {"reponses": {str(q_texte.id): "Londres", str(q_qcm.id): mauvais_choix.texte}},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    soum.refresh_from_db()
    assert soum.note == 0.0


# ── Comparaison texte normalisée (correction auto) ──────────────────


@pytest.mark.django_db
def test_soumettre_devoir_comparaison_texte_normalisee(
    client_apprenant_premium, cours_enseignant, user_apprenant_premium
):
    # P9.1 : client_apprenant_premium, sans rapport avec ce test.
    devoir = _devoir_avec_question(cours_enseignant, tentatives_max=3, type_correction="auto")
    q = _question_texte(devoir, reponse_attendue="Paris", points=1.0, ordre=1)
    SoumissionDevoir.objects.create(
        utilisateur=user_apprenant_premium, devoir=devoir, statut="en_cours"
    )

    response = client_apprenant_premium.post(
        reverse("soumettre-devoir", args=[devoir.id]),
        {"reponses": {str(q.id): "  PARIS.  "}},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["note"] == 20.0
    rep = ReponseDevoir.objects.get(question=q)
    assert rep.est_correct is True


# ── QCM interdit en correction manuelle ──────────────────────────────


@pytest.mark.django_db
def test_creer_question_qcm_devoir_manuel_400(client_enseignant, cours_enseignant):
    devoir = Devoir.objects.create(
        titre="D",
        enonce="E",
        date_debut=timezone.now() - timedelta(days=1),
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
        type_correction="manuel",
    )
    enonce_devoir = EnonceDevoir.objects.create(devoir=devoir, contenu="E", ordre=1)

    payload = {
        "enonce": "Q1",
        "type_question": "qcm",
        "points": 1.0,
        "choix": [
            {"texte": "A", "est_correct": True},
            {"texte": "B", "est_correct": False},
        ],
    }
    response = client_enseignant.post(
        reverse("devoir-enonce-question-ajouter", args=[enonce_devoir.id]), payload, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "type_question" in response.data["error"]["fields"]
    assert not QuestionDevoir.objects.filter(devoir=devoir).exists()


@pytest.mark.django_db
def test_creer_question_texte_devoir_manuel_201(client_enseignant, cours_enseignant):
    """Non-régression : texte libre reste autorisé en correction manuelle."""
    devoir = Devoir.objects.create(
        titre="D",
        enonce="E",
        date_debut=timezone.now() - timedelta(days=1),
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_enseignant,
        est_publie=False,
        type_correction="manuel",
    )
    enonce_devoir = EnonceDevoir.objects.create(devoir=devoir, contenu="E", ordre=1)

    payload = {"enonce": "Q1", "type_question": "texte", "points": 1.0}
    response = client_enseignant.post(
        reverse("devoir-enonce-question-ajouter", args=[enonce_devoir.id]), payload, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_passer_devoir_auto_a_manuel_avec_qcm_existant_400(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant, est_publie=False, type_correction="auto")
    _question_qcm(devoir)

    response = client_enseignant.patch(
        reverse("devoir-modifier", args=[devoir.id]), {"type_correction": "manuel"}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    devoir.refresh_from_db()
    assert devoir.type_correction == "auto"


@pytest.mark.django_db
def test_passer_devoir_auto_a_manuel_sans_qcm_200(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant, est_publie=False, type_correction="auto")
    _question_texte(devoir)

    response = client_enseignant.patch(
        reverse("devoir-modifier", args=[devoir.id]), {"type_correction": "manuel"}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK
    devoir.refresh_from_db()
    assert devoir.type_correction == "manuel"


# ── Résultat apprenant — choix snapshot + bonne réponse ─────────────


@pytest.mark.django_db
def test_resultat_devoir_expose_choix_snapshot_et_bonne_reponse(
    client_apprenant, cours_enseignant, user_apprenant
):
    devoir = _devoir_avec_question(cours_enseignant, tentatives_max=3, type_correction="auto")
    q_texte = _question_texte(devoir, reponse_attendue="Paris", points=1.0, ordre=1)
    q_qcm = _question_qcm(devoir, ordre=2, points=1.0)
    soum = SoumissionDevoir.objects.create(
        utilisateur=user_apprenant, devoir=devoir, statut="corrige", note=20.0, commentaire="Bon travail"
    )
    mauvais_choix = q_qcm.choix.get(est_correct=False)
    ReponseDevoir.objects.create(
        soumission=soum, question=q_texte, reponse="Lyon", est_correct=False, points_obtenus=0
    )
    ReponseDevoir.objects.create(
        soumission=soum,
        question=q_qcm,
        reponse=mauvais_choix.texte,
        choix=mauvais_choix,
        est_correct=False,
        points_obtenus=0,
    )

    response = client_apprenant.get(reverse("resultat-devoir", args=[devoir.id]))
    assert response.status_code == status.HTTP_200_OK
    # P7.6 : dénominateur de la note, absent jusqu'ici — aucun appelant
    # frontend de la route de résultat ne le transmettait par ailleurs.
    assert response.data["note_sur"] == devoir.note_sur

    detail_qcm = next(
        d for d in response.data["questions_detail"] if d["question_id"] == q_qcm.id
    )
    # L'apprenant doit voir TOUTES les options, pas seulement la sienne.
    assert len(detail_qcm["choix"]) == 2
    assert any(c["texte"] == "Bonne" and c["est_correct"] for c in detail_qcm["choix"])
    assert any(c["texte"] == "Mauvaise" and not c["est_correct"] for c in detail_qcm["choix"])
    assert detail_qcm["bonne_reponse"] == "Bonne"
    assert detail_qcm["commentaire_enseignant"] == "Bon travail"

    detail_texte = next(
        d for d in response.data["questions_detail"] if d["question_id"] == q_texte.id
    )
    assert detail_texte["bonne_reponse"] == "Paris"
    assert detail_texte["choix"] == []
    assert detail_texte["commentaire_enseignant"] == "Bon travail"


# ── Non-régression : DetailSoumissionEnseignantView ─────────────────


@pytest.mark.django_db
def test_detail_soumission_enseignant_ne_plante_pas(
    client_enseignant, cours_enseignant, user_apprenant
):
    """Reproduit d'abord le bug (`rep.question.texte` — AttributeError,
    QuestionDevoir n'a que `enonce`), corrigé ici."""
    devoir = _devoir_avec_question(cours_enseignant, tentatives_max=3, type_correction="manuel")
    q = _question_texte(devoir, reponse_attendue="", points=1.0, ordre=1)
    soum = SoumissionDevoir.objects.create(
        utilisateur=user_apprenant, devoir=devoir, statut="soumis"
    )
    ReponseDevoir.objects.create(soumission=soum, question=q, reponse="Ma réponse")

    response = client_enseignant.get(reverse("soumission-detail", args=[soum.id]))

    assert response.status_code == status.HTTP_200_OK
    detail = response.data["reponses"][0]
    assert detail["question_enonce"] == q.enonce
    assert detail["reponse"] == "Ma réponse"


# ── Correction manuelle : note + commentaire facultatif ─────────────


@pytest.mark.django_db
def test_corriger_soumission_note_et_commentaire(client_enseignant, cours_enseignant, user_apprenant):
    devoir = _devoir_avec_question(cours_enseignant, type_correction="manuel")
    _question_texte(devoir)
    soum = SoumissionDevoir.objects.create(
        utilisateur=user_apprenant, devoir=devoir, statut="soumis"
    )

    response = client_enseignant.patch(
        reverse("soumission-corriger", args=[soum.id]),
        {"note": 16.5, "commentaire": "Bon travail, mais…"},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    soum.refresh_from_db()
    assert soum.note == 16.5
    assert soum.commentaire == "Bon travail, mais…"
    assert soum.statut == "corrige"


@pytest.mark.django_db
def test_corriger_soumission_commentaire_facultatif(client_enseignant, cours_enseignant, user_apprenant):
    devoir = _devoir_avec_question(cours_enseignant, type_correction="manuel")
    _question_texte(devoir)
    soum = SoumissionDevoir.objects.create(
        utilisateur=user_apprenant, devoir=devoir, statut="soumis"
    )

    response = client_enseignant.patch(
        reverse("soumission-corriger", args=[soum.id]), {"note": 10}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK
    soum.refresh_from_db()
    assert soum.commentaire == ""


# ── Énoncé riche avec émoji (correction manuelle, "comme Word") ─────


@pytest.mark.django_db
def test_enonce_devoir_survit_avec_emoji(client_enseignant, cours_enseignant):
    devoir = _devoir_avec_question(cours_enseignant, est_publie=False, type_correction="manuel")

    contenu = "Rédigez un texte sur la joie 😀🎉 et la persévérance 💪."
    response = client_enseignant.patch(
        reverse("devoir-enonce-detail", args=[devoir.enonces.first().id]),
        {"contenu": contenu},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    enonce = EnonceDevoir.objects.get(devoir=devoir)
    assert enonce.contenu == contenu
