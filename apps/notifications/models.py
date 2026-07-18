import logging

from django.db import models
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS IN-APP
# ═══════════════════════════════════════════════════════════════════════════


class Notification(models.Model):
    """
    Notification in-app pour les utilisateurs.
    Types:
    - devoir: nouveau devoir publié
    - correction: devoir/exercice corrigé
    - olympiade: olympiade créée/à venir
    - rappel: rappel de date limite
    - classement: changement de rang
    - forum: réponse à une question
    - system: notification système
    """

    TYPE_CHOICES = [
        ("devoir", "Devoir"),
        ("correction", "Correction"),
        ("olympiade", "Olympiade"),
        ("rappel", "Rappel"),
        ("classement", "Classement"),
        ("forum", "Forum"),
        ("system", "Système"),
    ]

    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="system")
    titre = models.CharField(max_length=255)
    contenu = models.TextField()
    est_lue = models.BooleanField(default=False)
    cree_le = models.DateTimeField(auto_now_add=True)

    # Lien vers l'objet concerné (optionnel)
    objet_id = models.PositiveIntegerField(null=True, blank=True)
    objet_type = models.CharField(max_length=50, blank=True)
    action_url = models.CharField(max_length=500, blank=True, help_text="URL de redirection")

    class Meta:
        db_table = "yeki_notification"
        ordering = ["-cree_le"]
        indexes = [
            models.Index(fields=["utilisateur", "est_lue"]),
            models.Index(fields=["utilisateur", "cree_le"]),
        ]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self):
        return (
            f"{self.titre} → {self.utilisateur.username} ({'lue' if self.est_lue else 'non lue'})"
        )


class DeviceToken(models.Model):
    """
    Jeton d'appareil pour les notifications push via Firebase Cloud
    Messaging (P2.4, CDC §8.2). Un jeton invalide (erreur `UNREGISTERED`
    lors de l'envoi) doit être désactivé (`actif=False`), jamais supprimé.
    """

    PLATEFORME_CHOICES = [
        ("android", "Android"),
        ("ios", "iOS"),
        ("web", "Web"),
        ("desktop", "Desktop"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="device_tokens")
    token = models.CharField(max_length=255, unique=True)
    plateforme = models.CharField(max_length=20, choices=PLATEFORME_CHOICES)
    actif = models.BooleanField(default=True)
    derniere_utilisation = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "yeki_device_token"
        verbose_name = "Jeton d'appareil"
        verbose_name_plural = "Jetons d'appareil"

    def __str__(self):
        return f"{self.user.username} — {self.get_plateforme_display()} ({'actif' if self.actif else 'inactif'})"


# Helper pour créer une notification
def creer_notification(
    utilisateur,
    type_notif: str,
    titre: str,
    contenu: str,
    objet_id: int = None,
    objet_type: str = "",
    action_url: str = "",
):
    """
    Crée une notification pour un utilisateur.
    """
    try:
        Notification.objects.create(
            utilisateur=utilisateur,
            type=type_notif,
            titre=titre,
            contenu=contenu,
            objet_id=objet_id,
            objet_type=objet_type,
            action_url=action_url,
        )
        return True
    except Exception:
        # Volontairement large : une notification in-app est un
        # accessoire — elle ne doit jamais faire échouer l'action métier
        # (création de devoir, correction, etc.) qui l'a déclenchée.
        logger.exception("Échec création Notification (type=%s)", type_notif)
        return False
