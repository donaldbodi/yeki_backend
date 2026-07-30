"""
Tests P9.1 : AccesMatricePermission — la permission_class dédiée qui
délègue à AccesService (aucune vue ne réimplémente la matrice).
"""

import pytest
from rest_framework.views import APIView

from apps.core.permissions import AccesMatricePermission
from apps.evaluation.models import Devoir, Exercice


class _Requete:
    def __init__(self, user):
        self.user = user


class _VueSansModele(APIView):
    pass


class _VueDevoirVoir(APIView):
    acces_modele = Devoir
    acces_action = "voir"


class _VueExerciceSoumettre(APIView):
    acces_modele = Exercice
    acces_action = "soumettre"


@pytest.mark.django_db
def test_has_permission_sans_acces_modele_autorise_toujours(user_apprenant):
    permission = AccesMatricePermission()
    assert permission.has_permission(_Requete(user_apprenant), _VueSansModele()) is True


@pytest.mark.django_db
def test_has_permission_devoir_bloque_gratuit(user_apprenant):
    permission = AccesMatricePermission()
    assert permission.has_permission(_Requete(user_apprenant), _VueDevoirVoir()) is False


@pytest.mark.django_db
def test_has_object_permission_exercice_utilise_linstance_pas_seulement_la_classe(
    user_apprenant, exercice
):
    """exercice (fixture conftest) a etoiles=1 → soumissible même en
    gratuit, alors que has_permission(classe nue) ne pourrait pas trancher
    aussi finement."""
    permission = AccesMatricePermission()
    vue = _VueExerciceSoumettre()
    assert permission.has_permission(_Requete(user_apprenant), vue) is True
    assert permission.has_object_permission(_Requete(user_apprenant), vue, exercice) is True


@pytest.mark.django_db
def test_has_object_permission_exercice_2_etoiles_bloque_soumission_gratuit(user_apprenant, cours):
    permission = AccesMatricePermission()
    vue = _VueExerciceSoumettre()
    ex_2 = Exercice.objects.create(cours=cours, titre="Ex 2★", enonce="…", etoiles=2)
    assert permission.has_object_permission(_Requete(user_apprenant), vue, ex_2) is False
