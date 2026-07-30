# Généré à la main (pas par makemigrations) — P11.9, rituel P5.0.
#
# `SupplementCours.cours` devient obligatoire (arbitrage tranché avec
# l'utilisateur : rattaché au cours en premier, à la leçon en option),
# alors que `lecon` était jusqu'ici la seule FK et restait, elle,
# obligatoire — inverse de l'arbitrage retenu.
#
# Migration en 3 étapes (règle 5 : ne rien perdre) plutôt qu'un simple
# `AddField(default=None)` généré par `makemigrations` (qui échouerait
# net sur toute ligne existante dans un environnement où la table ne
# serait pas vide, contrairement à la base de dev locale confirmée à 0
# ligne) :
#   1. Ajoute `cours` en NULLABLE + rend `lecon` NULLABLE.
#   2. Rétro-remplit `cours` depuis `lecon.module.cours` pour toute ligne
#      existante qui aurait une leçon exploitable.
#   3. Rend `cours` obligatoire — n'échoue que s'il reste des lignes
#      sans cours dérivable (leçon sans module), cas qui n'existe pas
#      aujourd'hui (aucune vue/serializer ne permettait d'en créer avant
#      ce ticket) mais qu'on ne suppose pas silencieusement.

import django.db.models.deletion
from django.db import migrations, models


def retro_remplir_cours(apps, schema_editor):
    # `Lecon.cours` est une FK directe et obligatoire (pas seulement via
    # `Lecon.module`, nullable, comme supposé dans une première version de
    # cette fonction) — toujours disponible pour toute leçon existante.
    # Boucle plutôt qu'un `.update(cours=F("lecon__cours"))` : Django
    # n'autorise pas les `F()` traversant une relation dans `.update()`.
    SupplementCours = apps.get_model("formation", "SupplementCours")
    for supplement in SupplementCours.objects.filter(cours__isnull=True, lecon__isnull=False):
        supplement.cours_id = supplement.lecon.cours_id
        supplement.save(update_fields=["cours"])


def sans_retour_arriere(apps, schema_editor):
    # Rien à défaire : `cours` redevient simplement NULLABLE dans le
    # `AlterField` suivant en cas de reverse — pas de perte de données.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("formation", "0003_alter_departement_niveau_formation"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplementcours",
            name="cours",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="supplements",
                to="formation.cours",
            ),
        ),
        migrations.AlterField(
            model_name="supplementcours",
            name="lecon",
            field=models.ForeignKey(
                blank=True,
                help_text="Facultatif — si renseigné, le supplément n'apparaît que sur cette leçon.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="supplements",
                to="formation.lecon",
            ),
        ),
        migrations.AlterField(
            model_name="supplementcours",
            name="type_contenu",
            field=models.CharField(
                choices=[("lien", "Lien"), ("pdf", "PDF"), ("ppt", "PowerPoint"), ("autre", "Autre")],
                max_length=20,
            ),
        ),
        migrations.RunPython(retro_remplir_cours, sans_retour_arriere),
        migrations.AlterField(
            model_name="supplementcours",
            name="cours",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="supplements",
                to="formation.cours",
            ),
        ),
    ]
