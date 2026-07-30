"""
P6.3 : `Choix` vient de gagner un champ `ordre` (défaut 1 pour toutes les
lignes existantes). Cette migration de données attribue un `ordre`
distinct (1, 2, 3…) à chaque `Choix` existant, par question, en se basant
sur son `pk` actuel — l'ordre de lecture d'AVANT ce correctif était déjà
implicitement l'ordre de création (pk croissant), cette migration le
rend simplement explicite et stable au lieu de dépendre du hasard de
l'ordre par défaut de la base.
"""

from django.db import migrations


def backfill_ordre(apps, schema_editor):
    Question = apps.get_model("evaluation", "Question")

    for question in Question.objects.filter(type_question="qcm").iterator():
        for position, choix in enumerate(question.choix.order_by("id"), start=1):
            if choix.ordre != position:
                choix.ordre = position
                choix.save(update_fields=["ordre"])


class Migration(migrations.Migration):
    dependencies = [
        ("evaluation", "0009_choix_ordre"),
    ]

    operations = [
        migrations.RunPython(backfill_ordre, migrations.RunPython.noop),
    ]
