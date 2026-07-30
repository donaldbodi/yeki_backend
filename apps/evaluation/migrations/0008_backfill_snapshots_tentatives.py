"""
P6.2 : les `ExerciceTentative` créées AVANT ce correctif n'ont que les
réponses brutes de l'apprenant (`{question_id: texte}`), pas de snapshot
auto-suffisant. Cette migration de données reconstruit, pour CES lignes
uniquement, un snapshot au nouveau format en rejouant la correction contre
l'état ACTUEL des `Question`/`Choix` de l'exercice (décision actée avec
l'utilisateur, AskUserQuestion) — la meilleure approximation possible,
mais PAS une garantie d'exactitude historique parfaite si l'exercice a
déjà été modifié depuis la tentative concernée. Toute tentative créée à
partir de la mise en production de ce correctif sera, elle, parfaitement
fidèle (snapshot figé au moment même de la soumission).

Irréversible : reconstituer le format brut d'origine ferait perdre le
snapshot sans rien apporter (l'ancien format était déjà, lui, une
approximation à usage unique).
"""

from django.db import migrations


def backfill_snapshots(apps, schema_editor):
    ExerciceTentative = apps.get_model("evaluation", "ExerciceTentative")
    Question = apps.get_model("evaluation", "Question")

    for tentative in ExerciceTentative.objects.select_related("exercice").iterator():
        reponses = tentative.reponses or {}
        if isinstance(reponses, dict) and "questions" in reponses:
            continue  # déjà au nouveau format (créée après ce correctif)

        questions_par_id = {
            q.id: q for q in Question.objects.filter(exercice=tentative.exercice)
        }
        details = []
        for question_id_str, reponse_brute in reponses.items():
            if not str(question_id_str).isdigit():
                continue
            question = questions_par_id.get(int(question_id_str))
            if not question:
                continue  # question supprimée depuis : rien à reconstruire

            reponse_normalisee = (reponse_brute or "").strip().lower()
            if question.type_question == "qcm":
                choix_selectionne = question.choix.filter(
                    texte__iexact=reponse_normalisee
                ).first()
                est_correct = bool(choix_selectionne and choix_selectionne.est_correct)
                choix_snapshot = [
                    {"id": c.id, "texte": c.texte, "est_correct": c.est_correct}
                    for c in question.choix.all()
                ]
            else:
                est_correct = reponse_normalisee == (question.bonne_reponse or "").strip().lower()
                choix_snapshot = []

            details.append(
                {
                    "question_id": question.id,
                    "enonce_snapshot": question.text,
                    "type": question.type_question,
                    "choix_snapshot": choix_snapshot,
                    "reponse_apprenant": reponse_normalisee,
                    "bonne_reponse": question.bonne_reponse,
                    "est_correct": est_correct,
                    "points_obtenus": question.points if est_correct else 0,
                    "points_max": question.points,
                    "explication": getattr(question, "explication", "") or "",
                }
            )

        date_iso = tentative.date_tentative.isoformat() if tentative.date_tentative else None
        tentative.reponses = {
            "questions": details,
            "score": tentative.score,
            "total": tentative.total_points,
            "date": date_iso,
        }
        tentative.save(update_fields=["reponses"])


class Migration(migrations.Migration):
    dependencies = [
        ("evaluation", "0007_question_explication"),
    ]

    operations = [
        migrations.RunPython(backfill_snapshots, migrations.RunPython.noop),
    ]
