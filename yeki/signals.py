from django.db.models.signals import post_save, post_delete
from django.contrib.auth.models import User
from django.dispatch import receiver
from .models import Profile, Lecon, Devoir

#@receiver(post_save, sender=User)
#def create_profile(sender, instance, created, **kwargs):
#    if created:
#        Profile.objects.create(user=instance)


@receiver(post_save, sender=Lecon)
def update_nb_lecons_on_save(sender, instance, **kwargs):
    """Met à jour le compteur nb_lecons du cours à chaque ajout/modification de leçon."""
    cours = instance.cours
    cours.nb_lecons = cours.lecons.count()
    cours.save(update_fields=["nb_lecons"])


@receiver(post_delete, sender=Lecon)
def update_nb_lecons_on_delete(sender, instance, **kwargs):
    """Met à jour le compteur nb_lecons du cours à chaque suppression de leçon."""
    try:
        cours = instance.cours
        cours.nb_lecons = cours.lecons.count()
        cours.save(update_fields=["nb_lecons"])
    except Exception:
        pass


@receiver(post_save, sender=Devoir)
def update_nb_devoirs_on_save(sender, instance, created, **kwargs):
    """Met à jour le compteur nb_devoirs du cours à chaque ajout de devoir."""
    if created:
        cours = instance.cours_lie  # Devoir utilise cours_lie comme FK vers Cours
        if cours:
            cours.nb_devoirs = cours.devoirs.count()
            cours.save(update_fields=["nb_devoirs"])


@receiver(post_delete, sender=Devoir)
def update_nb_devoirs_on_delete(sender, instance, **kwargs):
    """Met à jour le compteur nb_devoirs du cours à chaque suppression de devoir."""
    try:
        cours = instance.cours_lie
        if cours:
            cours.nb_devoirs = cours.devoirs.count()
            cours.save(update_fields=["nb_devoirs"])
    except Exception:
        pass
