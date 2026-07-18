"""
Tests P2.1 : Repetiteur.lien_whatsapp (redirection Service Client) et
cascade is_repetiteur=False -> disponible=False (jamais de suppression).
"""

import pytest

from apps.core.models import ParametreSysteme
from apps.repetiteurs.models import Repetiteur


@pytest.mark.django_db
def test_lien_whatsapp_pointe_vers_service_client_pas_enseignant(user_enseignant, cours):
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()

    ParametreSysteme.objects.filter(cle="whatsapp_service_client").update(valeur="237600000000")
    ParametreSysteme.objects.filter(cle="url_base_frontend").update(
        valeur="https://yeki-84b1a.web.app"
    )

    fiche = Repetiteur.objects.create(
        enseignant=user_enseignant.profile,
        cours=cours,
        ville="Yaoundé",
        telephone="237699999999",  # numéro de l'enseignant : ne doit PAS apparaître dans le lien
    )

    lien = fiche.lien_whatsapp

    assert "237600000000" in lien  # numéro du Service Client
    assert "237699999999" not in lien  # jamais le téléphone de l'enseignant
    assert f"profil/{user_enseignant.id}" in lien
    assert "7500" in lien or str(fiche.tarif_mensuel) in lien


@pytest.mark.django_db
def test_lien_whatsapp_sans_numero_configure_ne_plante_pas(user_enseignant, cours):
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()

    fiche = Repetiteur.objects.create(
        enseignant=user_enseignant.profile,
        cours=cours,
        ville="Yaoundé",
        telephone="237699999999",
    )

    # ParametreSysteme vide par défaut (seedé vide en migration) : ne doit
    # jamais lever d'exception, juste produire un lien "vide".
    lien = fiche.lien_whatsapp
    assert lien.startswith("https://wa.me/")


@pytest.mark.django_db
def test_is_repetiteur_false_desactive_les_fiches_sans_les_supprimer(user_enseignant, cours):
    user_enseignant.profile.is_repetiteur = True
    user_enseignant.profile.save()

    fiche = Repetiteur.objects.create(
        enseignant=user_enseignant.profile,
        cours=cours,
        ville="Douala",
        telephone="237699999999",
        disponible=True,
    )

    user_enseignant.profile.is_repetiteur = False
    user_enseignant.profile.save()

    fiche.refresh_from_db()
    assert fiche.disponible is False
    assert Repetiteur.objects.filter(pk=fiche.pk).exists()  # jamais supprimée
