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


@pytest.mark.django_db
def test_cadre_round_trip_ne_corrompt_plus_les_champs_absents_du_dashboard(
    client_enseignant_cadre, user_enseignant_cadre, departement
):
    """
    Bug corrigé : `EnseignantCadreDashboardView` ne renvoyait pas
    `acces_restreint`/`niveaux_accessibles` — `departement_form_sheet.dart`
    les réinitialisait alors à `false`/`[]` et les renvoyait quand même à
    chaque sauvegarde, écrasant silencieusement les vraies valeurs. Ce test
    reproduit le round-trip réel : lire le dashboard, PATCH avec les
    valeurs relues (comme le fait le formulaire), vérifier qu'elles
    survivent.
    """
    departement.cadre = user_enseignant_cadre.profile
    departement.acces_restreint = True
    departement.niveaux_accessibles = "terminale,premiere"
    departement.periode = 6
    departement.save()

    dashboard = client_enseignant_cadre.get("/api/enseignant/cadre/dashboard/")
    assert dashboard.status_code == 200, dashboard.data
    dept_data = dashboard.data["departements"][0]
    assert dept_data["acces_restreint"] is True
    assert dept_data["niveaux_accessibles"] == ["terminale", "premiere"]
    assert dept_data["periode"] == 6

    # Le formulaire renvoie exactement ces valeurs relues, plus un
    # changement réel (le nom) — même round-trip que la production.
    reponse = client_enseignant_cadre.patch(
        f"/api/admin/departements/{departement.id}/update/",
        {
            "nom": "Nom changé",
            "acces_restreint": dept_data["acces_restreint"],
            "niveaux_accessibles": dept_data["niveaux_accessibles"],
            "periode": dept_data["periode"],
        },
        format="json",
    )
    assert reponse.status_code == 200, reponse.data

    departement.refresh_from_db()
    assert departement.nom == "Nom changé"
    assert departement.acces_restreint is True
    assert departement.get_niveaux_accessibles_list() == ["terminale", "premiere"]
    assert departement.periode == 6
