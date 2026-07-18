import logging

from django.db import migrations

logger = logging.getLogger(__name__)

TABLE = "yeki_olympiade"
COLONNES_PRIX = ["prix_1er", "prix_2eme", "prix_3eme"]
LIBELLES = {"prix_1er": "1er prix", "prix_2eme": "2ème prix", "prix_3eme": "3ème prix"}


def _colonnes_presentes(connection, cursor, table, colonnes):
    """
    Introspection portable (SQLite dev, PostgreSQL prod) : `matiere`,
    `niveau`, `prix_1er`, `prix_2eme`, `prix_3eme` ont déjà été retirés du
    modèle Django `Olympiade` (Python commenté) bien avant cette tâche, et
    aucune migration de ce dépôt n'a jamais créé ces colonnes
    (`yeki/migrations/0001_initial.py` les exclut déjà) — la base de dev ne
    les a donc jamais eues. La production tourne sur PostgreSQL, une base
    distincte dont l'historique réel de schéma a pu diverger (squash de
    l'historique de migrations jamais rejoué contre la prod) : elle a
    probablement encore ces colonnes physiquement. On introspecte plutôt
    que de supposer, pour rester correct dans les deux cas.

    Utilise `connection` (= `schema_editor.connection`, passé explicitement,
    jamais le connexion globale par défaut) : sur un projet multi-base, la
    connexion réellement migrée peut différer de `django.db.connection`.
    """
    description = connection.introspection.get_table_description(cursor, table)
    noms_existants = {col.name for col in description}
    return [c for c in colonnes if c in noms_existants]


def fusionner_prix_dans_recompense(apps, schema_editor):
    """
    P2.5 : avant suppression des colonnes prix_1er/prix_2eme/prix_3eme
    (migration 0005 suivante), concatène leur contenu éventuel dans
    `recompense` (qui devient du HTML enrichi), pour ne rien perdre. Ne
    fait rien si les colonnes n'existent déjà pas (cas confirmé de la base
    de dev).
    """
    if schema_editor.connection.vendor not in ("sqlite", "postgresql"):
        logger.warning(
            "P2.5 : moteur de base non testé (%s) — migration de données "
            "ignorée par prudence, à rejouer manuellement si nécessaire.",
            schema_editor.connection.vendor,
        )
        return

    with schema_editor.connection.cursor() as cursor:
        presentes = _colonnes_presentes(schema_editor.connection, cursor, TABLE, COLONNES_PRIX)

        if not presentes:
            logger.info(
                "P2.5 : colonnes %s déjà absentes de %s — migration de "
                "données no-op.",
                COLONNES_PRIX,
                TABLE,
            )
            return

        colonnes_select = ", ".join(["id", "recompense"] + presentes)
        cursor.execute(f"SELECT {colonnes_select} FROM {TABLE}")
        lignes = cursor.fetchall()

        nb_touchees = 0
        nb_ignorees = 0
        for ligne in lignes:
            valeurs = dict(zip(["id", "recompense"] + presentes, ligne))
            olympiade_id = valeurs["id"]
            recompense_actuelle = valeurs["recompense"] or ""

            fragments = []
            for col in presentes:
                contenu = (valeurs.get(col) or "").strip()
                if contenu:
                    fragments.append(f"<li>{LIBELLES[col]} : {contenu}</li>")

            if not fragments:
                nb_ignorees += 1
                continue

            nouveau_bloc = "<ul>" + "".join(fragments) + "</ul>"
            nouvelle_recompense = (
                f"{recompense_actuelle}\n{nouveau_bloc}" if recompense_actuelle else nouveau_bloc
            )

            cursor.execute(
                f"UPDATE {TABLE} SET recompense = %s WHERE id = %s"
                if schema_editor.connection.vendor == "postgresql"
                else f"UPDATE {TABLE} SET recompense = ? WHERE id = ?",
                [nouvelle_recompense, olympiade_id],
            )
            nb_touchees += 1
            logger.info(
                "P2.5 : Olympiade id=%s — prix fusionnés dans recompense.",
                olympiade_id,
            )

        logger.info(
            "P2.5 : fusion prix→recompense terminée sur %s — %s ligne(s) "
            "modifiée(s), %s ligne(s) sans contenu prix (ignorées).",
            TABLE,
            nb_touchees,
            nb_ignorees,
        )


def revert_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("evaluation", "0003_alter_devoir_enonces_supplementaires_enoncedevoir_and_more"),
    ]

    operations = [
        migrations.RunPython(fusionner_prix_dans_recompense, revert_noop),
    ]
