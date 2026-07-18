import logging

from django.db import migrations

logger = logging.getLogger(__name__)

TABLE = "yeki_olympiade"
COLONNES_A_SUPPRIMER = ["matiere", "niveau", "prix_1er", "prix_2eme", "prix_3eme"]


def supprimer_colonnes_abandonnees(apps, schema_editor):
    """
    P2.5 : supprime physiquement matiere/niveau/prix_1er/prix_2eme/prix_3eme
    de la table `yeki_olympiade` si elles existent encore (cas probable de
    la production PostgreSQL, cf. migration 0004 précédente qui a déjà
    fusionné le contenu de prix_1er/2eme/3eme dans `recompense`). Ces
    champs ne sont plus déclarés sur le modèle `Olympiade` depuis
    longtemps — Django ne peut donc pas générer de `RemoveField` pour eux,
    d'où le SQL brut. No-op loggé si une colonne est déjà absente (cas
    confirmé de la base de dev). Un échec de DROP sur une colonne est
    loggé et n'interrompt pas la migration (rien perdu : au pire une
    colonne orpheline reste, jamais une perte de données).
    """
    if schema_editor.connection.vendor not in ("sqlite", "postgresql"):
        logger.warning(
            "P2.5 : moteur de base non testé (%s) — suppression de "
            "colonnes ignorée par prudence, à rejouer manuellement si "
            "nécessaire.",
            schema_editor.connection.vendor,
        )
        return

    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(cursor, TABLE)
        noms_existants = {col.name for col in description}

        supprimees, absentes, echecs = [], [], []
        for colonne in COLONNES_A_SUPPRIMER:
            if colonne not in noms_existants:
                absentes.append(colonne)
                continue
            try:
                cursor.execute(f"ALTER TABLE {TABLE} DROP COLUMN {colonne}")
                supprimees.append(colonne)
            except Exception:
                logger.exception(
                    "P2.5 : échec de la suppression de la colonne %s sur %s "
                    "— colonne laissée en place, à traiter manuellement.",
                    colonne,
                    TABLE,
                )
                echecs.append(colonne)

        logger.info(
            "P2.5 : suppression des colonnes abandonnées sur %s — "
            "supprimées=%s, déjà absentes=%s, échecs=%s.",
            TABLE,
            supprimees,
            absentes,
            echecs,
        )


def revert_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("evaluation", "0004_fusionner_anciens_prix_olympiade"),
    ]

    operations = [
        migrations.RunPython(supprimer_colonnes_abandonnees, revert_noop),
    ]
