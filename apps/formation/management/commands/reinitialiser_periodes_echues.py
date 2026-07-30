"""
P12.4 — commande de gestion pour la réinitialisation des périodes de
classement échues. `Departement.reinitialiser_periode()`
(`apps/formation/models.py`) existe depuis P2.3 et fait déjà tout le
travail d'archivage (ClassementHistorique) + reset, mais n'avait aucun
appelant en production — seul un test l'invoquait.

`reinitialiser_periode()` ne vérifie elle-même aucune date (elle
réinitialise inconditionnellement le département sur lequel elle est
appelée) et n'est pas idempotente dans son ensemble (un second appel
avancerait silencieusement une deuxième fois les dates de période) —
c'est donc cette commande, pas la méthode, qui décide quels départements
sont réellement échus (`date_fin_periode <= maintenant`).

À planifier côté hébergeur (PythonAnywhere : onglet "Tasks"), quotidien
— même mécanisme que `apps/core/management/commands/envoyer_rappels.py`,
cette commande ne s'auto-planifie pas elle-même, aucun scheduler
n'existe dans le code (action manuelle, documentée, hors de portée du
code applicatif).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.formation.models import Departement


class Command(BaseCommand):
    help = "Archive puis réinitialise les périodes de classement échues (CDC §9.2)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--departement_id",
            type=int,
            help="Limiter à ce département (toujours soumis à l'échéance de sa période).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Lister les départements qui seraient réinitialisés, sans rien modifier.",
        )

    def handle(self, *args, **options):
        maintenant = timezone.now()
        departements = Departement.objects.filter(
            date_fin_periode__isnull=False, date_fin_periode__lte=maintenant
        )
        if options["departement_id"]:
            departements = departements.filter(id=options["departement_id"])

        if options["dry_run"]:
            total = 0
            for departement in departements:
                self.stdout.write(
                    f"[dry-run] À réinitialiser : {departement} "
                    f"(échue le {departement.date_fin_periode})."
                )
                total += 1
            self.stdout.write(f"[dry-run] {total} département(s) concerné(s).")
            return

        total = 0
        for departement in departements:
            departement.reinitialiser_periode()
            total += 1
            self.stdout.write(f"Période réinitialisée : {departement}.")
        self.stdout.write(f"{total} département(s) réinitialisé(s).")
