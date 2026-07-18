"""
Validateurs partagés pour l'app evaluation (P2.2).
"""

from django.core.exceptions import ValidationError

PAS_POINTS = 0.25
TOLERANCE = 1e-9


def valider_pas_de_0_25(value):
    """
    Les points doivent être un multiple de 0.25 (ex: 0.25, 0.5, 1, 1.75...).
    Tolérance flottante pour éviter les faux négatifs d'arrondi binaire.
    """
    reste = round(value / PAS_POINTS) * PAS_POINTS
    if abs(value - reste) > TOLERANCE:
        raise ValidationError(
            f"Les points doivent être un multiple de {PAS_POINTS} (ex : 0.25, 0.5, 1, 1.75…).",
            code="pas_invalide",
        )


def valider_pas_de_cycle_epreuve(instance, candidats):
    """
    Empêche qu'une épreuve se contienne elle-même, directement ou
    transitivement, via `Exercice.exercices_composes`.

    `instance` : l'exercice en cours de modification (None à la création —
    aucun cycle possible tant que l'objet n'existe pas encore).
    `candidats` : itérable d'instances `Exercice` proposées comme composants.

    Lève `ValidationError` au premier candidat problématique.
    """
    if instance is None or instance.pk is None:
        return

    for candidat in candidats:
        if candidat.pk == instance.pk:
            raise ValidationError(
                f"Une épreuve ne peut pas se contenir elle-même (« {candidat.titre} »).",
                code="auto_reference",
            )
        if _contient_transitivement(candidat, instance.pk):
            raise ValidationError(
                f"Cycle détecté : « {candidat.titre} » contient déjà (directement ou "
                "indirectement) cette épreuve — l'ajouter créerait une boucle.",
                code="cycle",
            )


def _contient_transitivement(exercice, cible_pk, visites=None):
    """DFS : True si `cible_pk` est atteignable depuis `exercice.exercices_composes`."""
    if visites is None:
        visites = set()
    if exercice.pk in visites:
        return False
    visites.add(exercice.pk)

    for composant in exercice.exercices_composes.all():
        if composant.pk == cible_pk:
            return True
        if _contient_transitivement(composant, cible_pk, visites):
            return True
    return False
