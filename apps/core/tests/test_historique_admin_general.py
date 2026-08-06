"""
Régression : `HistoriqueActiviteView.CATEGORIES["enseignants"]` listait
les codes d'action d'une fonctionnalité différente (enseignant principal
gérant ses enseignants secondaires) — jamais ceux réellement émis par
l'Admin Général (`teacher_activated`/`teacher_deactivated`/
`teacher_type_changed`/`teacher_modified`, apps/accounts/views/
admin_enseignants.py). Le filtre "Enseignants" renvoyait donc toujours
une liste vide pour l'admin général alors que `enregistrer_activite()`
écrit bien ces lignes — reproduit ici de bout en bout (une vraie action
admin, puis une vraie requête de lecture de l'historique), pas juste un
test unitaire du dictionnaire de catégories.
"""

import pytest


@pytest.mark.django_db
def test_modification_enseignant_apparait_dans_historique_categorie_enseignants(
    client_admin, user_enseignant
):
    # Une vraie action Admin Général — déclenche enregistrer_activite(action="teacher_modified", ...).
    profile_id = user_enseignant.profile.id
    reponse_modif = client_admin.patch(
        f"/api/admin-general/enseignants/{profile_id}/modifier/",
        {"user_type": "enseignant_cadre"},
        format="json",
    )
    assert reponse_modif.status_code == 200

    reponse_historique = client_admin.get("/api/historique/", {"category": "enseignants"})
    assert reponse_historique.status_code == 200
    actions = [r["action"] for r in reponse_historique.data["results"]]
    assert "teacher_modified" in actions


@pytest.mark.django_db
def test_activation_enseignant_apparait_dans_historique_categorie_enseignants(
    client_admin, user_enseignant
):
    # AdminGeneralActiverEnseignantView exige un compte inactif au départ.
    user_enseignant.profile.is_active = False
    user_enseignant.profile.save(update_fields=["is_active"])

    profile_id = user_enseignant.profile.id
    reponse_activation = client_admin.post(f"/api/admin-general/enseignants/{profile_id}/activer/")
    assert reponse_activation.status_code == 200

    reponse_historique = client_admin.get("/api/historique/", {"category": "enseignants"})
    assert reponse_historique.status_code == 200
    actions = [r["action"] for r in reponse_historique.data["results"]]
    assert "teacher_activated" in actions
