from django.db import models
from django.core.exceptions import PermissionDenied
from django.contrib.auth.models import User
import mammoth
from django.db.models.signals import post_save
from django.dispatch import receiver


class Profile(models.Model):
    USER_TYPES = (
        ('admin', 'Administrateur'),
        ('enseignant_admin', 'Enseignant Administrateur'),
        ('enseignant_cadre', 'Enseignant Cadre'),
        ('enseignant_principal', 'Enseignant Principal'),
        ('enseignant', 'Enseignant'),
        ('apprenant', 'Apprenant'),
    )
    user_type = models.CharField(max_length=20, choices=USER_TYPES, default='apprenant', blank=True, null=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    # Champs optionnels pour apprenant (pas utilisés ici)
    cursus = models.CharField(max_length=100, null=True, blank=True)
    sub_cursus = models.CharField(max_length=100, null=True, blank=True)
    niveau = models.CharField(max_length=100, null=True, blank=True)
    filiere = models.CharField(max_length=100, null=True, blank=True)
    licence = models.CharField(max_length=100, null=True, blank=True)

    is_active = models.BooleanField(default=False)

    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.user_type})"


# --- NIVEAU 1 ---

class Parcours(models.Model):
    nom = models.CharField(max_length=100)
    admin = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'user_type': 'enseignant_admin'},
        related_name='parcours_admin'
    )

    def __str__(self):
        return f"{self.nom} ({self.admin})"


# --- NIVEAU 2 ---
class Departement(models.Model):
    nom = models.CharField(max_length=100)
    parcours = models.ForeignKey(Parcours, on_delete=models.CASCADE, related_name="departements")
    cadre = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'user_type': 'enseignant_cadre'},
        related_name='departements_cadre'
    )

    def __str__(self):
        return f"{self.nom} ({self.parcours.nom}. cadre: {self.cadre})"

    # ✅ Seul un enseignant_admin peut créer un département
    @staticmethod
    def create_departement(user, parcours, nom, cadre):
        if user.user_type != "enseignant_admin":
            raise PermissionDenied("Seul un enseignant_admin peut créer un département.")
        return Departement.objects.create(parcours=parcours, nom=nom, cadre=cadre)



# --- NIVEAU 3 ---
class Cours(models.Model):
    titre = models.CharField(max_length=200)
    niveau = models.CharField(max_length=200)

    # Relations
    departement = models.ForeignKey(
        Departement,
        on_delete=models.CASCADE,
        related_name="cours"
    )

    # --- NOUVEAUX CHAMPS ---
    description_brief = models.CharField(
        max_length=255,
        help_text="Description courte du cours",
        blank=True
    )

    color_code = models.CharField(
        max_length=7,
        default="#008080",
        help_text="Code couleur hexadécimal (#RRGGBB)"
    )

    icon_name = models.CharField(
        max_length=50,
        default="school",
        help_text="Nom de l’icône Flutter (MaterialIcons)"
    )

    nb_devoirs = models.PositiveIntegerField(default=0)
    nb_lecons = models.PositiveIntegerField(default=0)

    # --- EXISTANTS ---
    matiere = models.CharField(max_length=255, blank=True)
    concours = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True, null=True)

    nb_apprenants = models.PositiveIntegerField(default=0)

    enseignant_principal = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'user_type': 'enseignant_principal'},
        related_name='cours_principal'
    )

    enseignants = models.ManyToManyField(
        Profile,
        blank=True,
        limit_choices_to={'user_type': 'enseignant'},
        related_name='cours_secondaires'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.titre} ({self.niveau})"


# --- NIVEAU 4 ---
class Lecon(models.Model):
    titre = models.CharField(max_length=200)
    fichier = models.FileField(upload_to='lecons/')
    video = models.FileField(upload_to='video', blank=True, null=True)
    description = models.TextField()
    contenu_html = models.TextField(blank=True, null=True)
    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, related_name="lecons")
    created_by = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.titre} ({self.cours.titre})"

    # ✅ Seul un enseignant_principal peut créer une leçon
    @staticmethod
    def create_lecon(user, cours, titre, description):
        if user.user_type != "enseignant_principal":
            raise PermissionDenied("Seul un enseignant_principal peut créer une leçon.")
        return Lecon.objects.create(
            cours=cours,
            titre=titre,
            description=description,
            created_by=user
        )

@receiver(post_save, sender=Lecon)
def convertir_docx_en_html(sender, instance, **kwargs):
    if instance.fichier and instance.fichier.name.endswith(".docx"):
        with open(instance.fichier.path, "rb") as docx_file:
            result = mammoth.convert_to_html(docx_file)
            html = result.value  # HTML du contenu
            instance.contenu_html = html
            instance.save()

