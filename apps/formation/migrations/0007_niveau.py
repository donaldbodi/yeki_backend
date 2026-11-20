"""
Table Niveau, pré-remplie avec les niveaux du Cameroun, de la 6ème au
Master 2 : sections francophone et anglophone, enseignement général et
technique, puis supérieur. Les noms « 2nde », « 1ère », « Terminale »,
« Licence 1 »… sont ceux déjà utilisés par les cours existants.
"""

from django.db import migrations, models

NIVEAUX = [
    # Francophone — enseignement général
    ("6ème", "francophone_general"),
    ("5ème", "francophone_general"),
    ("4ème", "francophone_general"),
    ("3ème", "francophone_general"),
    ("2nde", "francophone_general"),
    ("1ère", "francophone_general"),
    ("Terminale", "francophone_general"),
    # Francophone — enseignement technique
    ("1ère année (technique)", "francophone_technique"),
    ("2ème année (technique)", "francophone_technique"),
    ("3ème année (technique)", "francophone_technique"),
    ("4ème année (technique)", "francophone_technique"),
    ("2nde technique", "francophone_technique"),
    ("1ère technique", "francophone_technique"),
    ("Terminale technique", "francophone_technique"),
    # Anglophone — general education
    ("Form 1", "anglophone_general"),
    ("Form 2", "anglophone_general"),
    ("Form 3", "anglophone_general"),
    ("Form 4", "anglophone_general"),
    ("Form 5", "anglophone_general"),
    ("Lower Sixth", "anglophone_general"),
    ("Upper Sixth", "anglophone_general"),
    # Anglophone — technical education
    ("Form 1 Technical", "anglophone_technique"),
    ("Form 2 Technical", "anglophone_technique"),
    ("Form 3 Technical", "anglophone_technique"),
    ("Form 4 Technical", "anglophone_technique"),
    ("Form 5 Technical", "anglophone_technique"),
    ("Lower Sixth Technical", "anglophone_technique"),
    ("Upper Sixth Technical", "anglophone_technique"),
    # Enseignement supérieur
    ("BTS 1", "superieur"),
    ("BTS 2", "superieur"),
    ("HND 1", "superieur"),
    ("HND 2", "superieur"),
    ("Licence 1", "superieur"),
    ("Licence 2", "superieur"),
    ("Licence 3", "superieur"),
    ("Master 1", "superieur"),
    ("Master 2", "superieur"),
]


def remplir(apps, schema_editor):
    Niveau = apps.get_model("formation", "Niveau")
    for ordre, (nom, section) in enumerate(NIVEAUX, start=1):
        Niveau.objects.update_or_create(nom=nom, defaults={"section": section, "ordre": ordre * 10})


class Migration(migrations.Migration):
    dependencies = [
        ("formation", "0006_departement_cycles"),
    ]

    operations = [
        migrations.CreateModel(
            name="Niveau",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=60, unique=True)),
                (
                    "section",
                    models.CharField(
                        choices=[
                            ("francophone_general", "Francophone — enseignement général"),
                            ("francophone_technique", "Francophone — enseignement technique"),
                            ("anglophone_general", "Anglophone — general education"),
                            ("anglophone_technique", "Anglophone — technical education"),
                            ("superieur", "Enseignement supérieur"),
                        ],
                        max_length=30,
                    ),
                ),
                ("ordre", models.PositiveSmallIntegerField(help_text="Position dans les listes (croissant)")),
                ("actif", models.BooleanField(default=True)),
            ],
            options={"db_table": "yeki_niveau", "ordering": ["ordre", "nom"]},
        ),
        migrations.RunPython(remplir, migrations.RunPython.noop),
    ]
