from django.db import models
from django.core.exceptions import PermissionDenied
from django.contrib.auth.models import AbstractUser
from django_summernote.fields import SummernoteTextField


class AppVersion(models.Model):
    version_code = models.IntegerField()  # Exemple: 3
    version_name = models.CharField(max_length=20)  # Exemple: "1.0.3"
    apk_url = models.URLField()  # Lien direct Google Drive ou autre
    changelog = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Version {self.version_name}"


class CustomUser(AbstractUser):
    USER_TYPES = (
        ('admin', 'Administrateur'),
        ('enseignant_admin', 'Enseignant Administrateur'),
        ('enseignant_cadre', 'Enseignant Cadre'),
        ('enseignant_principal', 'Enseignant Principal'),
        ('enseignant', 'Enseignant'),
        ('apprenant', 'Apprenant'),
    )
    user_type = models.CharField(max_length=20, choices=USER_TYPES, default='apprenant')
    name = models.CharField(max_length=100)

    # Champs optionnels pour apprenant (pas utilisés ici)
    cursus = models.CharField(max_length=100, null=True, blank=True)
    sub_cursus = models.CharField(max_length=100, null=True, blank=True)
    niveau = models.CharField(max_length=100, null=True, blank=True)
    filiere = models.CharField(max_length=100, null=True, blank=True)
    licence = models.CharField(max_length=100, null=True, blank=True)

    is_active = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.username} ({self.user_type})"


# --- NIVEAU 1 ---

class Parcours(models.Model):
    nom = models.CharField(max_length=100)
    admin = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'user_type': 'enseignant_admin'},
        related_name='parcours_admin'
    )

    def __str__(self):
        return self.nom

    # ✅ Seulement un admin peut créer un parcours
    @staticmethod
    def create_parcours(user, nom, admin):
        if user.user_type != "admin":
            raise PermissionDenied("Seul un administrateur général peut créer un parcours.")
        return Parcours.objects.create(nom=nom, admin=admin)



# --- NIVEAU 2 ---
class Departement(models.Model):
    nom = models.CharField(max_length=100)
    parcours = models.ForeignKey(Parcours, on_delete=models.CASCADE, related_name="departements")
    cadre = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'user_type': 'enseignant_cadre'},
        related_name='departements_cadre'
    )

    def __str__(self):
        return f"{self.nom} ({self.parcours.nom})"

    # ✅ Seul un enseignant_admin peut créer un département
    @staticmethod
    def create_departement(user, parcours, nom, cadre):
        if user.user_type != "enseignant_admin":
            raise PermissionDenied("Seul un enseignant_admin peut créer un département.")
        return Departement.objects.create(parcours=parcours, nom=nom, cadre=cadre)



# --- NIVEAU 3 ---
class Cours(models.Model):
    titre = models.CharField(max_length=200)
    niveau = models.CharField(max_length=200)   # <= déjà présent
    departement = models.ForeignKey(Departement, on_delete=models.CASCADE, related_name="cours")
    matiere = models.CharField(max_length=255, blank='true')
    concours = models.CharField(max_length=255, blank='true')
    description = models.TextField(blank=True, null=True)
    nb_apprenants = models.PositiveIntegerField(default=0)
    enseignant_principal = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'user_type': 'enseignant_principal'},
        related_name='cours_principal'
    )
    enseignants = models.ManyToManyField(
        CustomUser,
        blank=True,
        limit_choices_to={'user_type': 'enseignant'},
        related_name='cours_secondaires'
    )

    def __str__(self):
        return f"{self.titre} ({self.niveau} - {self.departement.nom})"  # <= affichage amélioré

    # ✅ Seul un enseignant_cadre peut créer un cours
    @staticmethod
    def create_cours(user, departement, titre, niveau, enseignant_principal=None):
        if user.user_type != "enseignant_cadre":
            raise PermissionDenied("Seul un enseignant_cadre peut créer un cours.")
        return Cours.objects.create(
            departement=departement,
            titre=titre,
            niveau=niveau,  # <= ajouté
            enseignant_principal=enseignant_principal
        )

    # ✅ Un enseignant_principal peut ajouter des enseignants
    def add_enseignant(self, user, enseignant):
        if user.user_type != "enseignant_principal":
            raise PermissionDenied("Seul un enseignant_principal peut ajouter des enseignants.")
        if enseignant.user_type != "enseignant":
            raise PermissionDenied("Seuls les enseignants secondaires peuvent être ajoutés.")
        self.enseignants.add(enseignant)

    def nb_lecons(self):
        return self.lecons.count()

    def nb_enseignants(self):
        nb = 1 if self.enseignant_principal else 0
        return nb + self.enseignants.count()

    def __str__(self):
        return self.titre


# --- NIVEAU 4 ---
class Lecon(models.Model):
    titre = models.CharField(max_length=200)
    contenu = SummernoteTextField()
    video = models.FileField(upload_to='video', blank=True, null=True)
    description = models.TextField()
    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, related_name="lecons")
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
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

