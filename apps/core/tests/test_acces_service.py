"""
Tests P9.1 : AccesService — matrice d'accès Gratuit/Premium (CDC_BACKEND §5.2).

Fixtures réutilisées depuis conftest.py racine (user_apprenant,
user_apprenant_premium, exercice, devoir, cours, departement). Les fixtures
spécifiques à ce ticket (exercices 2★/3★, QuestionForum, Repetiteur,
Olympiade) sont définies ci-dessous.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.services import AccesService
from apps.evaluation.models import Exercice, Devoir, Olympiade
from apps.forum.models import QuestionForum
from apps.paiement.models import AbonnementPremium, PaiementOlympiade
from apps.repetiteurs.models import Repetiteur


@pytest.fixture
def exercice_2_etoiles(db, cours):
    return Exercice.objects.create(cours=cours, titre="Exercice 2★", enonce="…", etoiles=2)


@pytest.fixture
def exercice_3_etoiles(db, cours):
    return Exercice.objects.create(cours=cours, titre="Exercice 3★", enonce="…", etoiles=3)


@pytest.fixture
def question_forum(db, user_apprenant):
    return QuestionForum.objects.create(auteur=user_apprenant, contenu="Une question", source="libre")


@pytest.fixture
def question_forum_depuis_lecon(db, user_apprenant):
    return QuestionForum.objects.create(
        auteur=user_apprenant, contenu="Une question depuis une leçon", source="lecon", lecon_id=1
    )


@pytest.fixture
def repetiteur(db, cours, user_enseignant):
    from apps.accounts.models import Profile

    profil = Profile.objects.get(user=user_enseignant)
    profil.is_repetiteur = True
    profil.save()
    return Repetiteur.objects.create(
        enseignant=profil, cours=cours, ville="Douala", telephone="237600000000"
    )


def _olympiade(payante: bool):
    now = timezone.now()
    return Olympiade.objects.create(
        titre="Olympiade Test",
        date_ouverture_inscription=now,
        date_cloture_inscription=now + timedelta(days=1),
        date_debut_olympiade=now + timedelta(days=2),
        date_fin_olympiade=now + timedelta(days=2, hours=2),
        demande_paiement_participants=payante,
        prix_participation=100 if payante else 0,
    )


@pytest.fixture
def olympiade_gratuite(db):
    return _olympiade(payante=False)


@pytest.fixture
def olympiade_payante(db):
    return _olympiade(payante=True)


# ── est_premium ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_est_premium_vrai_si_abonnement_actif(user_apprenant_premium):
    assert AccesService.est_premium(user_apprenant_premium) is True


@pytest.mark.django_db
def test_est_premium_faux_si_pas_dabonnement(user_apprenant):
    assert AccesService.est_premium(user_apprenant) is False


@pytest.mark.django_db
def test_est_premium_faux_si_abonnement_expire(user_apprenant):
    AbonnementPremium.objects.create(
        utilisateur=user_apprenant,
        type_abonnement="mensuel",
        actif=True,
        fin=timezone.now() - timedelta(days=1),
    )
    assert AccesService.est_premium(user_apprenant) is False


# ── Exercice ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_exercice_1_etoile_toujours_visible_et_soumissible_meme_gratuit(user_apprenant, exercice):
    assert AccesService.peut_voir(user_apprenant, exercice) is True
    assert AccesService.peut_soumettre(user_apprenant, exercice) is True


@pytest.mark.django_db
def test_exercice_2_etoiles_visible_mais_non_soumissible_en_gratuit(user_apprenant, exercice_2_etoiles):
    assert AccesService.peut_voir(user_apprenant, exercice_2_etoiles) is True
    assert AccesService.peut_soumettre(user_apprenant, exercice_2_etoiles) is False


@pytest.mark.django_db
def test_exercice_2_etoiles_visible_et_soumissible_en_premium(
    user_apprenant_premium, exercice_2_etoiles
):
    assert AccesService.peut_voir(user_apprenant_premium, exercice_2_etoiles) is True
    assert AccesService.peut_soumettre(user_apprenant_premium, exercice_2_etoiles) is True


@pytest.mark.django_db
def test_exercice_3_etoiles_invisible_en_gratuit(user_apprenant, exercice_3_etoiles):
    assert AccesService.peut_voir(user_apprenant, exercice_3_etoiles) is False
    assert AccesService.peut_soumettre(user_apprenant, exercice_3_etoiles) is False


@pytest.mark.django_db
def test_exercice_3_etoiles_visible_en_premium(user_apprenant_premium, exercice_3_etoiles):
    assert AccesService.peut_voir(user_apprenant_premium, exercice_3_etoiles) is True
    assert AccesService.peut_soumettre(user_apprenant_premium, exercice_3_etoiles) is True


@pytest.mark.django_db
def test_etoiles_max_visibles_coherent_avec_peut_voir_exercice(user_apprenant, cours):
    seuil = AccesService.etoiles_max_visibles(user_apprenant)
    assert seuil == AccesService.ETOILES_VITRINE_GRATUIT
    for etoiles in range(1, 6):
        ex = Exercice.objects.create(cours=cours, titre=f"Ex {etoiles}★", enonce="…", etoiles=etoiles)
        assert AccesService.peut_voir(user_apprenant, ex) == (etoiles <= seuil)


@pytest.mark.django_db
def test_etoiles_max_visibles_illimite_en_premium(user_apprenant_premium):
    assert AccesService.etoiles_max_visibles(user_apprenant_premium) is None


# ── Devoir ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_devoir_invisible_et_non_soumissible_en_gratuit(user_apprenant, devoir):
    assert AccesService.peut_voir(user_apprenant, devoir) is False
    assert AccesService.peut_soumettre(user_apprenant, devoir) is False


@pytest.mark.django_db
def test_devoir_visible_et_soumissible_en_premium(user_apprenant_premium, devoir):
    assert AccesService.peut_voir(user_apprenant_premium, devoir) is True
    assert AccesService.peut_soumettre(user_apprenant_premium, devoir) is True


@pytest.mark.django_db
def test_devoir_classe_nue_bloquee_en_gratuit(user_apprenant):
    """Vue liste sans instance concrète (has_permission) : tout-ou-rien."""
    assert AccesService.peut_voir(user_apprenant, Devoir) is False


# ── Forum ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_question_forum_invisible_en_gratuit(user_apprenant, question_forum):
    assert AccesService.peut_voir(user_apprenant, question_forum) is False
    assert AccesService.peut_soumettre(user_apprenant, question_forum) is False


@pytest.mark.django_db
def test_question_forum_depuis_lecon_invisible_en_gratuit(user_apprenant, question_forum_depuis_lecon):
    """« pas de préoccupation depuis une leçon » = un post forum
    source=lecon, déjà couvert par la règle générale « PAS de forum »."""
    assert AccesService.peut_voir(user_apprenant, question_forum_depuis_lecon) is False
    assert AccesService.peut_soumettre(user_apprenant, question_forum_depuis_lecon) is False


@pytest.mark.django_db
def test_question_forum_visible_en_premium(user_apprenant_premium, question_forum):
    assert AccesService.peut_voir(user_apprenant_premium, question_forum) is True
    assert AccesService.peut_soumettre(user_apprenant_premium, question_forum) is True


# ── Répétiteur ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_repetiteur_toujours_visible_peu_importe_premium(user_apprenant, user_apprenant_premium, repetiteur):
    assert AccesService.peut_voir(user_apprenant, repetiteur) is True
    assert AccesService.peut_voir(user_apprenant_premium, repetiteur) is True


# ── Olympiade ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_olympiade_toujours_visible_peu_importe_premium(
    user_apprenant, user_apprenant_premium, olympiade_payante
):
    assert AccesService.peut_voir(user_apprenant, olympiade_payante) is True
    assert AccesService.peut_voir(user_apprenant_premium, olympiade_payante) is True


@pytest.mark.django_db
def test_olympiade_soumission_toujours_vraie_si_pas_de_paiement_requis(
    user_apprenant, olympiade_gratuite
):
    assert AccesService.peut_soumettre(user_apprenant, olympiade_gratuite) is True


@pytest.mark.django_db
def test_olympiade_soumission_dependant_du_paiement_pas_du_premium(
    user_apprenant, user_apprenant_premium, olympiade_payante
):
    # Ni gratuit ni premium n'ont payé : bloqué pour les deux.
    assert AccesService.peut_soumettre(user_apprenant, olympiade_payante) is False
    assert AccesService.peut_soumettre(user_apprenant_premium, olympiade_payante) is False

    PaiementOlympiade.objects.create(
        apprenant=user_apprenant, olympiade=olympiade_payante, montant=100, statut="paye"
    )
    assert AccesService.peut_soumettre(user_apprenant, olympiade_payante) is True
    # Le premium ne dispense pas non plus l'autre apprenant qui n'a pas payé.
    assert AccesService.peut_soumettre(user_apprenant_premium, olympiade_payante) is False


# ── Lecon / vidéo ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_lecon_toujours_visible_peu_importe_premium(user_apprenant, user_apprenant_premium, cours):
    from apps.formation.models import Lecon

    lecon = Lecon.objects.create(titre="Leçon Test", description="…", cours=cours)
    assert AccesService.peut_voir(user_apprenant, lecon) is True
    assert AccesService.peut_voir(user_apprenant_premium, lecon) is True


@pytest.mark.django_db
def test_video_lecon_masquee_en_gratuit_visible_en_premium(user_apprenant, user_apprenant_premium):
    assert AccesService.peut_voir_video_lecon(user_apprenant) is False
    assert AccesService.peut_voir_video_lecon(user_apprenant_premium) is True


# ── Non-apprenant ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_utilisateur_enseignant_jamais_restreint_par_la_matrice(user_enseignant, devoir, question_forum):
    assert AccesService.peut_voir(user_enseignant, devoir) is True
    assert AccesService.peut_soumettre(user_enseignant, devoir) is True
    assert AccesService.peut_voir(user_enseignant, question_forum) is True


# ── Type non géré ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_type_objet_non_gere_leve_typeerror(user_apprenant):
    with pytest.raises(TypeError):
        AccesService.peut_voir(user_apprenant, object())
    with pytest.raises(TypeError):
        AccesService.peut_soumettre(user_apprenant, object())
