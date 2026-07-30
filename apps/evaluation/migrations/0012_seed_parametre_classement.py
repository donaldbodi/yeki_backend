"""
P6.3 : seed des poids de classement. Progression NON LINÉAIRE entre les
étoiles (proposition actée) — un 5★ vaut bien plus que 5 fois un 1★.
`olympiade`/`devoir` sont semés pour être prêts (le devoir doit toujours
rester le poids le plus élevé) mais ne sont consommés par aucun calcul
dans ce ticket (décision actée, hors périmètre).

Modifiable ensuite sans redéploiement (admin Django) — c'est tout le
sens de stocker ces valeurs en base plutôt qu'en dur.
"""

from django.db import migrations

POIDS = {
    "etoile_1": 1,
    "etoile_2": 2,
    "etoile_3": 4,
    "etoile_4": 7,
    "etoile_5": 11,
    "olympiade": 15,
    "devoir": 20,
}


def seed_poids(apps, schema_editor):
    ParametreClassement = apps.get_model("evaluation", "ParametreClassement")
    for source, poids in POIDS.items():
        ParametreClassement.objects.get_or_create(source=source, defaults={"poids": poids})


def supprimer_poids(apps, schema_editor):
    ParametreClassement = apps.get_model("evaluation", "ParametreClassement")
    ParametreClassement.objects.filter(source__in=POIDS.keys()).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("evaluation", "0011_parametre_classement"),
    ]

    operations = [
        migrations.RunPython(seed_poids, supprimer_poids),
    ]
