"""
Tests P10.3 : commande `envoyer_rappels` — devoir/olympiade/abonnement à
échéance, idempotence (ré-exécution = pas de doublon).
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.evaluation.models import Devoir, InscriptionOlympiade, Olympiade
from apps.notifications.models import Notification
from apps.paiement.models import AbonnementPremium


@pytest.mark.django_db
def test_devoir_dans_1h_notifie_les_non_soumis_horaire(user_apprenant, cours, departement):
    profil = user_apprenant.profile
    profil.cursus = departement.parcours.nom
    profil.save(update_fields=["cursus"])

    devoir = Devoir.objects.create(
        titre="Devoir Test",
        enonce="Énoncé.",
        date_limite=timezone.now() + timedelta(minutes=45),
        cours_lie=cours,
        est_publie=True,
    )

    call_command("envoyer_rappels", "--horaire")

    assert Notification.objects.filter(
        utilisateur=user_apprenant, titre="Devoir à rendre dans 1 heure", objet_id=devoir.id
    ).exists()


@pytest.mark.django_db
def test_devoir_dans_23h_ne_declenche_pas_le_rappel_horaire(user_apprenant, cours, departement):
    profil = user_apprenant.profile
    profil.cursus = departement.parcours.nom
    profil.save(update_fields=["cursus"])

    devoir = Devoir.objects.create(
        titre="Devoir Test",
        enonce="Énoncé.",
        date_limite=timezone.now() + timedelta(hours=23),
        cours_lie=cours,
        est_publie=True,
    )

    call_command("envoyer_rappels", "--horaire")

    assert not Notification.objects.filter(
        utilisateur=user_apprenant, objet_id=devoir.id, objet_type="Devoir"
    ).exists()


@pytest.mark.django_db
def test_reexecution_ne_cree_pas_de_doublon(user_apprenant, cours, departement):
    profil = user_apprenant.profile
    profil.cursus = departement.parcours.nom
    profil.save(update_fields=["cursus"])

    Devoir.objects.create(
        titre="Devoir Test",
        enonce="Énoncé.",
        date_limite=timezone.now() + timedelta(minutes=30),
        cours_lie=cours,
        est_publie=True,
    )

    call_command("envoyer_rappels", "--horaire")
    call_command("envoyer_rappels", "--horaire")

    assert Notification.objects.filter(
        utilisateur=user_apprenant, titre="Devoir à rendre dans 1 heure"
    ).count() == 1


@pytest.mark.django_db
def test_apprenant_deja_soumis_nest_pas_rappele(user_apprenant, cours, departement):
    from apps.evaluation.models import SoumissionDevoir

    profil = user_apprenant.profile
    profil.cursus = departement.parcours.nom
    profil.save(update_fields=["cursus"])

    devoir = Devoir.objects.create(
        titre="Devoir Test",
        enonce="Énoncé.",
        date_limite=timezone.now() + timedelta(minutes=30),
        cours_lie=cours,
        est_publie=True,
    )
    SoumissionDevoir.objects.create(utilisateur=user_apprenant, devoir=devoir, statut="soumis")

    call_command("envoyer_rappels", "--horaire")

    assert not Notification.objects.filter(
        utilisateur=user_apprenant, objet_id=devoir.id, objet_type="Devoir"
    ).exists()


@pytest.mark.django_db
def test_olympiade_dans_1h_notifie_les_inscrits(user_apprenant):
    olympiade = Olympiade.objects.create(
        titre="Olympiade Test",
        date_ouverture_inscription=timezone.now() - timedelta(days=1),
        date_cloture_inscription=timezone.now() - timedelta(hours=2),
        date_debut_olympiade=timezone.now() + timedelta(minutes=40),
        date_fin_olympiade=timezone.now() + timedelta(hours=3),
        duree_minutes=120,
    )
    InscriptionOlympiade.objects.create(olympiade=olympiade, apprenant=user_apprenant)

    call_command("envoyer_rappels", "--horaire")

    assert Notification.objects.filter(
        utilisateur=user_apprenant, titre="Olympiade dans 1 heure", objet_id=olympiade.id
    ).exists()


@pytest.mark.django_db
def test_abonnement_expire_dans_3_jours_notifie_quotidien(user_apprenant, departement):
    # Rectification : l'abonnement est désormais PAR DÉPARTEMENT — le
    # titre de la notification inclut maintenant son nom (un même
    # apprenant peut avoir plusieurs abonnements distincts à rappeler).
    abonnement = AbonnementPremium.objects.create(
        utilisateur=user_apprenant,
        departement=departement,
        type_abonnement="mensuel",
        actif=True,
        fin=timezone.now() + timedelta(days=2),
    )

    call_command("envoyer_rappels", "--quotidien")

    assert Notification.objects.filter(
        utilisateur=user_apprenant,
        titre=f"Abonnement « {departement.nom} » expire dans 3 jours",
        objet_id=abonnement.id,
    ).exists()


@pytest.mark.django_db
def test_abonnement_inactif_nest_pas_notifie(user_apprenant):
    AbonnementPremium.objects.create(
        utilisateur=user_apprenant,
        type_abonnement="mensuel",
        actif=False,
        fin=timezone.now() + timedelta(days=2),
    )

    call_command("envoyer_rappels", "--quotidien")

    assert not Notification.objects.filter(
        utilisateur=user_apprenant, titre="Abonnement expire dans 3 jours"
    ).exists()
