from django.db import models

from django.contrib.auth.models import AbstractUser
from django.db import models

class AppVersion(models.Model):
    version_code = models.IntegerField()  # Exemple: 3
    version_name = models.CharField(max_length=20)  # Exemple: "1.0.3"
    apk_url = models.URLField()  # Lien direct Google Drive ou autre
    changelog = models.TextField(blank=True)  # Liste des nouveautés

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Version {self.version_name}"



class CustomUser(AbstractUser):
    USER_TYPES = (
        ('apprenant', 'Apprenant'),
        ('enseignant', 'Enseignant'),
        ('enseignant_principal', 'Enseignant Principal'),
        ('enseignant_admin', 'Enseignant Administrateur'),
        ('admin', 'Administrateur'),
    )
    user_type = models.CharField(max_length=20, choices=USER_TYPES, default='apprenant')
    name = models.CharField(max_length=100)
    
    # Apprenant fields
    cursus = models.CharField(max_length=100, null=True, blank=True)
    sub_cursus = models.CharField(max_length=100, null=True, blank=True)
    niveau = models.CharField(max_length=100, null=True, blank=True)
    filiere = models.CharField(max_length=100, null=True, blank=True)
    licence = models.CharField(max_length=100, null=True, blank=True)

    # Retirer l’identifiant (comme demandé)
    is_active = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.username} ({self.user_type})"


class Parcours(models.Model):
    nom = models.CharField(max_length=100)
    admin = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={
            'user_type__in': ['enseignant', 'enseignant_principal', 'enseignant_admin', 'admin']
        },
        related_name='parcours_admin'
    )
    cours = models.IntegerField(default=0)
    apprenants = models.IntegerField(default=0)
    moyenne = models.FloatField(default=0.0)

    def __str__(self):
        return self.nom

