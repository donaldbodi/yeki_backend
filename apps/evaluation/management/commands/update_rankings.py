from django.core.management.base import BaseCommand

from apps.evaluation.views.classement import RankingService

# TODO(bloqué, pré-existant) : `RankingService` (voir
# apps/evaluation/views/classement.py) ne se charge pas — son import de
# `yeki.ranking_service` échoue tant que ce fichier n'est pas restauré. Cette
# commande était définie dans yeki/views.py avant l'éclatement (un
# emplacement non idiomatique — le commentaire de ranking_service.py
# indiquait lui-même "Créer fichier: management/commands/update_rankings.py").
# Replacée ici, à son emplacement Django correct, sans changement de logique.


class Command(BaseCommand):
    help = "Met à jour les rangs des apprenants pour tous les départements"

    def add_arguments(self, parser):
        parser.add_argument(
            "--departement_id",
            type=int,
            help="ID du département spécifique à mettre à jour",
        )

    def handle(self, *args, **options):
        if options["departement_id"]:
            from apps.formation.models import Departement

            dept = Departement.objects.get(id=options["departement_id"])
            count = RankingService.mettre_a_jour_rangs_departement(dept)
            self.stdout.write(f"Département '{dept.nom}': {count} apprenants traités")
        else:
            count = RankingService.mettre_a_jour_tous_les_rangs()
            self.stdout.write(f"Mise à jour complète: {count} apprenants traités")
