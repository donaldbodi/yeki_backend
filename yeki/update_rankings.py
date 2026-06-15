from django.core.management.base import BaseCommand
from yeki.ranking_service import RankingService

class Command(BaseCommand):
    help = 'Met à jour les rangs des apprenants pour tous les départements'

    def add_arguments(self, parser):
        parser.add_argument(
            '--departement_id',
            type=int,
            help='ID du département spécifique à mettre à jour',
        )

    def handle(self, *args, **options):
        if options['departement_id']:
            from yeki.models import Departement
            dept = Departement.objects.get(id=options['departement_id'])
            count = RankingService.mettre_a_jour_rangs_departement(dept)
            self.stdout.write(f"Département '{dept.nom}': {count} apprenants traités")
        else:
            count = RankingService.mettre_a_jour_tous_les_rangs()
            self.stdout.write(f"Mise à jour complète: {count} apprenants traités")