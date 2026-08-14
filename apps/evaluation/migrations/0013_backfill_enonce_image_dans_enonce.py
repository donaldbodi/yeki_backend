"""
Rectification (demande explicite) : `Exercice.enonce` (texte simple) +
`Exercice.enonce_image` (champ fichier séparé) fusionnés en un champ
`enonce` unique, riche (HTML), même mécanisme que
`EnonceDevoir.contenu`/`YkRichEditor` — les images sont désormais
insérées inline par l'éditeur, plus de champ image à part.

Aucune perte de données (règle 5) : pour chaque `Exercice` ayant déjà une
`enonce_image`, une balise `<img>` référençant ce fichier est ajoutée à
la fin de son `enonce` (préserve le rendu visuel existant tel quel,
`YkRichViewer` — déjà utilisé côté lecture apprenant — l'affichera
normalement). Le champ `enonce_image` lui-même N'EST PAS supprimé du
modèle (conservé, déprécié, pour compatibilité descendante — même
précédent que `Devoir.enonce`) — seuls les serializers de
création/modification ont cessé de l'exposer en écriture.
"""

from django.db import migrations


def backfill_enonce_image(apps, schema_editor):
    Exercice = apps.get_model("evaluation", "Exercice")

    for exercice in Exercice.objects.exclude(enonce_image="").iterator():
        if not exercice.enonce_image:
            continue
        try:
            url = exercice.enonce_image.url
        except ValueError:
            # Fichier référencé en base mais absent du stockage — rien à
            # migrer visuellement, ne pas planter la migration pour autant.
            continue
        balise = f'<img src="{url}" alt="Illustration de l\'énoncé" />'
        if balise not in (exercice.enonce or ""):
            exercice.enonce = f"{exercice.enonce or ''}\n{balise}"
            exercice.save(update_fields=["enonce"])


class Migration(migrations.Migration):
    dependencies = [
        ("evaluation", "0012_seed_parametre_classement"),
    ]

    operations = [
        migrations.RunPython(backfill_enonce_image, migrations.RunPython.noop),
    ]
