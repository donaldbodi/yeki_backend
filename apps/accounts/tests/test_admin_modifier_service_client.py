"""
Régression : `AdminGeneralModifierEnseignantView` refusait tout compte
`service_client` (400 "Cet utilisateur n'est pas un enseignant."), alors
que `AdminGeneralSearchEnseignantsView` le rend pourtant trouvable depuis
le même onglet (voir test_admin_search_service_client_p2.py) — un compte
Service Client était donc trouvable mais impossible à modifier une fois
trouvé (grade/autorisation).
"""

import pytest


@pytest.mark.django_db
def test_modifier_statut_actif_service_client_reussit(client_admin, user_service_client):
    profile_id = user_service_client.profile.id
    assert user_service_client.profile.is_active is True

    response = client_admin.patch(
        f"/api/admin-general/enseignants/{profile_id}/modifier/",
        {"is_active": False},
        format="json",
    )

    assert response.status_code == 200
    user_service_client.profile.refresh_from_db()
    assert user_service_client.profile.is_active is False


@pytest.mark.django_db
def test_modifier_user_type_service_client_reussit(client_admin, user_service_client):
    profile_id = user_service_client.profile.id

    response = client_admin.patch(
        f"/api/admin-general/enseignants/{profile_id}/modifier/",
        {"user_type": "enseignant"},
        format="json",
    )

    assert response.status_code == 200
    user_service_client.profile.refresh_from_db()
    assert user_service_client.profile.user_type == "enseignant"


@pytest.mark.django_db
def test_modifier_enseignant_classique_reste_fonctionnel(client_admin, user_enseignant):
    """Non-régression : le chemin déjà fonctionnel (enseignant classique)
    n'est pas affecté par l'ajout de service_client aux listes."""
    profile_id = user_enseignant.profile.id

    response = client_admin.patch(
        f"/api/admin-general/enseignants/{profile_id}/modifier/",
        {"user_type": "enseignant_cadre", "is_active": True},
        format="json",
    )

    assert response.status_code == 200
    user_enseignant.profile.refresh_from_db()
    assert user_enseignant.profile.user_type == "enseignant_cadre"


@pytest.mark.django_db
def test_modifier_apprenant_reste_refuse(client_admin, user_apprenant):
    """Non-régression : un apprenant reste hors du périmètre de cette vue
    (seuls les 4 grades enseignant + service_client sont gérables ici)."""
    profile_id = user_apprenant.profile.id

    response = client_admin.patch(
        f"/api/admin-general/enseignants/{profile_id}/modifier/",
        {"is_active": False},
        format="json",
    )

    assert response.status_code == 400
