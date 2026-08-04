"""
Régression : `AdminGeneralSearchEnseignantsView` omettait `service_client`
de sa liste de `user_type` autorisés (queryset ET filtre) — un compte
Service Client n'apparaissait jamais dans la recherche de l'admin
général, empêchant de le retrouver pour lui assigner ce rôle.
"""

import pytest


@pytest.mark.django_db
def test_service_client_apparait_dans_la_recherche_sans_filtre(client_admin, user_service_client):
    response = client_admin.get("/api/admin-general/enseignants/search/")
    assert response.status_code == 200
    ids = [e["id"] for e in response.data["results"]]
    assert user_service_client.profile.id in ids


@pytest.mark.django_db
def test_filtre_user_type_service_client_fonctionne(client_admin, user_service_client, user_enseignant):
    response = client_admin.get(
        "/api/admin-general/enseignants/search/", {"user_type": "service_client"}
    )
    assert response.status_code == 200
    ids = [e["id"] for e in response.data["results"]]
    assert user_service_client.profile.id in ids
    assert user_enseignant.profile.id not in ids
