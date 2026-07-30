"""
Signaux évaluation (P10.3) — remplace 2 des appels manuels dispersés dans
`apps/evaluation/views/devoirs.py` (PublierDevoirView/CorrigerSoumissionView)
par des signaux Django : une notification créée à la main dans une vue est
une notification oubliée dans la vue suivante.

Déclencheurs du catalogue CDC_BACKEND §9.1.1 couverts ici : « Devoir
publié » / « Devoir corrigé ».

Déclencheurs du même catalogue VOLONTAIREMENT LAISSÉS en appel manuel
(champ renommé `action_route`, mais pas convertis en signal) : « Olympiade
créée », « Classement d'olympiade publié », « Gain de rang ». Raison :
contrairement à Devoir/SoumissionDevoir, ni `Olympiade` ni le calcul de
classement ne portent une référence de département/destinataires
directement sur le modèle — les destinataires sont calculés dans la vue à
partir d'un `departement_id` de requête ou d'un service externe
(`ClassementService`). Les convertir en signal exigerait d'ajouter un champ
`Olympiade.departement` (changement de schéma métier hors périmètre de ce
ticket) plutôt que de forcer une abstraction bancale.
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.accounts.models import Profile
from apps.evaluation.models import Devoir, SoumissionDevoir
from apps.notifications.models import creer_notification


@receiver(pre_save, sender=Devoir)
def _memoriser_ancien_est_publie(sender, instance, **kwargs):
    if instance.pk:
        instance._ancien_est_publie = (
            Devoir.objects.filter(pk=instance.pk).values_list("est_publie", flat=True).first()
        )
    else:
        instance._ancien_est_publie = None


@receiver(post_save, sender=Devoir)
def _notifier_devoir_publie(sender, instance, created, **kwargs):
    if created:
        return
    if getattr(instance, "_ancien_est_publie", None) is True or not instance.est_publie:
        return
    # Un devoir d'olympiade (cours_lie=None) n'a pas de cohorte de cours à
    # notifier ici (même garde que l'ancien code dans la vue).
    cours = instance.cours_lie
    if cours is None:
        return

    apprenants = Profile.objects.filter(
        user_type="apprenant", cursus=cours.departement.parcours.nom, is_active=True
    ).select_related("user")
    for apprenant in apprenants:
        creer_notification(
            utilisateur=apprenant.user,
            type_notif="devoir",
            titre=f"Nouveau devoir : {instance.titre}",
            contenu=f"Le devoir '{instance.titre}' est maintenant disponible dans le cours '{cours.titre}'.",
            objet_id=instance.id,
            objet_type="Devoir",
            action_route=f"/devoirs/{instance.id}",
        )


@receiver(pre_save, sender=SoumissionDevoir)
def _memoriser_ancien_statut_soumission(sender, instance, **kwargs):
    if instance.pk:
        instance._ancien_statut = (
            SoumissionDevoir.objects.filter(pk=instance.pk).values_list("statut", flat=True).first()
        )
    else:
        instance._ancien_statut = None


@receiver(post_save, sender=SoumissionDevoir)
def _notifier_devoir_corrige(sender, instance, created, **kwargs):
    if created:
        return
    ancien = getattr(instance, "_ancien_statut", None)
    if ancien == "corrige" or instance.statut != "corrige":
        return

    note_sur = float(instance.devoir.note_sur)
    creer_notification(
        utilisateur=instance.utilisateur,
        type_notif="correction",
        titre="Devoir corrigé",
        contenu=f"Votre devoir « {instance.devoir.titre} » a été corrigé : {instance.note}/{note_sur}.",
        objet_id=instance.devoir.id,
        objet_type="Devoir",
        action_route=f"/devoirs/{instance.devoir.id}/resultat",
    )
