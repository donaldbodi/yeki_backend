from django.db import models

from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    ROLE_CHOICES = (
        ('apprenant', 'Apprenant'),
        ('enseignant', 'Enseignant'),
        ('enseignant_principal', 'Enseignant Principal'),
        ('admin', 'Administrateur'),
    )
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='apprenant')

    def __str__(self):
        return f"{self.username} ({self.role})"

