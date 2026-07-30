"""
Tests P10.3 : signaux Django remplaçant/complétant les créations
manuelles de Notification dispersées dans les vues (catalogue
CDC_BACKEND §9.1.1). Un test par déclencheur converti/ajouté — prouve
qu'une Notification existe SANS qu'aucun code de vue n'ait appelé
`creer_notification` explicitement (la vue testée n'en contient plus).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.evaluation.models import Devoir, SoumissionDevoir
from apps.forum.models import QuestionForum, ReponseQuestion
from apps.formation.models import Cours, DemandeAccesFormation
from apps.notifications.models import Notification
from apps.paiement.models import DemandePaiementManuelle, DemandeRetrait, YekiWallet


@pytest.mark.django_db
def test_devoir_publie_notifie_les_apprenants_du_cursus(user_apprenant, cours, departement):
    profil = user_apprenant.profile
    profil.cursus = departement.parcours.nom
    profil.save(update_fields=["cursus"])

    devoir = Devoir.objects.create(
        titre="Devoir Test",
        enonce="Énoncé du devoir.",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours,
        est_publie=False,
    )

    devoir.est_publie = True
    devoir.save(update_fields=["est_publie"])

    assert Notification.objects.filter(
        utilisateur=user_apprenant, type="devoir", objet_id=devoir.id
    ).exists()


@pytest.mark.django_db
def test_devoir_corrige_notifie_lapprenant(user_apprenant, cours):
    devoir = Devoir.objects.create(
        titre="Devoir Test",
        enonce="Énoncé du devoir.",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours,
        est_publie=True,
    )
    soum = SoumissionDevoir.objects.create(utilisateur=user_apprenant, devoir=devoir, statut="soumis")

    soum.note = 15
    soum.statut = "corrige"
    soum.save(update_fields=["note", "statut"])

    notif = Notification.objects.get(
        utilisateur=user_apprenant, type="correction", objet_id=devoir.id
    )
    assert "15" in notif.contenu


@pytest.mark.django_db
def test_reponse_forum_notifie_lauteur_de_la_question(user_apprenant, user_enseignant):
    question = QuestionForum.objects.create(auteur=user_apprenant, contenu="Une question ?")

    ReponseQuestion.objects.create(question=question, auteur=user_enseignant, contenu="Une réponse.")

    assert Notification.objects.filter(
        utilisateur=user_apprenant, type="forum", objet_id=question.id
    ).exists()


@pytest.mark.django_db
def test_reponse_a_sa_propre_question_ne_notifie_pas(user_apprenant):
    question = QuestionForum.objects.create(auteur=user_apprenant, contenu="Une question ?")

    ReponseQuestion.objects.create(question=question, auteur=user_apprenant, contenu="Auto-réponse.")

    assert not Notification.objects.filter(utilisateur=user_apprenant, type="forum").exists()


@pytest.mark.django_db
def test_changement_de_grade_notifie_lenseignant(user_enseignant):
    profil = user_enseignant.profile
    profil.user_type = "enseignant_principal"
    profil.save(update_fields=["user_type"])

    assert Notification.objects.filter(
        utilisateur=user_enseignant, titre="Changement de grade"
    ).exists()


@pytest.mark.django_db
def test_validation_repetiteur_notifie_lenseignant(user_enseignant):
    profil = user_enseignant.profile
    profil.is_repetiteur = True
    profil.save(update_fields=["is_repetiteur"])

    assert Notification.objects.filter(
        utilisateur=user_enseignant, titre="Vous êtes validé comme répétiteur"
    ).exists()


@pytest.mark.django_db
def test_nouveau_cours_notifie_les_apprenants_du_cursus(user_apprenant, departement):
    profil = user_apprenant.profile
    profil.cursus = departement.parcours.nom
    profil.save(update_fields=["cursus"])

    cours = Cours.objects.create(titre="Nouveau cours", niveau="Terminale", departement=departement)

    assert Notification.objects.filter(
        utilisateur=user_apprenant, type="devoir", objet_id=cours.id, objet_type="Cours"
    ).exists()


@pytest.mark.django_db
def test_demande_acces_formation_creee_notifie_ladmin_du_parcours(
    user_apprenant, user_enseignant_admin, departement
):
    departement.parcours.admin = user_enseignant_admin.profile
    departement.parcours.save(update_fields=["admin"])

    demande = DemandeAccesFormation.objects.create(apprenant=user_apprenant, departement=departement)

    assert Notification.objects.filter(
        utilisateur=user_enseignant_admin, objet_id=demande.id, objet_type="DemandeAccesFormation"
    ).exists()


@pytest.mark.django_db
def test_demande_acces_formation_decidee_notifie_lapprenant(
    user_apprenant, user_enseignant_admin, departement
):
    demande = DemandeAccesFormation.objects.create(apprenant=user_apprenant, departement=departement)
    Notification.objects.filter(utilisateur=user_apprenant).delete()

    demande.statut = "acceptee"
    demande.save(update_fields=["statut"])

    assert Notification.objects.filter(
        utilisateur=user_apprenant, objet_id=departement.id, objet_type="Departement"
    ).exists()


@pytest.mark.django_db
def test_nouvelle_demande_paiement_notifie_service_client(user_apprenant, user_service_client):
    demande = DemandePaiementManuelle.objects.create(
        apprenant=user_apprenant.profile,
        categorie="recharge",
        montant=1000,
        operateur="orange_money",
        id_transaction="TX1",
    )

    assert Notification.objects.filter(
        utilisateur=user_service_client, objet_id=demande.id, objet_type="DemandePaiementManuelle"
    ).exists()


@pytest.mark.django_db
def test_decision_paiement_notifie_lapprenant(user_apprenant, user_service_client):
    demande = DemandePaiementManuelle.objects.create(
        apprenant=user_apprenant.profile,
        categorie="recharge",
        montant=1000,
        operateur="orange_money",
        id_transaction="TX2",
    )
    Notification.objects.filter(utilisateur=user_apprenant).delete()

    demande.statut = "validee"
    demande.save(update_fields=["statut"])

    assert Notification.objects.filter(
        utilisateur=user_apprenant, titre="Paiement validé", objet_id=demande.id
    ).exists()


@pytest.mark.django_db
def test_nouvelle_demande_retrait_notifie_service_client(user_enseignant_cadre, user_service_client):
    wallet = YekiWallet.get_or_create_wallet(user_enseignant_cadre)
    wallet.solde = 5000
    wallet.save(update_fields=["solde"])

    demande = DemandeRetrait.objects.create(
        beneficiaire=user_enseignant_cadre.profile,
        montant_brut=2000,
        frais_operateur=0,
        montant_net=2000,
        operateur="orange_money",
        numero_destination="699000000",
    )

    assert Notification.objects.filter(
        utilisateur=user_service_client, objet_id=demande.id, objet_type="DemandeRetrait"
    ).exists()
