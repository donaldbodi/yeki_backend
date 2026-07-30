"""
P10.3 — commande de gestion des rappels (CDC_BACKEND §9.1.1) :
- `--horaire` : devoir dans 1 h · olympiade démarre dans 1 h.
- `--quotidien` : devoir dans 24 h · abonnement expire dans 3 jours.

À planifier côté hébergeur (PythonAnywhere : onglet "Tasks") — cette
commande ne s'auto-planifie pas elle-même, aucun scheduler n'existe dans
le code (action manuelle, documentée, hors de portée du code applicatif).

Idempotence : réutilise le modèle `Notification` existant comme registre
"déjà notifié" (titre + objet_id + objet_type + utilisateur) plutôt que
d'ajouter de nouveaux champs de suivi — évite une migration de schéma
pour un simple garde-fou anti-doublon.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.evaluation.models import Devoir, Olympiade, SoumissionDevoir, InscriptionOlympiade
from apps.notifications.models import Notification, creer_notification
from apps.paiement.models import AbonnementPremium


def _apprenants_du_cours(cours):
    from apps.accounts.models import Profile

    return Profile.objects.filter(
        user_type="apprenant", cursus=cours.departement.parcours.nom, is_active=True
    ).select_related("user")


def _deja_notifie(utilisateur, titre, objet_id, objet_type) -> bool:
    return Notification.objects.filter(
        utilisateur=utilisateur, titre=titre, objet_id=objet_id, objet_type=objet_type
    ).exists()


class Command(BaseCommand):
    help = "Envoie les rappels de dates limites (devoirs, olympiades, abonnements) — CDC §9.1.1."

    def add_arguments(self, parser):
        groupe = parser.add_mutually_exclusive_group(required=True)
        groupe.add_argument("--horaire", action="store_true", help="Rappels à échéance 1 h.")
        groupe.add_argument("--quotidien", action="store_true", help="Rappels à échéance 24 h/3 j.")

    def handle(self, *args, **options):
        maintenant = timezone.now()
        if options["horaire"]:
            n1 = self._rappels_devoir(maintenant, timedelta(hours=1), "Devoir à rendre dans 1 heure")
            n2 = self._rappels_olympiade(maintenant)
            self.stdout.write(f"Rappels horaires : {n1} devoir(s), {n2} olympiade(s).")
        else:
            n1 = self._rappels_devoir(maintenant, timedelta(hours=24), "Devoir à rendre dans 24 heures")
            n2 = self._rappels_abonnement(maintenant)
            self.stdout.write(f"Rappels quotidiens : {n1} devoir(s), {n2} abonnement(s).")

    def _rappels_devoir(self, maintenant, delai, titre) -> int:
        devoirs = Devoir.objects.filter(
            est_publie=True,
            cours_lie__isnull=False,
            date_limite__gt=maintenant,
            date_limite__lte=maintenant + delai,
        ).select_related("cours_lie__departement__parcours")

        total = 0
        for devoir in devoirs:
            deja_soumis = set(
                SoumissionDevoir.objects.filter(
                    devoir=devoir, statut__in=["soumis", "corrige"]
                ).values_list("utilisateur_id", flat=True)
            )
            for apprenant in _apprenants_du_cours(devoir.cours_lie):
                if apprenant.user_id in deja_soumis:
                    continue
                if _deja_notifie(apprenant.user, titre, devoir.id, "Devoir"):
                    continue
                creer_notification(
                    utilisateur=apprenant.user,
                    type_notif="rappel",
                    titre=titre,
                    contenu=f"Le devoir « {devoir.titre} » doit être rendu bientôt.",
                    objet_id=devoir.id,
                    objet_type="Devoir",
                    action_route=f"/devoirs/{devoir.id}",
                )
                total += 1
        return total

    def _rappels_olympiade(self, maintenant) -> int:
        titre = "Olympiade dans 1 heure"
        olympiades = Olympiade.objects.filter(
            date_debut_olympiade__gt=maintenant,
            date_debut_olympiade__lte=maintenant + timedelta(hours=1),
        )
        total = 0
        for olympiade in olympiades:
            inscrits = InscriptionOlympiade.objects.filter(olympiade=olympiade).select_related(
                "apprenant"
            )
            for inscription in inscrits:
                if _deja_notifie(inscription.apprenant, titre, olympiade.id, "Olympiade"):
                    continue
                creer_notification(
                    utilisateur=inscription.apprenant,
                    type_notif="rappel",
                    titre=titre,
                    contenu=f"L'olympiade « {olympiade.titre} » démarre dans 1 heure.",
                    objet_id=olympiade.id,
                    objet_type="Olympiade",
                    action_route=f"/olympiades/{olympiade.id}",
                )
                total += 1
        return total

    def _rappels_abonnement(self, maintenant) -> int:
        titre = "Abonnement expire dans 3 jours"
        abonnements = AbonnementPremium.objects.filter(
            actif=True,
            fin__gt=maintenant,
            fin__lte=maintenant + timedelta(days=3),
        ).select_related("utilisateur")
        total = 0
        for abonnement in abonnements:
            if _deja_notifie(abonnement.utilisateur, titre, abonnement.id, "AbonnementPremium"):
                continue
            creer_notification(
                utilisateur=abonnement.utilisateur,
                type_notif="rappel",
                titre=titre,
                contenu="Votre abonnement Premium expire dans 3 jours. Pensez à le renouveler.",
                objet_id=abonnement.id,
                objet_type="AbonnementPremium",
                action_route="/paiement",
            )
            total += 1
        return total
