"""
Test P6.3 : GET /api/cours/<id>/exercices/?module_id=<mid> doit renvoyer
Q(module_id=mid) | Q(lecon__module_id=mid) — un exercice rattaché à une
leçon du module doit apparaître, pas seulement ceux rattachés
directement au module. Absence de module_id = aucune contrainte (déjà
correct avant ce ticket, vérifié pour non-régression).
"""

import pytest

from apps.evaluation.models import Exercice
from apps.formation.models import Lecon, Module


@pytest.mark.django_db
def test_filtre_module_inclut_les_exercices_de_lecon(client_apprenant, cours):
    module = Module.objects.create(titre="M1", cours=cours, ordre=1)
    lecon = Lecon.objects.create(titre="L1", cours=cours, module=module, description="D")

    Exercice.objects.create(cours=cours, titre="Direct", enonce="E", etoiles=1, module=module)
    Exercice.objects.create(cours=cours, titre="ViaLecon", enonce="E", etoiles=1, lecon=lecon)
    Exercice.objects.create(cours=cours, titre="HorsModule", enonce="E", etoiles=1)

    reponse = client_apprenant.get(f"/api/cours/{cours.id}/exercices/?module_id={module.id}")

    assert reponse.status_code == 200
    titres = {e["titre"] for e in reponse.data["results"]}
    assert titres == {"Direct", "ViaLecon"}


@pytest.mark.django_db
def test_filtre_tous_retire_toute_contrainte(client_apprenant, cours):
    Exercice.objects.create(cours=cours, titre="A", enonce="E", etoiles=1)
    Exercice.objects.create(cours=cours, titre="B", enonce="E", etoiles=1)

    reponse = client_apprenant.get(f"/api/cours/{cours.id}/exercices/")

    assert reponse.status_code == 200
    assert len(reponse.data["results"]) == 2
