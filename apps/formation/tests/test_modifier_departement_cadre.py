"""
Test : le cadre peut désormais modifier le département qu'il gère
(demande explicite — cette capacité n'existait auparavant que pour le
coordonnateur, `AdminUpdateDepartementView` rejetait tout autre rôle avec
un 403). Non-régression sur le comportement du coordonnateur, et sur le
rejet d'un cadre tentant de modifier un département qui n'est pas le
sien.
"""

import pytest


@pytest.mark.django_db
def test_cadre_modifie_son_propre_departement_reussit(client_enseignant_cadre, user_enseignant_cadre, departement):
    departement.cadre = user_enseignant_cadre.profile
    departement.save()

    reponse = client_enseignant_cadre.patch(
        f"/api/admin/departements/{departement.id}/update/",
        {"nom": "Département modifié par le cadre", "description": "Nouvelle description"},
        format="json",
    )

    assert reponse.status_code == 200, reponse.data
    departement.refresh_from_db()
    assert departement.nom == "Département modifié par le cadre"


@pytest.mark.django_db
def test_cadre_ne_peut_pas_modifier_un_autre_departement(client_enseignant_cadre, departement):
    # `departement.cadre` reste `None` (pas assigné à ce cadre).
    reponse = client_enseignant_cadre.patch(
        f"/api/admin/departements/{departement.id}/update/",
        {"nom": "Tentative non autorisée"},
        format="json",
    )

    assert reponse.status_code == 403


@pytest.mark.django_db
def test_coordonnateur_toujours_autorise_apres_le_correctif(client_enseignant_admin, user_enseignant_admin, parcours, departement):
    """Non-régression : le comportement du coordonnateur (déjà couvert par
    test_modifier_departement_p11_6.py) reste inchangé après l'ajout du cas
    cadre."""
    parcours.admin = user_enseignant_admin.profile
    parcours.save()

    reponse = client_enseignant_admin.patch(
        f"/api/admin/departements/{departement.id}/update/",
        {"nom": "Modifié par le coordonnateur"},
        format="json",
    )

    assert reponse.status_code == 200, reponse.data


@pytest.mark.django_db
def test_apprenant_rejete(client_apprenant, departement):
    reponse = client_apprenant.patch(
        f"/api/admin/departements/{departement.id}/update/",
        {"nom": "Tentative apprenant"},
        format="json",
    )

    assert reponse.status_code == 403
