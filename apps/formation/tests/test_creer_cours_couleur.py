"""
Bug corrigé : `COURSE_COLOR_PALETTE` (backend) divergeait de
`YkCourseColors.palette` (frontend, seule source consultée par
`YkColorPicker`) — `color_code` échouait donc TOUJOURS la validation
`choices=`, quelle que soit la couleur choisie par le cadre à la
création d'un cours. Confirme le nouveau contrat : une couleur de la
palette synchronisée réussit, une couleur de l'ancienne palette (périmée)
échoue explicitement.
"""

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_creer_cours_avec_couleur_synchronisee_reussit(
    client_enseignant_cadre, user_enseignant_cadre, departement
):
    departement.cadre = user_enseignant_cadre.profile
    departement.save(update_fields=["cadre"])

    reponse = client_enseignant_cadre.post(
        reverse("cours-create"),
        {
            "titre": "Algèbre Linéaire",
            "niveau": "Terminale",
            "departement": departement.id,
            "color_code": "#2E7CAD",  # Azur — 1ère couleur de YkCourseColors.palette
            "icon_name": "calculate",
        },
        format="json",
    )

    assert reponse.status_code == 201, reponse.data
    assert reponse.data["color_code"] == "#2E7CAD"


@pytest.mark.django_db
def test_creer_cours_avec_ancienne_couleur_perimee_echoue(
    client_enseignant_cadre, user_enseignant_cadre, departement
):
    """L'ancienne palette (avant synchronisation) n'est plus acceptée —
    documente explicitement le changement de contrat plutôt que de le
    laisser échouer silencieusement à l'avenir."""
    departement.cadre = user_enseignant_cadre.profile
    departement.save(update_fields=["cadre"])

    reponse = client_enseignant_cadre.post(
        reverse("cours-create"),
        {
            "titre": "Algèbre Linéaire",
            "niveau": "Terminale",
            "departement": departement.id,
            "color_code": "#2563EB",  # ancien code "Bleu Roi", plus dans la palette
            "icon_name": "calculate",
        },
        format="json",
    )

    assert reponse.status_code == 400
    assert "color_code" in reponse.data.get("error", {}).get("fields", reponse.data)
