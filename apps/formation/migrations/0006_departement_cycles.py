from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("formation", "0005_alter_cours_color_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="departement",
            name="cycle_date_debut",
            field=models.DateField(
                blank=True,
                help_text="Début du premier cycle. Vide pour un département créé avant les cycles.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="departement",
            name="cycle_duree_mois",
            field=models.PositiveSmallIntegerField(
                default=12, help_text="Durée d'un cycle, en mois (1 à 12)"
            ),
        ),
        migrations.AddField(
            model_name="departement",
            name="cycle_nombre",
            field=models.PositiveSmallIntegerField(
                default=1, help_text="Nombre de cycles par an (au plus 12 // durée du cycle)"
            ),
        ),
        migrations.AddField(
            model_name="departement",
            name="cycle_placement",
            field=models.CharField(
                choices=[("suite", "À la suite"), ("repartis", "Répartis sur l'année")],
                default="suite",
                help_text="Cycles à la suite, ou répartis régulièrement sur l'année",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="departement",
            name="periode",
            field=models.PositiveIntegerField(
                default=6,
                help_text="Durée d'une période de classement en mois (= durée du cycle)",
            ),
        ),
        migrations.AlterField(
            model_name="departement",
            name="prix_annuel",
            field=models.PositiveIntegerField(
                default=0, help_text="Prix de l'abonnement sur le cycle, en ligne (FCFA)"
            ),
        ),
    ]
