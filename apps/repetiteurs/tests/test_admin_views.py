"""
Tests P9.5 : administration des répétiteurs par le Service Client (bascule
is_repetiteur, création/édition/suppression de fiches Repetiteur) —
n'existait pas avant ce ticket. Vérifie aussi la régression du bug déjà
documenté (tarif hardcodé à 5000 dans RepetiteursSearchView).
"""

import pytest
from django.urls import reverse

from apps.accounts.models import Profile
from apps.core.models import ParametreSysteme
from apps.repetiteurs.models import Repetiteur


# ── Toggle ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_toggle_403_si_non_service_client(client_apprenant, user_enseignant):
    response = client_apprenant.patch(
        reverse("repetiteurs-admin-toggle", args=[user_enseignant.profile.id]),
        {"is_repetiteur": True},
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_toggle_400_si_valeur_absente(client_service_client, user_enseignant):
    response = client_service_client.patch(
        reverse("repetiteurs-admin-toggle", args=[user_enseignant.profile.id]), {}, format="json"
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_toggle_active_le_profil(client_service_client, user_enseignant):
    response = client_service_client.patch(
        reverse("repetiteurs-admin-toggle", args=[user_enseignant.profile.id]),
        {"is_repetiteur": True},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["is_repetiteur"] is True

    user_enseignant.profile.refresh_from_db()
    assert user_enseignant.profile.is_repetiteur is True


@pytest.mark.django_db
def test_toggle_desactive_declenche_la_cascade_existante(client_service_client, user_enseignant, cours):
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()
    fiche = Repetiteur.objects.create(
        enseignant=user_enseignant.profile, cours=cours, ville="Douala",
        telephone="237699999999", disponible=True,
    )

    response = client_service_client.patch(
        reverse("repetiteurs-admin-toggle", args=[user_enseignant.profile.id]),
        {"is_repetiteur": False},
        format="json",
    )
    assert response.status_code == 200

    fiche.refresh_from_db()
    assert fiche.disponible is False  # signal existant (apps/accounts/signals.py)
    assert Repetiteur.objects.filter(pk=fiche.pk).exists()  # jamais supprimée


# ── Candidats ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_candidats_403_si_non_service_client(client_apprenant):
    response = client_apprenant.get(reverse("repetiteurs-admin-candidats"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_candidats_liste_avec_fiches_imbriquees(client_service_client, user_enseignant, cours):
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()
    Repetiteur.objects.create(
        enseignant=user_enseignant.profile, cours=cours, ville="Douala", telephone="237699999999"
    )

    response = client_service_client.get(reverse("repetiteurs-admin-candidats"), {"is_repetiteur": "true"})
    assert response.status_code == 200
    candidats = response.data["candidats"]
    assert len(candidats) == 1
    assert candidats[0]["is_repetiteur"] is True
    assert len(candidats[0]["fiches"]) == 1
    assert candidats[0]["fiches"][0]["ville"] == "Douala"


# ── Fiches — création ────────────────────────────────────────────────


@pytest.mark.django_db
def test_creer_fiche_400_si_enseignant_pas_encore_valide(client_service_client, user_enseignant, cours):
    assert user_enseignant.profile.is_repetiteur is False
    response = client_service_client.post(
        reverse("repetiteurs-admin-fiches"),
        {
            "enseignant": user_enseignant.profile.id,
            "cours": cours.id,
            "ville": "Douala",
            "telephone": "237699999999",
        },
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_creer_fiche_ok(client_service_client, user_enseignant, cours):
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()

    response = client_service_client.post(
        reverse("repetiteurs-admin-fiches"),
        {
            "enseignant": user_enseignant.profile.id,
            "cours": cours.id,
            "ville": "Douala",
            "telephone": "237699999999",
            "tarif_mensuel": 8000,
        },
        format="json",
    )
    assert response.status_code == 201
    assert Repetiteur.objects.filter(
        enseignant=user_enseignant.profile, cours=cours, tarif_mensuel=8000
    ).exists()


# ── Fiches — édition / suppression ──────────────────────────────────


@pytest.mark.django_db
def test_editer_ville_et_tarif(client_service_client, user_enseignant, cours):
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()
    fiche = Repetiteur.objects.create(
        enseignant=user_enseignant.profile, cours=cours, ville="Douala", telephone="237699999999"
    )

    response = client_service_client.patch(
        reverse("repetiteurs-admin-fiche-detail", args=[fiche.id]),
        {"ville": "Yaoundé", "tarif_mensuel": 9000},
        format="json",
    )
    assert response.status_code == 200

    fiche.refresh_from_db()
    assert fiche.ville == "Yaoundé"
    assert fiche.tarif_mensuel == 9000


@pytest.mark.django_db
def test_retirer_dun_cours_supprime_la_fiche(client_service_client, user_enseignant, cours):
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()
    fiche = Repetiteur.objects.create(
        enseignant=user_enseignant.profile, cours=cours, ville="Douala", telephone="237699999999"
    )

    response = client_service_client.delete(
        reverse("repetiteurs-admin-fiche-detail", args=[fiche.id])
    )
    assert response.status_code == 204
    assert not Repetiteur.objects.filter(pk=fiche.id).exists()


# ── Régression : recherche apprenant reflète la fiche, plus 5000 en dur ─


@pytest.mark.django_db
def test_recherche_apprenant_utilise_le_tarif_de_la_fiche(
    client_apprenant, user_enseignant, cours
):
    cours.enseignant_principal = user_enseignant.profile
    cours.matiere = "Maths"
    cours.save(update_fields=["enseignant_principal", "matiere"])
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()
    Repetiteur.objects.create(
        enseignant=user_enseignant.profile, cours=cours, ville="Bafoussam",
        telephone="237699999999", tarif_mensuel=12000,
    )

    response = client_apprenant.get(reverse("repetiteurs-search"), {"matiere": "Maths"})
    assert response.status_code == 200
    assert response.data["total"] == 1
    resultat = response.data["repetiteurs"][0]
    assert resultat["tarif"] == 12000  # plus jamais 5000
    assert resultat["ville"] == "Bafoussam"


@pytest.mark.django_db
def test_recherche_apprenant_utilise_le_parametre_systeme_sans_fiche(
    client_apprenant, user_enseignant, cours
):
    ParametreSysteme.objects.filter(cle="tarif_repetiteur_mensuel").update(valeur="6500")
    cours.enseignant_principal = user_enseignant.profile
    cours.matiere = "Physique"
    cours.save(update_fields=["enseignant_principal", "matiere"])
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()

    response = client_apprenant.get(reverse("repetiteurs-search"), {"matiere": "Physique"})
    assert response.status_code == 200
    assert response.data["total"] == 1
    assert response.data["repetiteurs"][0]["tarif"] == 6500  # plus jamais 5000


@pytest.mark.django_db
def test_recherche_apprenant_exclut_fiche_marquee_indisponible(
    client_apprenant, user_enseignant, cours
):
    cours.enseignant_principal = user_enseignant.profile
    cours.matiere = "Chimie"
    cours.save(update_fields=["enseignant_principal", "matiere"])
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()
    Repetiteur.objects.create(
        enseignant=user_enseignant.profile, cours=cours, ville="Douala",
        telephone="237699999999", disponible=False,
    )

    response = client_apprenant.get(reverse("repetiteurs-search"), {"matiere": "Chimie"})
    assert response.status_code == 200
    assert response.data["total"] == 0
