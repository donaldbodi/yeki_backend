"""
Rectification (demande explicite) : l'abonnement Premium est désormais
PAR DÉPARTEMENT — `AbonnementPremium.departement` — au lieu d'un abonnement
global unique. Ces tests couvrent spécifiquement l'isolation entre
départements (un abonnement dans A ne donne pas accès à B), le repli sur
la règle globale pour le contenu sans département résolvable, et le statut
retourné par `StatutAbonnementView`.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.services import AccesService
from apps.evaluation.models import Devoir, Exercice
from apps.formation.models import Cours, Departement, Parcours
from apps.paiement.models import AbonnementPremium


@pytest.fixture
def autre_departement(db):
    parcours = Parcours.objects.create(nom="Cursus Autre", type_parcours="cursus")
    return Departement.objects.create(nom="Autre Département", parcours=parcours)


@pytest.fixture
def autre_cours(db, autre_departement):
    return Cours.objects.create(titre="Autre Cours", niveau="Terminale", departement=autre_departement)


@pytest.fixture
def abonnement_departement(db, user_apprenant, departement):
    return AbonnementPremium.objects.create(
        utilisateur=user_apprenant,
        departement=departement,
        type_abonnement="mensuel",
        actif=True,
        fin=timezone.now() + timedelta(days=30),
    )


@pytest.mark.django_db
def test_premium_dans_son_departement_donne_acces(user_apprenant, departement, devoir, abonnement_departement):
    assert AccesService.est_premium(user_apprenant, departement) is True
    assert AccesService.peut_voir(user_apprenant, devoir) is True


@pytest.mark.django_db
def test_premium_dans_un_departement_ne_donne_pas_acces_a_un_autre(
    user_apprenant, autre_departement, autre_cours, abonnement_departement
):
    devoir_autre = Devoir.objects.create(
        titre="Devoir Autre",
        enonce="…",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=autre_cours,
        est_publie=True,
    )
    assert AccesService.est_premium(user_apprenant, autre_departement) is False
    assert AccesService.peut_voir(user_apprenant, devoir_autre) is False


@pytest.mark.django_db
def test_devoir_sans_departement_resolvable_retombe_sur_regle_globale(
    user_apprenant, departement, abonnement_departement
):
    """Un devoir lié à une olympiade (`cours_lie=None`) n'a pas de
    département résolvable — le filet de sécurité (« premium dans
    N'IMPORTE QUEL département ») s'applique, pas un refus par défaut."""
    devoir_olympiade = Devoir.objects.create(
        titre="Devoir Olympiade",
        enonce="…",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=None,
        est_publie=True,
        type_devoir="olympiade",
    )
    assert AccesService.peut_voir(user_apprenant, devoir_olympiade) is True


@pytest.mark.django_db
def test_exercice_2_etoiles_visible_dans_departement_premium_seulement(
    user_apprenant, departement, cours, autre_departement, autre_cours, abonnement_departement
):
    ex_ici = Exercice.objects.create(cours=cours, titre="Ex ici", enonce="…", etoiles=3)
    ex_ailleurs = Exercice.objects.create(cours=autre_cours, titre="Ex ailleurs", enonce="…", etoiles=3)
    assert AccesService.peut_voir(user_apprenant, ex_ici) is True
    assert AccesService.peut_voir(user_apprenant, ex_ailleurs) is False


@pytest.mark.django_db
def test_statut_abonnement_view_departement_sans_prix_indisponible(client_apprenant, cours):
    response = client_apprenant.get(reverse("abonnement-statut"), {"cours_id": cours.id})
    assert response.status_code == 200
    data = response.json()
    assert data["disponible"] is False
    assert data["actif"] is False
    assert data["departement_id"] == cours.departement_id


@pytest.mark.django_db
def test_statut_abonnement_view_departement_avec_prix_disponible(client_apprenant, cours, departement):
    departement.prix_mensuel = 1500
    departement.prix_annuel = 13000
    departement.save()
    response = client_apprenant.get(reverse("abonnement-statut"), {"cours_id": cours.id})
    assert response.status_code == 200
    data = response.json()
    assert data["disponible"] is True
    assert data["prix_mensuel"] == 1500
    assert data["prix_annuel"] == 13000


@pytest.mark.django_db
def test_statut_abonnement_view_reflete_abonnement_actif(
    client_apprenant, user_apprenant, cours, departement, abonnement_departement
):
    response = client_apprenant.get(reverse("abonnement-statut"), {"cours_id": cours.id})
    assert response.status_code == 200
    data = response.json()
    assert data["actif"] is True
    assert data["type_abonnement"] == "mensuel"


@pytest.mark.django_db
def test_statut_abonnement_view_sans_cours_id_rejete(client_apprenant):
    response = client_apprenant.get(reverse("abonnement-statut"))
    assert response.status_code == 400
