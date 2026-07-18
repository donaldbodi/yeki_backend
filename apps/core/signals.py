"""
Signaux core (P2.4). Connectés depuis CoreConfig.ready().
"""

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.core.models import ParametreSysteme


@receiver(post_save, sender=ParametreSysteme)
@receiver(post_delete, sender=ParametreSysteme)
def _invalider_cache_parametre(sender, instance, **kwargs):
    """
    Invalide le cache mémoire à chaque écriture/suppression — l'admin
    général doit voir sa modification prise en compte immédiatement, sans
    redéploiement ni redémarrage du process (voir ParametreSysteme.get()).
    """
    cache.delete(ParametreSysteme._cache_key(instance.cle))
