"""
Signaux paiement (P10.3) — remplace les appels manuels dispersés dans
`apps/paiement/views.py` (ValiderPaiementManuelView/RefuserPaiementManuelView
/ValiderRetraitView/RefuserRetraitView) : une notification créée à la main
dans une vue est une notification oubliée dans la vue suivante.

Couvre 4 des 23 déclencheurs du catalogue CDC_BACKEND §9.1.1 :
« Nouvelle demande de paiement » / « Décision de paiement » / « Nouvelle
demande de retrait » / « Décision de retrait ».
"""

from django.contrib.auth.models import User
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.notifications.models import creer_notification
from apps.paiement.models import DemandePaiementManuelle, DemandeRetrait


def _memoriser_ancien_statut(sender, instance, **kwargs):
    """Mémorise l'ancien statut avant sauvegarde — Django ne fournit pas
    nativement l'ancienne valeur dans post_save (même patron que
    apps/accounts/signals.py::_memoriser_ancien_is_repetiteur)."""
    if instance.pk:
        instance._ancien_statut = (
            sender.objects.filter(pk=instance.pk).values_list("statut", flat=True).first()
        )
    else:
        instance._ancien_statut = None


pre_save.connect(_memoriser_ancien_statut, sender=DemandePaiementManuelle)
pre_save.connect(_memoriser_ancien_statut, sender=DemandeRetrait)


def _notifier_service_client(titre: str, contenu: str, objet_id: int, objet_type: str, action_route: str):
    """« Nouvelle demande de paiement/retrait » → TOUS les Service Client
    actifs (aucune notion de "Service Client assigné" n'existe dans le
    modèle métier — un seul rôle, plusieurs comptes possibles)."""
    users = User.objects.filter(profile__user_type="service_client", profile__is_active=True)
    for user in users:
        creer_notification(
            utilisateur=user,
            type_notif="paiement",
            titre=titre,
            contenu=contenu,
            objet_id=objet_id,
            objet_type=objet_type,
            action_route=action_route,
        )


@receiver(post_save, sender=DemandePaiementManuelle)
def _notifier_demande_paiement_manuel(sender, instance, created, **kwargs):
    if created:
        _notifier_service_client(
            titre="Nouvelle demande de paiement",
            contenu=f"Nouvelle demande de paiement #{instance.id} à valider ({instance.categorie}).",
            objet_id=instance.id,
            objet_type="DemandePaiementManuelle",
            action_route="/service-client",
        )
        return

    ancien = getattr(instance, "_ancien_statut", None)
    if ancien == instance.statut:
        return

    if instance.statut == "validee":
        creer_notification(
            utilisateur=instance.apprenant.user,
            type_notif="paiement",
            titre="Paiement validé",
            contenu=f"Votre demande de paiement #{instance.id} a été validée.",
            objet_id=instance.id,
            objet_type="DemandePaiementManuelle",
            action_route="/wallet",
        )
    elif instance.statut == "refusee":
        creer_notification(
            utilisateur=instance.apprenant.user,
            type_notif="paiement",
            titre="Paiement refusé",
            contenu=f"Votre demande de paiement #{instance.id} a été refusée : {instance.motif_refus}",
            objet_id=instance.id,
            objet_type="DemandePaiementManuelle",
            action_route="/wallet",
        )


@receiver(post_save, sender=DemandeRetrait)
def _notifier_demande_retrait(sender, instance, created, **kwargs):
    if created:
        _notifier_service_client(
            titre="Nouvelle demande de retrait",
            contenu=f"Nouvelle demande de retrait #{instance.id} à valider.",
            objet_id=instance.id,
            objet_type="DemandeRetrait",
            action_route="/service-client",
        )
        return

    ancien = getattr(instance, "_ancien_statut", None)
    if ancien == instance.statut:
        return

    if instance.statut == "validee":
        creer_notification(
            utilisateur=instance.beneficiaire.user,
            type_notif="paiement",
            titre="Retrait validé",
            contenu=f"Votre demande de retrait #{instance.id} a été validée et envoyée.",
            objet_id=instance.id,
            objet_type="DemandeRetrait",
            action_route="/wallet",
        )
    elif instance.statut == "refusee":
        creer_notification(
            utilisateur=instance.beneficiaire.user,
            type_notif="paiement",
            titre="Retrait refusé",
            contenu=(
                f"Votre demande de retrait #{instance.id} a été refusée : "
                f"{instance.motif_refus}. Le solde a été libéré."
            ),
            objet_id=instance.id,
            objet_type="DemandeRetrait",
            action_route="/wallet",
        )
