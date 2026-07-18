"""
Tests P2.2 : validation anti-cycle sur Exercice.exercices_composes, et
correction du bug de modification d'épreuve (PATCH partiel qui ne renvoie
pas est_epreuve sautait silencieusement la vérification).
"""

import pytest
from django.core.exceptions import ValidationError

from apps.evaluation.models import Exercice
from apps.evaluation.serializers import ExerciceCreateSerializer
from apps.evaluation.validators import valider_pas_de_cycle_epreuve


@pytest.fixture
def exercice_a(cours):
    return Exercice.objects.create(cours=cours, titre="A", enonce="EA", etoiles=1)


@pytest.fixture
def exercice_b(cours):
    return Exercice.objects.create(cours=cours, titre="B", enonce="EB", etoiles=1)


@pytest.mark.django_db
def test_auto_reference_directe_leve(exercice_a):
    with pytest.raises(ValidationError):
        valider_pas_de_cycle_epreuve(exercice_a, [exercice_a])


@pytest.mark.django_db
def test_cycle_transitif_leve(exercice_a, exercice_b):
    """A compose B ; si B veut ensuite composer A → cycle."""
    exercice_a.exercices_composes.add(exercice_b)
    with pytest.raises(ValidationError):
        valider_pas_de_cycle_epreuve(exercice_b, [exercice_a])


@pytest.mark.django_db
def test_pas_de_cycle_ne_leve_pas(exercice_a, exercice_b):
    valider_pas_de_cycle_epreuve(exercice_a, [exercice_b])  # ne doit pas lever


@pytest.mark.django_db
def test_creation_sans_instance_ne_verifie_pas_cycle():
    """À la création (instance=None), aucun cycle n'est possible."""
    valider_pas_de_cycle_epreuve(None, [])  # ne doit pas lever


@pytest.mark.django_db
def test_patch_partiel_sans_est_epreuve_verifie_quand_meme(exercice_a):
    """
    Bug confirmé (P2.2) : un PATCH partiel qui ne renvoie pas `est_epreuve`
    sur une épreuve déjà existante sautait silencieusement la vérification
    « au moins un exercice ». Doit maintenant toujours s'appliquer.
    """
    exercice_a.est_epreuve = True
    exercice_a.save(update_fields=["est_epreuve"])

    serializer = ExerciceCreateSerializer(
        exercice_a, data={"enonce": "Nouvel énoncé"}, partial=True
    )
    assert not serializer.is_valid()
    assert "exercices_composes" in serializer.errors


@pytest.mark.django_db
def test_patch_ajoutant_un_cycle_est_refuse(exercice_a, exercice_b):
    exercice_a.exercices_composes.add(exercice_b)
    exercice_a.est_epreuve = True
    exercice_a.save(update_fields=["est_epreuve"])

    serializer = ExerciceCreateSerializer(
        exercice_b,
        data={"enonce": "E", "est_epreuve": True, "exercices_composes": [exercice_a.id]},
        partial=True,
    )
    assert not serializer.is_valid()
    assert "exercices_composes" in serializer.errors
