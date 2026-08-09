"""
Rétablissement de la validation admin des olympiades (rectification —
l'utilisateur revient sur la décision produit qui avait supprimé ce
mécanisme, voir `test_nettoyage_olympiades.py`). Couvre le cycle complet :
création en attente → invisible des apprenants → coordonnateur
valide/refuse → visibilité mise à jour. Vérifie aussi le correctif
découvert en restaurant ce flux : `CadreModifierOlympiadeView` bloquait la
modification EN PERMANENCE (dès que le devoir lié existait, ce qui est
toujours vrai depuis la création) — seul `est_validee` doit désormais
bloquer.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.evaluation.models import Olympiade


def _payload_olympiade(departement):
    now = timezone.now()
    return {
        "titre": "Olympiade Test",
        "departement_id": departement.id,
        "date_ouverture_inscription": (now - timedelta(days=1)).isoformat(),
        "date_cloture_inscription": (now + timedelta(hours=12)).isoformat(),
        "date_debut_olympiade": (now + timedelta(days=2)).isoformat(),
        "duree_minutes": 120,
    }


@pytest.mark.django_db
def test_creation_par_cadre_reste_en_attente(client_enseignant_cadre, user_enseignant_cadre, departement):
    departement.cadre = user_enseignant_cadre.profile
    departement.save()

    reponse = client_enseignant_cadre.post(
        "/api/olympiades/cadre/creer/", _payload_olympiade(departement), format="json"
    )

    assert reponse.status_code == 201, reponse.data
    olympiade = Olympiade.objects.get(pk=reponse.data["id"])
    assert olympiade.est_validee is False
    assert olympiade.est_refusee is False
    assert "attente" in reponse.data["detail"]


@pytest.mark.django_db
def test_olympiade_en_attente_invisible_pour_apprenant(
    client_enseignant_cadre, user_enseignant_cadre, client_apprenant, departement
):
    departement.cadre = user_enseignant_cadre.profile
    departement.save()
    creation = client_enseignant_cadre.post(
        "/api/olympiades/cadre/creer/", _payload_olympiade(departement), format="json"
    )
    assert creation.status_code == 201, creation.data

    reponse = client_apprenant.get(reverse("liste-olympiades"))
    assert reponse.status_code == 200
    titres = {o["titre"] for o in reponse.data["results"]}
    assert "Olympiade Test" not in titres


@pytest.mark.django_db
def test_cadre_peut_encore_modifier_avant_validation(
    client_enseignant_cadre, user_enseignant_cadre, departement
):
    """Bug corrigé découvert en restaurant ce flux : le blocage "devoir déjà
    lié" rendait la modification impossible dès la création (le devoir est
    TOUJOURS lié immédiatement), indépendamment de la validation."""
    departement.cadre = user_enseignant_cadre.profile
    departement.save()
    creation = client_enseignant_cadre.post(
        "/api/olympiades/cadre/creer/", _payload_olympiade(departement), format="json"
    )
    olympiade_id = creation.data["id"]

    reponse = client_enseignant_cadre.patch(
        reverse("modifier-olympiade", args=[olympiade_id]),
        {"prix_participation": 250},
        format="json",
    )
    assert reponse.status_code == 200, reponse.data
    olympiade = Olympiade.objects.get(pk=olympiade_id)
    assert olympiade.prix_participation == 250


@pytest.mark.django_db
def test_coordonnateur_liste_les_olympiades_en_attente(
    client_enseignant_admin, user_enseignant_admin, client_enseignant_cadre, user_enseignant_cadre, parcours, departement
):
    parcours.admin = user_enseignant_admin.profile
    parcours.save()
    departement.cadre = user_enseignant_cadre.profile
    departement.save()
    creation = client_enseignant_cadre.post(
        "/api/olympiades/cadre/creer/", _payload_olympiade(departement), format="json"
    )
    assert creation.status_code == 201, creation.data

    reponse = client_enseignant_admin.get(reverse("admin-olympiades-a-valider"))
    assert reponse.status_code == 200, reponse.data
    resultats = reponse.data["results"]
    assert len(resultats) == 1
    assert resultats[0]["statut_validation"] == "attente"
    assert resultats[0]["cadre"]["id"] == user_enseignant_cadre.profile.id


@pytest.mark.django_db
def test_coordonnateur_valide_rend_visible_et_notifie(
    client_enseignant_admin, user_enseignant_admin, client_enseignant_cadre, user_enseignant_cadre,
    client_apprenant, parcours, departement,
):
    parcours.admin = user_enseignant_admin.profile
    parcours.save()
    departement.cadre = user_enseignant_cadre.profile
    departement.save()
    creation = client_enseignant_cadre.post(
        "/api/olympiades/cadre/creer/", _payload_olympiade(departement), format="json"
    )
    olympiade_id = creation.data["id"]

    reponse = client_enseignant_admin.post(reverse("admin-valider-olympiade", args=[olympiade_id]))
    assert reponse.status_code == 200, reponse.data

    olympiade = Olympiade.objects.get(pk=olympiade_id)
    assert olympiade.est_validee is True
    assert olympiade.validee_le is not None

    liste = client_apprenant.get(reverse("liste-olympiades"))
    titres = {o["titre"] for o in liste.data["results"]}
    assert "Olympiade Test" in titres


@pytest.mark.django_db
def test_coordonnateur_refuse_avec_motif(
    client_enseignant_admin, user_enseignant_admin, client_enseignant_cadre, user_enseignant_cadre, parcours, departement
):
    parcours.admin = user_enseignant_admin.profile
    parcours.save()
    departement.cadre = user_enseignant_cadre.profile
    departement.save()
    creation = client_enseignant_cadre.post(
        "/api/olympiades/cadre/creer/", _payload_olympiade(departement), format="json"
    )
    olympiade_id = creation.data["id"]

    reponse = client_enseignant_admin.post(
        reverse("admin-refuser-olympiade", args=[olympiade_id]), {"motif": "Dates incohérentes."}, format="json"
    )
    assert reponse.status_code == 200, reponse.data

    olympiade = Olympiade.objects.get(pk=olympiade_id)
    assert olympiade.est_refusee is True
    assert olympiade.est_validee is False
    assert olympiade.motif_refus == "Dates incohérentes."


@pytest.mark.django_db
def test_cadre_ne_peut_plus_modifier_une_fois_validee(
    client_enseignant_admin, user_enseignant_admin, client_enseignant_cadre, user_enseignant_cadre, parcours, departement
):
    parcours.admin = user_enseignant_admin.profile
    parcours.save()
    departement.cadre = user_enseignant_cadre.profile
    departement.save()
    creation = client_enseignant_cadre.post(
        "/api/olympiades/cadre/creer/", _payload_olympiade(departement), format="json"
    )
    olympiade_id = creation.data["id"]
    client_enseignant_admin.post(reverse("admin-valider-olympiade", args=[olympiade_id]))

    reponse = client_enseignant_cadre.patch(
        reverse("modifier-olympiade", args=[olympiade_id]), {"prix_participation": 300}, format="json"
    )
    assert reponse.status_code == 400


@pytest.mark.django_db
def test_admin_general_et_apprenant_rejetes_des_vues_coordonnateur(client_admin, client_apprenant):
    for client in (client_admin, client_apprenant):
        assert client.get(reverse("admin-olympiades-a-valider")).status_code == 403
        assert client.post(reverse("admin-valider-olympiade", args=[1])).status_code == 403


@pytest.mark.django_db
def test_coordonnateur_dun_autre_parcours_ne_voit_pas(
    client_enseignant_admin, user_enseignant_admin, client_enseignant_cadre, user_enseignant_cadre, departement
):
    """Le coordonnateur connecté n'a AUCUN parcours assigné (`departement`
    appartient à un parcours différent, sans admin) — doit être rejeté."""
    departement.cadre = user_enseignant_cadre.profile
    departement.save()
    creation = client_enseignant_cadre.post(
        "/api/olympiades/cadre/creer/", _payload_olympiade(departement), format="json"
    )
    olympiade_id = creation.data["id"]

    reponse = client_enseignant_admin.get(reverse("admin-olympiades-a-valider"))
    assert reponse.status_code == 404

    reponse = client_enseignant_admin.post(reverse("admin-valider-olympiade", args=[olympiade_id]))
    assert reponse.status_code == 404
