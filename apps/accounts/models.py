import random
import string
from datetime import timedelta

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Profile(models.Model):
    USER_TYPES = (
        ("admin", "Administrateur"),
        ("service_client", "Service Client"),
        ("enseignant_admin", "Enseignant Administrateur"),
        ("enseignant_cadre", "Enseignant Cadre"),
        ("enseignant_principal", "Enseignant Principal"),
        ("enseignant", "Enseignant"),
        ("apprenant", "Apprenant"),
    )
    user_type = models.CharField(
        max_length=20,
        choices=USER_TYPES,
        default="apprenant",
        blank=True,
        null=True,
        db_index=True,
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    # Champs optionnels pour apprenant (pas utilisés ici)
    cursus = models.CharField(max_length=100, null=True, blank=True)
    sub_cursus = models.CharField(max_length=100, null=True, blank=True)
    niveau = models.CharField(max_length=100, null=True, blank=True)
    filiere = models.CharField(max_length=100, null=True, blank=True)
    licence = models.CharField(max_length=100, null=True, blank=True)
    # Département choisi à l'inscription (CDC §13.2 : parcours/département/
    # niveau obligatoires). Nullable ici pour ne pas casser les Profile
    # existants ; l'obligation est appliquée côté RegisterSerializer. Le
    # parcours se déduit de `departement.parcours` (une seule source de
    # vérité, pas de FK parcours redondante).
    departement = models.ForeignKey(
        "formation.Departement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profils",
    )
    ville = models.CharField(max_length=100, blank=True, null=True, help_text="Ville de résidence")

    is_active = models.BooleanField(default=False)

    phone = models.CharField(max_length=20, blank=True)
    whatsapp = models.CharField(
        max_length=20, blank=True, help_text="Numéro WhatsApp pour les répétiteurs"
    )
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    bio = models.TextField(blank=True)

    # Validé par le Service Client (P2.1, CDC §7.1). Ne concerne que les
    # enseignants — un enseignant repassant à False voit ses fiches
    # Repetiteur passer disponible=False (jamais supprimées), voir
    # apps/accounts/signals.py.
    is_repetiteur = models.BooleanField(
        default=False,
        help_text="Validé par le Service Client. Ne concerne que les enseignants.",
    )

    class Meta:
        db_table = "yeki_profile"

    def __str__(self):
        return f"{self.user.username} ({self.user_type})"


class PasswordResetOTP(models.Model):
    """
    Code OTP à 6 chiffres envoyé par email pour réinitialiser le mot de passe.
    - Expire après 10 minutes
    - Invalidé après utilisation
    - Maximum 5 tentatives de validation
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="reset_otps",
    )
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "yeki_passwordresetotp"
        ordering = ["-created_at"]
        verbose_name = "OTP Réinitialisation"

    def save(self, *args, **kwargs):
        if not self.pk:
            # Génère un code à 6 chiffres
            self.code = "".join(random.choices(string.digits, k=6))
            # Expire dans 10 minutes
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    @property
    def is_valid(self):
        return not self.used and self.attempts < 5 and timezone.now() < self.expires_at

    def __str__(self):
        return f"OTP {self.code} → {self.user.username} ({'✓' if self.used else '⏳'})"
