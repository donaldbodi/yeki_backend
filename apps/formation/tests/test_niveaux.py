"""Table Niveau (niveaux du Cameroun) et listes de niveaux exposées par l'API."""

import pytest
from django.urls import reverse

from apps.formation.models import Cours, Niveau


@pytest.mark.django_db
def test_table_pre_remplie_de_la_6eme_au_master_2():
    noms = list(Niveau.objects.values_list("nom", flat=True))
    assert noms[0] == "6ème"
    assert noms[-1] == "Master 2"
    for nom in ("Terminale", "Form 1", "Upper Sixth", "Terminale technique", "Form 5 Technical", "Licence 3"):
        assert nom in noms
    sections = set(Niveau.objects.values_list("section", flat=True))
    assert {"francophone_general", "francophone_technique", "anglophone_general", "anglophone_technique", "superieur"} <= sections


@pytest.mark.django_db
def test_liste_de_reference_dans_l_ordre(client_apprenant, departement):
    Cours.objects.create(titre="Ancien", niveau="Tle C", departement=departement)
    reponse = client_apprenant.get(reverse("liste-niveaux"))
    assert reponse.status_code == 200
    assert reponse.data[0] == "6ème"
    assert reponse.data.index("3ème") < reponse.data.index("Terminale") < reponse.data.index("Licence 1")
    # Un niveau d'ancien cours absent de la table n'est jamais perdu.
    assert "Tle C" in reponse.data


@pytest.mark.django_db
def test_niveaux_d_un_departement_suivent_ses_cours(api_client, departement):
    for niveau in ("Licence 1", "3ème", "Terminale"):
        Cours.objects.create(titre=f"Cours {niveau}", niveau=niveau, departement=departement)
    reponse = api_client.get(f"/api/departements/{departement.id}/niveaux/")
    assert reponse.status_code == 200
    assert reponse.data == ["3ème", "Terminale", "Licence 1"]
