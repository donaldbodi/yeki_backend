"""
Aucun test n'existait pour `PrincipalDashboardAPIView`/
`PrincipalApprenantsCoursAPIView` avant ce ticket (trou de couverture
confirmé) — c'est ce qui a permis à un vrai bug de passer inaperçu :
`Devoir.objects.filter(cours__in=cours_ids)` référençait un champ
inexistant sur `Devoir` (seul `cours_lie` existe) — une `FieldError`
systématique dès qu'AU MOINS UN apprenant réel existait pour ce
principal (le compte de démo sans apprenant inscrit ne déclenchait
jamais cette ligne). Corrigé dans la réécriture ORM de la vue — ces
tests couvrent le cas réel (avec apprenant + soumission) qui aurait
immédiatement révélé le bug.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.evaluation.models import Devoir, SoumissionDevoir


@pytest.fixture
def cours_du_principal(db, departement, user_enseignant_principal):
    from apps.formation.models import Cours

    return Cours.objects.create(
        titre="Cours du principal",
        niveau="Terminale",
        departement=departement,
        enseignant_principal=user_enseignant_principal.profile,
    )


@pytest.mark.django_db
def test_dashboard_sans_cours_renvoie_des_donnees_vides(client_enseignant_principal):
    response = client_enseignant_principal.get(reverse("principal-dashboard-stats"))
    assert response.status_code == 200
    data = response.json()
    assert data["stats"]["nb_cours"] == 0
    assert data["devoirs_par_cours"] == []
    assert data["apprenants_risque"] == []


@pytest.mark.django_db
def test_dashboard_avec_apprenant_reel_ne_plante_plus(
    client_enseignant_principal, cours_du_principal, parcours, user_apprenant
):
    """
    Bug confirmé et corrigé : avant ce ticket, cette requête levait un
    `FieldError` (500) dès qu'un apprenant réel matchait le parcours du
    cours — jamais couvert par un test, donc jamais détecté.
    """
    user_apprenant.profile.cursus = parcours.nom
    user_apprenant.profile.save(update_fields=["cursus"])
    devoir = Devoir.objects.create(
        titre="Devoir 1",
        enonce="Énoncé.",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_du_principal,
        est_publie=True,
    )

    response = client_enseignant_principal.get(reverse("principal-dashboard-stats"))
    assert response.status_code == 200
    data = response.json()
    assert data["stats"]["nb_cours"] == 1
    assert data["stats"]["nb_devoirs"] == 1
    assert data["stats"]["nb_apprenants"] == 1
    # L'apprenant n'a encore rien rendu — 0% de rendu, apparaît en risque.
    assert len(data["apprenants_risque"]) == 1
    assert data["apprenants_risque"][0]["email"] == user_apprenant.email
    assert len(data["devoirs_par_cours"]) == 1
    assert data["devoirs_par_cours"][0]["cours_id"] == cours_du_principal.id
    assert data["devoirs_par_cours"][0]["nb_devoirs"] == 1
    assert data["devoirs_par_cours"][0]["details_devoirs"][0]["id"] == devoir.id


@pytest.mark.django_db
def test_dashboard_agregats_corrects_apres_soumission(
    client_enseignant_principal, cours_du_principal, parcours, user_apprenant
):
    user_apprenant.profile.cursus = parcours.nom
    user_apprenant.profile.save(update_fields=["cursus"])
    devoir = Devoir.objects.create(
        titre="Devoir 1",
        enonce="Énoncé.",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_du_principal,
        est_publie=True,
    )
    SoumissionDevoir.objects.create(
        utilisateur=user_apprenant,
        devoir=devoir,
        statut="corrige",
        soumis_le=timezone.now(),
        note=15,
    )

    response = client_enseignant_principal.get(reverse("principal-dashboard-stats"))
    assert response.status_code == 200
    data = response.json()
    assert data["stats"]["taux_rendu_global"] == 100.0
    assert data["stats"]["moyenne_globale"] == 15.0
    assert data["stats"]["nb_retards"] == 0
    # Taux de rendu 100% pour cet unique devoir : plus "à risque" (<50%).
    assert data["apprenants_risque"] == []
    details = data["devoirs_par_cours"][0]["details_devoirs"][0]
    assert details["nb_rendus"] == 1
    assert details["note_moyenne"] == 15.0


@pytest.mark.django_db
def test_apprenants_cours_avec_apprenant_reel(
    client_enseignant_principal, cours_du_principal, parcours, user_apprenant
):
    user_apprenant.profile.cursus = parcours.nom
    user_apprenant.profile.save(update_fields=["cursus"])
    devoir = Devoir.objects.create(
        titre="Devoir 1",
        enonce="Énoncé.",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours_du_principal,
        est_publie=True,
    )
    SoumissionDevoir.objects.create(
        utilisateur=user_apprenant, devoir=devoir, statut="soumis", soumis_le=timezone.now(), note=12
    )

    response = client_enseignant_principal.get(
        reverse("principal-apprenants-cours"), {"cours_id": cours_du_principal.id}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["email"] == user_apprenant.email
    assert data[0]["taux_rendu"] == 100.0
    assert data[0]["moyenne"] == 12.0
