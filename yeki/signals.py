from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from .models import Profile, Lecon

#@receiver(post_save, sender=User)
#def create_profile(sender, instance, created, **kwargs):
#    if created:
#        Profile.objects.create(user=instance)

@receiver(post_save, sender=Lecon)
def increment_nb_lecons(sender, instance, **kwargs):
    cours = instance.cours
    cours.nb_lecons = cours.lecons.count()
    cours.save(update_fields=["nb_lecons"])
