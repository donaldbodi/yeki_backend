"""
Signaux Profile (P2.1) + notifications (P10.3). Connectés depuis
AccountsConfig.ready().
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.accounts.models import Profile
from apps.notifications.models import creer_notification


@receiver(pre_save, sender=Profile)
def _memoriser_ancien_is_repetiteur(sender, instance, **kwargs):
    """
    Mémorise l'ancienne valeur de `is_repetiteur` ET `user_type` sur
    l'instance avant sauvegarde, pour que le signal post_save puisse
    détecter une transition (Django ne fournit pas nativement l'ancienne
    valeur dans post_save).
    """
    if instance.pk:
        ancien = (
            Profile.objects.filter(pk=instance.pk)
            .values("is_repetiteur", "user_type")
            .first()
        )
        instance._ancien_is_repetiteur = ancien["is_repetiteur"] if ancien else None
        instance._ancien_user_type = ancien["user_type"] if ancien else None
    else:
        instance._ancien_is_repetiteur = None
        instance._ancien_user_type = None


@receiver(post_save, sender=Profile)
def _desactiver_fiches_repetiteur(sender, instance, created, **kwargs):
    """
    CDC P2.1 : un enseignant dont `is_repetiteur` repasse à False voit
    TOUTES ses fiches Repetiteur passer `disponible=False` — jamais
    supprimées (statut réversible, voir docs/API_FOUNDATIONS.md).
    """
    if created:
        return

    ancien = getattr(instance, "_ancien_is_repetiteur", None)
    if ancien is True and instance.is_repetiteur is False:
        # Import différé : apps.repetiteurs.models importe déjà
        # apps.accounts.models, un import en tête de ce fichier créerait un
        # cycle au chargement des apps.
        from apps.repetiteurs.models import Repetiteur

        Repetiteur.objects.filter(enseignant=instance).update(disponible=False)


@receiver(post_save, sender=Profile)
def _notifier_valide_repetiteur(sender, instance, created, **kwargs):
    """P10.3 — catalogue CDC_BACKEND §9.1.1 : « Compte validé comme
    répétiteur »."""
    if created:
        return
    ancien = getattr(instance, "_ancien_is_repetiteur", None)
    if ancien is False and instance.is_repetiteur is True:
        creer_notification(
            utilisateur=instance.user,
            type_notif="system",
            titre="Vous êtes validé comme répétiteur",
            contenu="Votre compte a été validé pour proposer des cours particuliers.",
            objet_id=instance.id,
            objet_type="Profile",
            action_route="/profile",
        )


@receiver(post_save, sender=Profile)
def _notifier_changement_de_grade(sender, instance, created, **kwargs):
    """P10.3 — catalogue CDC_BACKEND §9.1.1 : « Changement de grade »."""
    if created:
        return
    ancien = getattr(instance, "_ancien_user_type", None)
    if ancien is not None and ancien != instance.user_type:
        creer_notification(
            utilisateur=instance.user,
            type_notif="system",
            titre="Changement de grade",
            contenu=f"Votre rôle sur Yéki a changé : {instance.get_user_type_display()}.",
            objet_id=instance.id,
            objet_type="Profile",
            action_route="/profile",
        )
