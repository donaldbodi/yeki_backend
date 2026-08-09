"""
Test : `GET /parcours/<id>/departements/` — bug "clic Parcours ne charge
plus le détail en cascade" (Admin Général). Root cause confirmée :
l'endpoint est paginé (`{count, next, previous, results}`), le frontend
faisait `data as List` (cassé, corrigé séparément) ; deuxième défaut trouvé
en chemin, corrigé ici : `DepartementSerializer` n'exposait pas
`nb_cours`/`nb_apprenants`/`taux_moyen`/`type_departement`, les champs que
chaque carte département affiche.
"""

import pytest

from apps.formation.models import Cours, Lecon, ProgressionLecon


@pytest.mark.django_db
def test_departements_par_parcours_est_paginee(client_admin, parcours, departement):
    reponse = client_admin.get(f"/api/parcours/{parcours.id}/departements/")

    assert reponse.status_code == 200
    assert set(reponse.data.keys()) >= {"count", "next", "previous", "results"}
    assert reponse.data["count"] == 1


@pytest.mark.django_db
def test_departements_par_parcours_expose_les_champs_agreges(client_admin, parcours, departement, user_apprenant):
    cours = Cours.objects.create(
        titre="Cours Test", niveau="Terminale", departement=departement, nb_apprenants=2, nb_lecons=2,
    )
    lecon1 = Lecon.objects.create(titre="Leçon 1", cours=cours, description="")
    Lecon.objects.create(titre="Leçon 2", cours=cours, description="")

    ProgressionLecon.objects.create(apprenant=user_apprenant, cours=cours, lecon=lecon1, terminee=True)

    reponse = client_admin.get(f"/api/parcours/{parcours.id}/departements/")

    assert reponse.status_code == 200
    dept_data = reponse.data["results"][0]
    assert dept_data["nb_cours"] == 1
    assert dept_data["nb_apprenants"] == 2
    assert dept_data["type_departement"] == departement.type_departement
    # 1 leçon terminée sur (2 leçons * 2 apprenants) = 25%.
    assert dept_data["taux_moyen"] == 25.0


@pytest.mark.django_db
def test_departements_par_parcours_sans_cours_taux_moyen_zero(client_admin, parcours, departement):
    reponse = client_admin.get(f"/api/parcours/{parcours.id}/departements/")

    assert reponse.status_code == 200
    dept_data = reponse.data["results"][0]
    assert dept_data["nb_cours"] == 0
    assert dept_data["taux_moyen"] == 0.0
