"""
Signaux Departement (P2.4) + notifications formation (P10.3). Connectés
depuis FormationConfig.ready().
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.accounts.models import Profile
from apps.formation.models import (
    CHAMPS_PRIX_HISTORISES,
    Cours,
    DemandeAccesFormation,
    Departement,
    HistoriquePrixDepartement,
)
from apps.notifications.models import creer_notification


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


# ─────────────────────────────────────────────────────────────────────────
# P10.3 — notifications (catalogue CDC_BACKEND §9.1.1)
# ─────────────────────────────────────────────────────────────────────────
# « Nouveau cours / leçon / supplément » : seule la création de COURS est
# couverte ici. La création de LEÇON est volontairement exclue — `Lecon
# .module` est nullable et la remonter jusqu'au département exigerait de
# traverser un lien optionnel ; surtout, notifier TOUS les apprenants du
# département à chaque leçon ajoutée pendant la construction d'un cours
# serait un bruit de notification disproportionné, non demandé ailleurs
# dans le produit (aucun autre déclencheur n'est aussi fréquent).


@receiver(post_save, sender=Cours)
def _notifier_nouveau_cours(sender, instance, created, **kwargs):
    if not created:
        return
    departement = instance.departement
    apprenants = Profile.objects.filter(
        user_type="apprenant", cursus=departement.parcours.nom, is_active=True
    ).select_related("user")
    for apprenant in apprenants:
        creer_notification(
            utilisateur=apprenant.user,
            type_notif="devoir",
            titre=f"Nouveau cours : {instance.titre}",
            contenu=f"Le cours '{instance.titre}' est maintenant disponible dans '{departement.nom}'.",
            objet_id=instance.id,
            objet_type="Cours",
            action_route=f"/cours/{instance.id}",
        )


@receiver(pre_save, sender=DemandeAccesFormation)
def _memoriser_ancien_statut_demande_acces(sender, instance, **kwargs):
    if instance.pk:
        instance._ancien_statut = (
            DemandeAccesFormation.objects.filter(pk=instance.pk)
            .values_list("statut", flat=True)
            .first()
        )
    else:
        instance._ancien_statut = None


@receiver(post_save, sender=DemandeAccesFormation)
def _notifier_demande_acces_formation(sender, instance, created, **kwargs):
    if created:
        admin = instance.departement.parcours.admin if instance.departement.parcours_id else None
        if admin:
            creer_notification(
                utilisateur=admin.user,
                type_notif="system",
                titre="Nouvelle demande d'accès à une formation",
                contenu=f"{instance.apprenant.username} demande l'accès à « {instance.departement.nom} ».",
                objet_id=instance.id,
                objet_type="DemandeAccesFormation",
                action_route="/enseignant/coordination",
            )
        return

    ancien = getattr(instance, "_ancien_statut", None)
    if ancien == instance.statut or instance.statut == "en_attente":
        return
    if instance.statut == "acceptee":
        contenu = f"Votre demande d'accès à « {instance.departement.nom} » a été acceptée."
    else:
        contenu = f"Votre demande d'accès à « {instance.departement.nom} » a été refusée."
    creer_notification(
        utilisateur=instance.apprenant,
        type_notif="system",
        titre="Décision sur votre demande d'accès",
        contenu=contenu,
        objet_id=instance.departement.id,
        objet_type="Departement",
        action_route=f"/formations/{instance.departement.id}",
    )
