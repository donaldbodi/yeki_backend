"""
Tests P2.5 : nettoyage des champs abandonnés de Olympiade (matiere, niveau,
prix_1er, prix_2eme, prix_3eme) — régression directe sur les bugs
confirmés (AttributeError sur CadreOlympiadesView, perte silencieuse sur
CadreModifierOlympiadeView, doublon cassé sur le dashboard admin général).

Rectification ultérieure : la suppression des 3 routes admin de
validation (décision produit actée ici à l'origine) a été EXPLICITEMENT
INVERSÉE par l'utilisateur — la validation est rétablie (voir
`AdminOlympiadesAValiderView`/`AdminValiderOlympiadeView`/
`AdminRefuserOlympiadeView`, `apps/evaluation/views/olympiades.py`).
`test_routes_admin_validation_supprimees` (qui vérifiait leur ABSENCE) a
donc été remplacé par son inverse ci-dessous — le reste de ce fichier
(nettoyage des champs abandonnés) reste valide et inchangé.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.evaluation.models import Olympiade


@pytest.fixture
def olympiade_du_cadre(user_enseignant_cadre):
    now = timezone.now()
    return Olympiade.objects.create(
        titre="Olympiade Cadre Test",
        edition="2026-1",
        date_ouverture_inscription=now - timedelta(days=1),
        date_cloture_inscription=now + timedelta(days=1),
        date_debut_olympiade=now + timedelta(days=2),
        date_fin_olympiade=now + timedelta(days=3),
        organisateur=user_enseignant_cadre.profile,
        recompense="Certificats.",
    )


@pytest.mark.django_db
def test_cadre_olympiades_ne_plante_plus(client_enseignant_cadre, olympiade_du_cadre):
    """
    Régression : CadreOlympiadesView lisait o.matiere/o.niveau/o.prix_1er
    (champs supprimés du modèle) → AttributeError non rattrapée → 500
    systématique dès qu'une olympiade existait pour le cadre connecté.
    """
    response = client_enseignant_cadre.get(reverse("cadre-olympiades"))
    assert response.status_code == status.HTTP_200_OK
    resultat = response.data["results"][0]
    assert "matiere" not in resultat
    assert "niveau" not in resultat
    assert "prix_1er" not in resultat
    assert "prix_2eme" not in resultat
    assert "prix_3eme" not in resultat


@pytest.mark.django_db
def test_modifier_olympiade_ignore_champs_abandonnes(client_enseignant_cadre, olympiade_du_cadre):
    """
    Régression : matiere/niveau/prix_1er envoyés dans le body étaient
    silencieusement acceptés par `setattr` (attribut Python ordinaire, pas
    un champ modèle) et jamais persistés — le 200 renvoyé incluait
    pourtant ces clés dans "modifications", laissant croire à tort que la
    donnée avait été sauvegardée. Désormais ignorées, absentes de
    "modifications", sans erreur.
    """
    response = client_enseignant_cadre.patch(
        reverse("modifier-olympiade", args=[olympiade_du_cadre.id]),
        {
            "matiere": "Maths",
            "niveau": "Terminale",
            "prix_1er": "Tablette",
            "prix_2eme": "Livres",
            "prix_3eme": "Certificat",
            "titre": "Nouveau titre",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    assert "matiere" not in response.data["modifications"]
    assert "niveau" not in response.data["modifications"]
    assert "prix_1er" not in response.data["modifications"]
    assert "titre" in response.data["modifications"]

    olympiade_du_cadre.refresh_from_db()
    assert olympiade_du_cadre.titre == "Nouveau titre"


@pytest.mark.django_db
def test_liste_olympiades_ignore_filtres_matiere_niveau(client_apprenant):
    """
    Régression : `qs.filter(matiere=...)`/`qs.filter(niveau=...)` levaient
    FieldError (champs absents du modèle) si ces query params étaient
    envoyés. Ces filtres sont retirés — la requête ne doit plus planter.
    """
    response = client_apprenant.get(
        reverse("liste-olympiades"), {"matiere": "Maths", "niveau": "Terminale"}
    )
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_routes_admin_validation_retablies():
    """
    Rectification : la décision de supprimer la validation admin a été
    inversée — ces 3 routes doivent exister à nouveau dans le urlconf
    (comportement fonctionnel testé séparément, `test_validation_olympiades.py`).
    """
    assert reverse("admin-olympiades-a-valider")
    assert reverse("admin-valider-olympiade", args=[1])
    assert reverse("admin-refuser-olympiade", args=[1])


@pytest.mark.django_db
def test_dashboard_admin_ne_renvoie_plus_olympiades_en_attente(
    client_enseignant_admin, user_enseignant_admin, user_enseignant_cadre, departement
):
    """
    Régression : le dashboard admin général dupliquait la même logique
    qu'AdminOlympiadesAValiderView (o.matiere/o.niveau) — même crash
    potentiel, même fonctionnalité désormais supprimée. Le endpoint ne
    doit plus planter et ne doit plus exposer cette liste.
    """
    parcours = departement.parcours
    parcours.admin = user_enseignant_admin.profile
    parcours.save()
    departement.cadre = user_enseignant_cadre.profile
    departement.save()

    now = timezone.now()
    Olympiade.objects.create(
        titre="Olympiade en attente",
        edition="2026-1",
        date_ouverture_inscription=now - timedelta(days=1),
        date_cloture_inscription=now + timedelta(days=1),
        date_debut_olympiade=now + timedelta(days=2),
        date_fin_olympiade=now + timedelta(days=3),
        organisateur=user_enseignant_cadre.profile,
    )

    response = client_enseignant_admin.get(reverse("enseignant-admin-dashboard"))
    assert response.status_code == status.HTTP_200_OK
    assert "olympiades_en_attente" not in response.data
    assert "nb_olympiades_attente" not in response.data["stats"]
