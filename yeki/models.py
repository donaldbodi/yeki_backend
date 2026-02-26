from django.db import models
from django.core.exceptions import PermissionDenied
from django.contrib.auth.models import User
#import mammoth
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
    # --- EXISTANTS ---
    matiere = models.CharField(max_length=255, blank=True)
    concours = models.CharField(max_length=255, blank=True)

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

    nb_apprenants = models.PositiveIntegerField(default=0)

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
        blank=True, null=True
    )

    color_code = models.CharField(
        max_length=7,
        default="#008080",
        help_text="Code couleur hexadécimal (#RRGGBB)",
    )

    icon_name = models.CharField(
        max_length=50,
        default="school",
        help_text="Nom de l’icône Flutter (MaterialIcons)",
    )

    nb_devoirs = models.PositiveIntegerField(default=0)
    nb_lecons = models.PositiveIntegerField(default=0)


    def __str__(self):
        return f"{self.titre} ({self.niveau})"

    # ✅ Seul un enseignant_cadre peut créer un cours
    @staticmethod
    def create_cours(user, departement, titre, niveau, color_code, icon_name, enseignant_principal=None, description_brief=None):
        try:
            profile = user.profile
        except Profile.DoesNotExist:
            raise PermissionDenied("Profil utilisateur introuvable.")

        if profile.user_type != "enseignant_cadre":
            raise PermissionDenied("Seul un enseignant_cadre peut créer un cours.")

        return Cours.objects.create(
            description_brief=description_brief,
            color_code=color_code,
            icon_name=icon_name,
            departement=departement,
            titre=titre,
            niveau=niveau,
            enseignant_principal=enseignant_principal
        )


class Module(models.Model):
    titre = models.CharField(max_length=200)
    
    description = models.CharField(max_length=200, default='')

    cours = models.ForeignKey(
        Cours,
        on_delete=models.CASCADE,
        related_name="modules"
    )

    ordre = models.PositiveIntegerField(
        help_text="Ordre défini par l'enseignant principal"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['ordre']
        unique_together = ('cours', 'ordre')

    def __str__(self):
        return f"{self.ordre}. {self.titre}"


# --- NIVEAU 4 ---
class Lecon(models.Model):
    titre = models.CharField(max_length=200)

    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name="lecons",
        null=True,
        blank=True,
    )

    description = models.TextField()

    fichier_pdf = models.FileField(
        upload_to='lecons/pdf/',
        help_text="PDF du cours",
        null=True,
        blank=True,
    )

    video = models.FileField(
        upload_to='lecons/video/',
        blank=True,
        null=True
    )

    cours = models.ForeignKey(
        Cours,
        on_delete=models.CASCADE,
        related_name="lecons"
    )

    created_by = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.titre} ({self.cours.titre})"


class Exercice(models.Model):
    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, related_name="exercices")
    titre = models.CharField(max_length=255)
    enonce = models.TextField()
    etoiles = models.IntegerField()
    duree_minutes = models.IntegerField(default=10)  # durée examen
    tentatives_max = models.IntegerField(default=1)

    @property
    def duree(self):
        """Durée en secondes pour Flutter"""
        return self.duree_minutes * 60

    def __str__(self):
        return f"{self.titre} ({self.etoiles}⭐)"


class SessionExercice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    exercice = models.ForeignKey(Exercice, on_delete=models.CASCADE)
    debut = models.DateTimeField(auto_now_add=True)
    termine = models.BooleanField(default=False)

    def temps_restant(self):
        from django.utils import timezone
        delta = timezone.now() - self.debut
        return max(0, self.exercice.duree_minutes * 60 - delta.total_seconds())

    def __str__(self):
        return f"Session {self.user} - {self.exercice}"


class Question(models.Model):
    TYPE_CHOICES = (
        ("qcm", "QCM"),
        ("texte", "Texte"),
    )

    exercice = models.ForeignKey(Exercice, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    type_question = models.CharField(max_length=10, choices=TYPE_CHOICES)
    bonne_reponse = models.CharField(max_length=255)
    points = models.IntegerField(default=1)

    def __str__(self):
        return self.text


class Choix(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choix")
    texte = models.CharField(max_length=255)

    def __str__(self):
        return self.texte


class EvaluationExercice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    exercice = models.ForeignKey(Exercice, on_delete=models.CASCADE)
    score = models.IntegerField()
    total = models.IntegerField()
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.exercice.titre} ({self.score}/{self.total})"

'''@receiver(post_save, sender=Lecon)
def convertir_docx_en_html(sender, instance, **kwargs):
    if instance.fichier and instance.fichier.name.endswith(".docx"):
        with open(instance.fichier.path, "rb") as docx_file:
            result = mammoth.convert_to_html(docx_file)
            html = result.value  # HTML du contenu
            instance.contenu_html = html
            instance.save()'''

