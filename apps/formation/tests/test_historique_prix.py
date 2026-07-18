"""
Tests P2.4 : HistoriquePrixDepartement — alimenté automatiquement par un
signal quand prix/prix_presentiel changent, jamais pour un autre champ
(portée volontairement limitée aux champs prix, seule motivation donnée
par le CDC : rendre la règle « promotion » calculable).
"""

import pytest

from apps.formation.models import HistoriquePrixDepartement


@pytest.mark.django_db
def test_changement_de_prix_cree_une_ligne_historique(departement):
    ancien_prix = departement.prix
    departement.prix = ancien_prix + 500
    departement.save()

    historique = HistoriquePrixDepartement.objects.filter(departement=departement)
    assert historique.count() == 1
    ligne = historique.first()
    assert ligne.champ == "prix"
    assert ligne.ancienne_valeur == ancien_prix
    assert ligne.nouvelle_valeur == ancien_prix + 500


@pytest.mark.django_db
def test_baisse_de_prix_est_bien_le_referent_de_la_promotion(departement):
    departement.prix = 1000
    departement.save()
    departement.prix = 700  # baisse -> "promotion"
    departement.save()

    dernier = HistoriquePrixDepartement.objects.filter(
        departement=departement, champ="prix"
    ).latest("date")
    assert dernier.nouvelle_valeur < dernier.ancienne_valeur


@pytest.mark.django_db
def test_changement_dun_autre_champ_ne_cree_aucune_ligne(departement):
    departement.nom = "Nouveau nom"
    departement.save()

    assert HistoriquePrixDepartement.objects.filter(departement=departement).count() == 0


@pytest.mark.django_db
def test_creation_du_departement_ne_cree_aucune_ligne(parcours):
    from apps.formation.models import Departement

    nouveau = Departement.objects.create(nom="Neuf", parcours=parcours, prix=500)
    assert HistoriquePrixDepartement.objects.filter(departement=nouveau).count() == 0
