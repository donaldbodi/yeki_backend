"""
Signaux Departement (P2.4). Connectés depuis FormationConfig.ready().
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.formation.models import CHAMPS_PRIX_HISTORISES, Departement, HistoriquePrixDepartement


@receiver(pre_save, sender=Departement)
def _memoriser_anciens_prix(sender, instance, **kwargs):
    """
    Mémorise les anciennes valeurs de prix/prix_presentiel avant
    sauvegarde, pour que post_save puisse détecter un changement (Django
    ne fournit pas nativement l'ancienne valeur dans post_save).
    """
    if instance.pk:
        anciennes = (
            Departement.objects.filter(pk=instance.pk).values(*CHAMPS_PRIX_HISTORISES).first()
        )
        instance._anciens_prix = anciennes
    else:
        instance._anciens_prix = None


@receiver(post_save, sender=Departement)
def _historiser_changement_prix(sender, instance, created, **kwargs):
    """
    P2.4 (CDC §6.4) : sans cet historique, « prix inférieur à l'ancien »
    n'a aucun référent — la règle PROMOTION ne peut littéralement pas être
    calculée. Portée limitée aux champs de CHAMPS_PRIX_HISTORISES (seule
    motivation donnée par le CDC), pas un audit générique de tout champ.
    """
    if created:
        return

    anciens = getattr(instance, "_anciens_prix", None)
    if not anciens:
        return

    for champ in CHAMPS_PRIX_HISTORISES:
        ancienne_valeur = anciens.get(champ)
        nouvelle_valeur = getattr(instance, champ)
        if ancienne_valeur is not None and ancienne_valeur != nouvelle_valeur:
            HistoriquePrixDepartement.objects.create(
                departement=instance,
                champ=champ,
                ancienne_valeur=ancienne_valeur,
                nouvelle_valeur=nouvelle_valeur,
            )
