"""
Tests P8.3 — deux bugs réels trouvés en implémentant la refonte du
classement d'olympiade :
1. `Olympiade.statut_auto` renvoyait "terminée"/"fermée" (avec accents)
   alors que `ClassementOlympiadeView`/`CalculerClassementView` (et le
   frontend) comparent contre "terminee"/"fermee" (sans accent) — le
   classement était entièrement inatteignable, quel que soit l'état réel
   de l'olympiade.
2. `CalculerClassementView` ne notifiait aucun participant (seul un
   journal d'audit interne, `enregistrer_activite`).
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.evaluation.models import InscriptionOlympiade, Olympiade
from apps.notifications.models import Notification


@pytest.fixture
def olympiade_terminee(user_enseignant_cadre):
    now = timezone.now()
    return Olympiade.objects.create(
        titre="Olympiade Terminée Test",
        date_ouverture_inscription=now - timedelta(days=10),
        date_cloture_inscription=now - timedelta(days=8),
        date_debut_olympiade=now - timedelta(days=7),
        date_fin_olympiade=now - timedelta(days=6),
        duree_minutes=120,
        organisateur=user_enseignant_cadre.profile,
    )


def test_statut_auto_terminee_sans_accent(olympiade_terminee):
    # Bug corrigé : renvoyait "terminée" (avec accent), ne correspondait
    # jamais à la comparaison "not in ['terminee']" des vues.
    assert olympiade_terminee.statut_auto == "terminee"


@pytest.mark.django_db
def test_classement_accessible_une_fois_lolympiade_terminee(client_apprenant, olympiade_terminee):
    # Avant le correctif : 403 indéfiniment, peu importe l'état réel.
    response = client_apprenant.get(reverse("classement-olympiade", args=[olympiade_terminee.id]))
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_calculer_classement_notifie_chaque_participant(
    client_enseignant_cadre, user_apprenant, olympiade_terminee
):
    InscriptionOlympiade.objects.create(
        olympiade=olympiade_terminee, apprenant=user_apprenant, soumis=True, note=15.0
    )

    response = client_enseignant_cadre.post(
        reverse("calculer-classement", args=[olympiade_terminee.id])
    )

    assert response.status_code == status.HTTP_200_OK
    notif = Notification.objects.filter(
        utilisateur=user_apprenant, type="classement", objet_id=olympiade_terminee.id
    ).latest("id")
    assert "Classement disponible" in notif.titre
    assert olympiade_terminee.titre in notif.contenu
