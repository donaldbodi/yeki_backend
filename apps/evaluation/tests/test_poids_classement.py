"""
Test P6.3 : le classement pondère les points selon l'étoile de
l'exercice, poids lus depuis `ParametreClassement` — jamais en dur.
Progression volontairement non linéaire (un 5★ vaut bien plus que 5× un
1★).
"""

import pytest

from apps.evaluation.models import EvaluationExercice, Exercice, ParametreClassement
from apps.evaluation.services import ClassementService


@pytest.mark.django_db
def test_score_departement_applique_les_poids_de_parametreclassement(
    user_apprenant, departement, cours
):
    # Poids volontairement différents des valeurs semées par défaut, pour
    # prouver qu'ils sont bien lus en base et non en dur dans le code.
    ParametreClassement.objects.filter(source="etoile_1").update(poids=10)
    ParametreClassement.objects.filter(source="etoile_5").update(poids=100)

    exo_1etoile = Exercice.objects.create(cours=cours, titre="1e", enonce="E", etoiles=1)
    exo_5etoiles = Exercice.objects.create(cours=cours, titre="5e", enonce="E", etoiles=5)
    EvaluationExercice.objects.create(user=user_apprenant, exercice=exo_1etoile, score=2.0, total=2.0)
    EvaluationExercice.objects.create(user=user_apprenant, exercice=exo_5etoiles, score=3.0, total=3.0)

    score = ClassementService.score_departement(user_apprenant, departement)

    assert score == 2.0 * 10 + 3.0 * 100  # 320 — pas 5.0 (somme brute pré-P6.3)


@pytest.mark.django_db
def test_progression_non_lineaire_5_etoiles_vaut_bien_plus_que_5x_1_etoile():
    poids = ClassementService.poids_par_etoile()

    assert poids[5] > 5 * poids[1]
