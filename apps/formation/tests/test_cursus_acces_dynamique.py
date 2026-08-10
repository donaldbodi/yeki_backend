"""
Rectification (demande explicite) : `ApprenantCursusAPIView` (GET
/api/apprenant/cursus/) calcule désormais un vrai `est_accessible` par
cours (dérivé du département, même critère que `Departement.
acces_restreint`/`apprenants_autorises`) au lieu de laisser le frontend
figer `isPremium` à `true` en dur (`cursus_page.dart`).
"""

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_cours_cursus_accessible_par_defaut(client_apprenant, user_apprenant, parcours, cours):
    user_apprenant.profile.cursus = parcours.nom
    user_apprenant.profile.save(update_fields=["cursus"])

    response = client_apprenant.get(reverse("apprenant-cursus"))
    assert response.status_code == 200
    resultats = response.json()["results"]
    assert len(resultats) == 1
    assert resultats[0]["departement_id"] == cours.departement_id
    assert resultats[0]["est_accessible"] is True


@pytest.mark.django_db
def test_cours_cursus_departement_restreint_inaccessible(
    client_apprenant, user_apprenant, parcours, departement, cours
):
    departement.acces_restreint = True
    departement.save(update_fields=["acces_restreint"])
    user_apprenant.profile.cursus = parcours.nom
    user_apprenant.profile.save(update_fields=["cursus"])

    response = client_apprenant.get(reverse("apprenant-cursus"))
    assert response.status_code == 200
    resultats = response.json()["results"]
    assert resultats[0]["est_accessible"] is False


@pytest.mark.django_db
def test_cours_cursus_departement_restreint_mais_autorise(
    client_apprenant, user_apprenant, parcours, departement, cours
):
    departement.acces_restreint = True
    departement.save(update_fields=["acces_restreint"])
    departement.apprenants_autorises.add(user_apprenant)
    user_apprenant.profile.cursus = parcours.nom
    user_apprenant.profile.save(update_fields=["cursus"])

    response = client_apprenant.get(reverse("apprenant-cursus"))
    assert response.status_code == 200
    resultats = response.json()["results"]
    assert resultats[0]["est_accessible"] is True
