"""
Signaux Profile (P2.1). Connectés depuis AccountsConfig.ready().
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.accounts.models import Profile


@receiver(pre_save, sender=Profile)
def _memoriser_ancien_is_repetiteur(sender, instance, **kwargs):
    """
    Mémorise l'ancienne valeur de `is_repetiteur` sur l'instance avant
    sauvegarde, pour que le signal post_save puisse détecter une
    transition True → False (Django ne fournit pas nativement l'ancienne
    valeur dans post_save).
    """
    if instance.pk:
        ancien = (
            Profile.objects.filter(pk=instance.pk).values_list("is_repetiteur", flat=True).first()
        )
        instance._ancien_is_repetiteur = ancien
    else:
        instance._ancien_is_repetiteur = None


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
