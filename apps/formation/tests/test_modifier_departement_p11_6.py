"""
Test P11.6 : régression sur le bug "modification de département ne
fonctionne pas" — remonté par le ticket Phase 11, diagnostiqué comme un
conflit de type sur `niveaux_accessibles` entre `AdminUpdateDepartementView`
(qui joignait la liste en chaîne avant validation) et
`DepartementUpdateSerializer` (dont le champ est un `ListField`, qui rejette
toute chaîne — y compris `""` — avant même de regarder son contenu). Le
bug se déclenchait sur quasi tout PATCH réel, `niveaux_accessibles` étant
envoyé par l'écran de modification à chaque sauvegarde.
"""

import pytest

from apps.core.models import ParametreSysteme
from apps.formation.models import Departement
from apps.formation.services import niveaux_formation_disponibles


@pytest.mark.django_db
def test_modifier_departement_avec_niveaux_accessibles_reussit(client_enseignant_admin, user_enseignant_admin, parcours, departement):
    parcours.admin = user_enseignant_admin.profile
    parcours.save()

    reponse = client_enseignant_admin.patch(
        f"/api/admin/departements/{departement.id}/update/",
        {
            "nom": "Département modifié",
            "description": "Nouvelle description",
            "niveaux_accessibles": ["Terminale", "Premiere"],
        },
        format="json",
    )

    assert reponse.status_code == 200, reponse.data
    departement.refresh_from_db()
    assert departement.nom == "Département modifié"
    # `get_niveaux_accessibles_list()` normalise en minuscules (comportement
    # du modèle, sans rapport avec ce bug) — voir `est_accessible_par_niveau`.
    assert departement.get_niveaux_accessibles_list() == ["terminale", "premiere"]


@pytest.mark.django_db
def test_modifier_departement_avec_niveaux_accessibles_vide_reussit(client_enseignant_admin, user_enseignant_admin, parcours, departement):
    """Cas explicitement cité dans le bug : vider la liste (tout niveau
    accessible) plantait aussi, `[]` étant tout autant rejeté par le
    `ListField` une fois joint en `""` avant validation."""
    parcours.admin = user_enseignant_admin.profile
    parcours.save()

    reponse = client_enseignant_admin.patch(
        f"/api/admin/departements/{departement.id}/update/",
        {"niveaux_accessibles": []},
        format="json",
    )

    assert reponse.status_code == 200, reponse.data
    departement.refresh_from_db()
    assert departement.get_niveaux_accessibles_list() == []


@pytest.mark.django_db
def test_modifier_departement_sans_niveaux_accessibles_reussit(client_enseignant_admin, user_enseignant_admin, parcours, departement):
    """N'envoyer aucun champ `niveaux_accessibles` (PATCH partiel classique)
    fonctionnait déjà avant le correctif — vérifie l'absence de régression."""
    parcours.admin = user_enseignant_admin.profile
    parcours.save()

    reponse = client_enseignant_admin.patch(
        f"/api/admin/departements/{departement.id}/update/",
        {"nom": "Autre nom"},
        format="json",
    )

    assert reponse.status_code == 200, reponse.data
    departement.refresh_from_db()
    assert departement.nom == "Autre nom"


@pytest.mark.django_db
def test_niveaux_formation_disponibles_valeur_par_defaut():
    niveaux = niveaux_formation_disponibles()
    assert [n["code"] for n in niveaux] == ["debutant", "intermediaire", "avance"]
    assert niveaux[0]["label"] == "Débutant"


@pytest.mark.django_db
def test_niveaux_formation_disponibles_administrable_sans_redeploiement():
    """Le cœur de l'arbitrage P11.6 : ajouter un niveau ne doit demander
    qu'une modification de `ParametreSysteme` (admin Django), jamais une
    modification de code ni un redéploiement."""
    ParametreSysteme.objects.create(
        cle="niveaux_formation_disponibles",
        valeur="debutant:Débutant,intermediaire:Intermédiaire,avance:Avancé,expert:Expert",
        type="string",
    )
    assert [n["code"] for n in niveaux_formation_disponibles()] == [
        "debutant", "intermediaire", "avance", "expert",
    ]


@pytest.mark.django_db
def test_liste_niveaux_formation_endpoint(client_enseignant):
    reponse = client_enseignant.get("/api/niveaux-formation/")
    assert reponse.status_code == 200
    assert reponse.data == niveaux_formation_disponibles()


@pytest.mark.django_db
def test_modifier_departement_niveau_formation_invalide_rejete(client_enseignant_admin, user_enseignant_admin, parcours, departement):
    parcours.type_parcours = "formation"
    parcours.save()
    parcours.admin = user_enseignant_admin.profile
    parcours.save()
    departement.est_formation_metier = True
    departement.save()

    reponse = client_enseignant_admin.patch(
        f"/api/admin/departements/{departement.id}/update/",
        {"est_formation_metier": True, "niveau_formation": "inexistant"},
        format="json",
    )

    assert reponse.status_code == 400
