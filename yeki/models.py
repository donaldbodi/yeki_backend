from gettext import translation

from django.db import models
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.models import User
#import mammoth
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
import random
from django.db import transaction
import string


class Profile(models.Model):
    USER_TYPES = (
        ('admin', 'Administrateur'),
        ('enseignant_admin', 'Enseignant Administrateur'),
        ('enseignant_cadre', 'Enseignant Cadre'),
        ('enseignant_principal', 'Enseignant Principal'),
        ('enseignant', 'Enseignant'),
        ('apprenant', 'Apprenant'),
    )
    user_type = models.CharField(max_length=20, choices=USER_TYPES, default='Apprenant', blank=True, null=True)
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
    

class PasswordResetOTP(models.Model):
    """
    Code OTP à 6 chiffres envoyé par email pour réinitialiser le mot de passe.
    - Expire après 10 minutes
    - Invalidé après utilisation
    - Maximum 5 tentatives de validation
    """
    user       = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reset_otps',
    )
    code       = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used       = models.BooleanField(default=False)
    attempts   = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'OTP Réinitialisation'

    def save(self, *args, **kwargs):
        if not self.pk:
            # Génère un code à 6 chiffres
            self.code = ''.join(random.choices(string.digits, k=6))
            # Expire dans 10 minutes
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    @property
    def is_valid(self):
        return (
            not self.used
            and self.attempts < 5
            and timezone.now() < self.expires_at
        )

    def __str__(self):
        return f"OTP {self.code} → {self.user.username} ({'✓' if self.used else '⏳'})"



# --- NIVEAU 1 ---

class Parcours(models.Model):
    """
    Parcours de haut niveau créé par l'admin général.
    Exemples : "Cursus Universitaire", "Prépa Concours", "Formations", etc.
    """
    TYPE_CHOICES = [
        ('cursus',      'Cursus scolaire / universitaire'),
        ('prepa',       'Prépa Concours'),
        ('formation',   'Formations professionnelles'),
        ('autre',       'Autre'),
    ]
    nom         = models.CharField(max_length=100)
    type_parcours = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default='autre',
        help_text="Nature du parcours pour guider l'affichage"
    )
    description = models.TextField(blank=True)
    admin       = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'user_type': 'enseignant_admin'},
        related_name='parcours_admin'
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nom} ({self.get_type_parcours_display()})"


# --- NIVEAU 2 ---
class Departement(models.Model):
    """
    Département / filière dans un Parcours.
    Selon le type de parcours parent, des champs supplémentaires s'activent :
      - Prépa Concours → date_limite_inscription, arrete_ministeriel, etc.
      - Formation       → est_formation_metier, est_formation_classique, duree_formation, etc.
      - Cursus          → champs de base uniquement
    """

    # ── Identité ──────────────────────────────────────────────────
    nom       = models.CharField(max_length=200)
    parcours  = models.ForeignKey(
        Parcours, on_delete=models.CASCADE, related_name="departements"
    )
    cadre     = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        limit_choices_to={'user_type': 'enseignant_cadre'},
        related_name='departements_cadre'
    )

    # ── Présentation visuelle (tous les types) ────────────────────
    description = models.TextField(blank=True, help_text="Description détaillée")
    image       = models.ImageField(
        upload_to='departements/images/',
        null=True, blank=True,
        help_text="Image de couverture du département"
    )
    couleur     = models.CharField(
        max_length=7, default='#2884A0',
        help_text="Couleur principale #RRGGBB"
    )
    est_actif   = models.BooleanField(
        default=True,
        help_text="Visible aux apprenants si True"
    )
    prix        = models.PositiveIntegerField(
        default=0,
        help_text="Prix d'accès en FCFA (0 = gratuit)"
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    # ── CHAMPS PRÉPA CONCOURS ──────────────────────────────────────
    # Activés quand parcours.type_parcours == 'prepa'
    est_prepa_concours      = models.BooleanField(
        default=False,
        help_text="True = ce département est un concours à préparer"
    )
    nom_concours            = models.CharField(
        max_length=255, blank=True,
        help_text="Nom officiel du concours (ex: ENS, Polytechnique, BEPC…)"
    )
    organisme_concours      = models.CharField(
        max_length=255, blank=True,
        help_text="Organisme/institution organisateur"
    )
    date_limite_inscription = models.DateField(
        null=True, blank=True,
        help_text="Date limite d'inscription au concours"
    )
    date_examen             = models.DateField(
        null=True, blank=True,
        help_text="Date prévue de l'examen / concours"
    )
    arrete_ministeriel      = models.CharField(
        max_length=255, blank=True,
        help_text="Référence de l'arrêté ministériel d'organisation"
    )
    lien_officiel           = models.URLField(
        blank=True,
        help_text="Site officiel du concours"
    )
    niveaux_cibles          = models.CharField(
        max_length=255, blank=True,
        help_text="Niveaux ciblés ex: Terminale, Licence 3, Master 1"
    )
    places_disponibles      = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Nombre de places au concours (null = non précisé)"
    )
    frais_dossier           = models.PositiveIntegerField(
        default=0,
        help_text="Frais de dossier officiels en FCFA"
    )
    debouches               = models.TextField(
        blank=True,
        help_text="Débouchés après réussite du concours"
    )

    est_valide = models.BooleanField(default=False, help_text="Validé par l'admin du parcours")
    est_refuse = models.BooleanField(default=False, help_text="Refusé par l'admin du parcours")
    motif_refus = models.TextField(blank=True, help_text="Motif du refus")
    valide_le = models.DateTimeField(null=True, blank=True, help_text="Date de validation")

    # Ajouter ces champs pour la gestion des accès
    acces_restreint = models.BooleanField(default=False, help_text="Accès limité aux apprenants sélectionnés")
    apprenants_autorises = models.ManyToManyField(
        User,
        blank=True,
        related_name='formations_autorisees',
        help_text="Apprenants autorisés à accéder à cette formation (si acces_restreint=True)"
    )

    # ── CHAMPS FORMATION ──────────────────────────────────────────
    # Activés quand parcours.type_parcours == 'formation'
    est_formation_metier    = models.BooleanField(
        default=False,
        help_text="True = formation orientée compétences métier"
    )
    est_formation_classique = models.BooleanField(
        default=False,
        help_text="True = formation académique classique (université, grande école…)"
    )
    duree_formation         = models.CharField(
        max_length=100, blank=True,
        help_text="Ex: 6 mois, 2 ans, 200 heures…"
    )
    mode_formation          = models.CharField(
        max_length=20,
        choices=[('presentiel','Présentiel'),('distance','À distance'),('hybride','Hybride')],
        default='hybride', blank=True,
        help_text="Mode de diffusion"
    )
    certificat_delivre      = models.CharField(
        max_length=255, blank=True,
        help_text="Certificat / diplôme délivré à la fin"
    )
    prerequis               = models.TextField(
        blank=True,
        help_text="Prérequis pour intégrer la formation"
    )
    objectifs               = models.TextField(
        blank=True,
        help_text="Objectifs pédagogiques de la formation"
    )
    domaine                 = models.CharField(
        max_length=255, blank=True,
        help_text="Domaine professionnel (Informatique, Gestion, Santé…)"
    )
    ville                   = models.CharField(
        max_length=100, blank=True,
        help_text="Ville principale où se déroule la formation"
    )
    est_certifiante         = models.BooleanField(
        default=False,
        help_text="True si la formation délivre un certificat reconnu"
    )

    class Meta:
        ordering = ['parcours', 'nom']

    def __str__(self):
        return f"{self.nom} ({self.parcours.nom} | cadre: {self.cadre})"

    @property
    def type_departement(self):
        """Retourne le type logique du département."""
        if self.est_prepa_concours:
            return 'prepa_concours'
        if self.est_formation_metier:
            return 'formation_metier'
        if self.est_formation_classique:
            return 'formation_classique'
        return 'cursus'

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
    

class ProgressionLecon(models.Model):
      apprenant    = models.ForeignKey(User, on_delete=models.CASCADE,
                                       related_name='progressions')
      lecon        = models.ForeignKey(Lecon, on_delete=models.CASCADE,
                                       related_name='progressions')
      cours        = models.ForeignKey(Cours, on_delete=models.CASCADE,
                                       related_name='progressions')
      pourcentage  = models.PositiveSmallIntegerField(default=0)
                     # 0-100
      derniere_vue = models.DateTimeField(auto_now=True)
      terminee     = models.BooleanField(default=False)

      class Meta:
          unique_together = ('apprenant', 'lecon')
          ordering = ['-derniere_vue']

      def __str__(self):
          return f"{self.apprenant.username} → {self.lecon.titre} ({self.pourcentage}%)"


class LeconLike(models.Model):
    """Like d'une leçon par un apprenant"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lecon_likes')
    lecon = models.ForeignKey(Lecon, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'lecon')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} → {self.lecon.titre}"


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


# ─────────────────────────────────────────────────────────────────
# DEVOIR GÉNÉRAL (cursus, concours, formation classique/métier)
# ─────────────────────────────────────────────────────────────────

class Devoir(models.Model):

    # ── Type de devoir ──────────────────────────────────────────
    TYPE_CHOICES = [
        ("cursus",           "Devoir de cursus"),
        ("concours",         "Préparation concours"),
        ("formation_classique", "Formation classique"),
        ("formation_metier", "Formation métier"),
        ("olympiade",        "Olympiade"),
    ]

    MATIERE_CHOICES = [
        ("Mathématiques",    "Mathématiques"),
        ("Physique",         "Physique"),
        ("Chimie",           "Chimie"),
        ("SVT",              "SVT"),
        ("Informatique",     "Informatique"),
        ("Français",         "Français"),
        ("Anglais",          "Anglais"),
        ("Histoire-Géo",     "Histoire-Géo"),
        ("Philosophie",      "Philosophie"),
        ("Économie",         "Économie"),
        ("Autre",            "Autre"),
    ]

    NIVEAU_CHOICES = [
        ("Terminale", "Terminale"),
        ("1ère",      "1ère"),
        ("2nde",      "2nde"),
        ("3ème",      "3ème"),
        ("Licence 1", "Licence 1"),
        ("Licence 2", "Licence 2"),
        ("Licence 3", "Licence 3"),
        ("Master 1",  "Master 1"),
        ("Master 2",  "Master 2"),
        ("Autre",     "Autre"),
    ]

    # ── Champs de base ───────────────────────────────────────────
    titre        = models.CharField(max_length=255)
    description  = models.TextField(blank=True)
    type_devoir  = models.CharField(max_length=25, choices=TYPE_CHOICES, default="cursus")
    matiere      = models.CharField(max_length=100, choices=MATIERE_CHOICES)
    niveau       = models.CharField(max_length=50, choices=NIVEAU_CHOICES, default="Terminale")
    enonce       = models.TextField()

    # ── Dates ────────────────────────────────────────────────────
    date_creation  = models.DateTimeField(auto_now_add=True)
    date_debut     = models.DateTimeField(default=timezone.now,
                                          help_text="Quand le devoir devient visible/accessible")
    date_limite    = models.DateTimeField(help_text="Date de remise obligatoire")

    # ── Concours / Formation ─────────────────────────────────────
    concours_lie   = models.CharField(max_length=255, blank=True, null=True,
                                       help_text="Ex: BEPC, BAC, Concours ENS…")
    formation_liee = models.CharField(max_length=255, blank=True, null=True,
                                       help_text="Nom de la formation liée")

    # ── Paramètres pédagogiques ──────────────────────────────────
    duree_minutes       = models.PositiveIntegerField(default=60,
                                                       help_text="Durée max de composition en minutes")
    tentatives_max      = models.PositiveIntegerField(default=1)
    note_sur            = models.PositiveIntegerField(default=20)
    coefficient         = models.FloatField(default=1.0)

    # ── Visibilité & accès ───────────────────────────────────────
    est_publie          = models.BooleanField(default=False)
    acces_restreint     = models.BooleanField(default=False,
                                               help_text="Si True, seuls les apprenants du cursus lié peuvent y accéder")
    cours_lie           = models.ForeignKey(
                            "Cours", on_delete=models.SET_NULL,
                            null=True, blank=True, related_name="devoirs"
                          )
    TYPE_CORRECTION_CHOICES = [
        ('auto',   'Correction automatique'),
        ('manuel', 'Correction manuelle'),
    ]
    type_correction = models.CharField(
        max_length=10,
        choices=TYPE_CORRECTION_CHOICES,
        default='auto',
        help_text='auto = QCM/texte exact corrigé auto ; manuel = enseignant corrige',
    )

    # ── Auteur ───────────────────────────────────────────────────
    cree_par = models.ForeignKey(
        "Profile", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="devoirs_crees"
    )

    class Meta:
        ordering = ["-date_limite"]

    def __str__(self):
        return f"[{self.get_type_devoir_display()}] {self.titre}"

    @property
    def est_ouvert(self):
        now = timezone.now()
        return self.date_debut <= now <= self.date_limite

    @property
    def est_expire(self):
        return timezone.now() > self.date_limite

    def clean(self):
        if self.date_debut and self.date_limite:
            if self.date_limite <= self.date_debut:
                raise ValidationError("La date limite doit être après la date de début.")


# ─────────────────────────────────────────────────────────────────
# QUESTIONS D'UN DEVOIR  (QCM ou texte libre)
# ─────────────────────────────────────────────────────────────────

class QuestionDevoir(models.Model):
    TYPE_CHOICES = [
        ("qcm",   "QCM"),
        ("texte", "Texte libre"),
    ]
    devoir         = models.ForeignKey(Devoir, on_delete=models.CASCADE, related_name="questions")
    texte          = models.TextField()
    type_question  = models.CharField(max_length=10, choices=TYPE_CHOICES)
    points         = models.FloatField(default=1.0)
    ordre          = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["ordre"]

    def __str__(self):
        return f"Q{self.ordre} — {self.texte[:60]}"


class ChoixReponse(models.Model):
    question     = models.ForeignKey(QuestionDevoir, on_delete=models.CASCADE, related_name="choix")
    texte        = models.CharField(max_length=500)
    est_correct  = models.BooleanField(default=False)

    def __str__(self):
        return f"{'✓' if self.est_correct else '✗'} {self.texte[:40]}"


# ─────────────────────────────────────────────────────────────────
# SOUMISSION  (une par apprenant par devoir)
# ─────────────────────────────────────────────────────────────────

class SoumissionDevoir(models.Model):
    STATUT_CHOICES = [
        ("en_cours",    "En cours"),
        ("soumis",      "Soumis"),
        ("en_retard",   "En retard"),
        ("corrige",     "Corrigé"),
    ]

    utilisateur     = models.ForeignKey(User, on_delete=models.CASCADE, related_name="soumissions")
    devoir          = models.ForeignKey(Devoir, on_delete=models.CASCADE, related_name="soumissions")
    statut          = models.CharField(max_length=15, choices=STATUT_CHOICES, default="en_cours")

    # ── Timestamps ──────────────────────────────────────────────
    debut           = models.DateTimeField(auto_now_add=True)
    soumis_le       = models.DateTimeField(null=True, blank=True)

    # ── Résultats ────────────────────────────────────────────────
    note            = models.FloatField(null=True, blank=True)
    commentaire     = models.TextField(blank=True)
    corrige_par     = models.ForeignKey(
                        User, on_delete=models.SET_NULL,
                        null=True, blank=True, related_name="corrections"
                      )
    corrige_le      = models.DateTimeField(null=True, blank=True)

    fichier_soumis = models.FileField(
        upload_to='soumissions_devoirs/',
        null=True,
        blank=True,
        help_text='Fichier PDF soumis par l\'apprenant (correction manuelle)',
    )

    # ── Anti-triche ──────────────────────────────────────────────
    nb_focus_perdu  = models.PositiveIntegerField(default=0,
                                                    help_text="Nombre de fois que l'apprenant a quitté la page")
    ip_address      = models.GenericIPAddressField(null=True, blank=True)
    user_agent      = models.TextField(blank=True)
    est_suspecte    = models.BooleanField(default=False)

    class Meta:
        unique_together = ("utilisateur", "devoir")

    def __str__(self):
        return f"{self.utilisateur.username} → {self.devoir.titre} [{self.statut}]"

    @property
    def est_en_retard(self):
        if self.soumis_le and self.devoir.date_limite:
            return self.soumis_le > self.devoir.date_limite
        return False

    def temps_restant_secondes(self):
        if self.statut != "en_cours":
            return 0
        elapsed = (timezone.now() - self.debut).total_seconds()
        return max(0, self.devoir.duree_minutes * 60 - elapsed)


class ReponseDevoir(models.Model):
    """Stocke la réponse d'un apprenant à une question."""
    soumission  = models.ForeignKey(SoumissionDevoir, on_delete=models.CASCADE, related_name="reponses")
    question    = models.ForeignKey(QuestionDevoir, on_delete=models.CASCADE)
    reponse     = models.TextField(blank=True)     # texte libre OU texte du choix sélectionné
    choix       = models.ForeignKey(ChoixReponse, on_delete=models.SET_NULL,
                                     null=True, blank=True)  # pour QCM
    est_correct = models.BooleanField(null=True, blank=True)  # rempli à la correction
    points_obtenus = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ("soumission", "question")


# ─────────────────────────────────────────────────────────────────
# OLYMPIADE  (type spécial avec logique propre)
# ─────────────────────────────────────────────────────────────────

class Olympiade(models.Model):
    STATUT_CHOICES = [
        ("inscription",  "Inscriptions ouvertes"),
        ("fermee",       "Inscriptions fermées"),
        ("en_cours",     "Olympiade en cours"),
        ("terminee",     "Terminée"),
    ]

    # ── Identité ─────────────────────────────────────────────────
    titre        = models.CharField(max_length=255)
    description  = models.TextField(blank=True)
    matiere      = models.CharField(max_length=100)
    niveau       = models.CharField(max_length=50)
    edition      = models.CharField(max_length=20, blank=True, help_text="Ex: 2025-1")

    # ── Dates ────────────────────────────────────────────────────
    date_ouverture_inscription = models.DateTimeField()
    date_cloture_inscription   = models.DateTimeField()
    date_debut_olympiade       = models.DateTimeField()
    date_fin_olympiade         = models.DateTimeField()

    # ── Paramètres de composition ────────────────────────────────
    duree_minutes        = models.PositiveIntegerField(default=120)
    nb_questions         = models.PositiveIntegerField(default=30)
    note_sur             = models.PositiveIntegerField(default=20)
    melanger_questions   = models.BooleanField(default=True,
                                                help_text="Mélange l'ordre des questions par participant")
    melanger_choix       = models.BooleanField(default=True,
                                                help_text="Mélange les choix QCM par participant")
    une_seule_session    = models.BooleanField(default=True,
                                                help_text="Impossible de reprendre si on quitte")
    max_focus_perdu      = models.PositiveIntegerField(default=3,
                                                        help_text="Nb d'abandons de focus avant soumission forcée")

    # ── Devoir lié ───────────────────────────────────────────────
    devoir = models.OneToOneField(
        Devoir, on_delete=models.CASCADE,
        related_name="olympiade_config",
        null=True, blank=True,
        help_text="Le devoir contenant les questions de l'olympiade"
    )

    # ── Prix / Récompenses ───────────────────────────────────────
    prix_1er    = models.CharField(max_length=255, blank=True)
    prix_2eme   = models.CharField(max_length=255, blank=True)
    prix_3eme   = models.CharField(max_length=255, blank=True)

    # ── Auteur ───────────────────────────────────────────────────
    organisateur = models.ForeignKey(
        "Profile", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="olympiades_organisees"
    )

    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )

    # ---validation olympiade ----
    est_validee = models.BooleanField(default=False)  # Validée par l'admin
    est_refusee = models.BooleanField(default=False)   # Refusée par l'admin
    motif_refus = models.TextField(blank=True)         # Motif du refus
    validee_le = models.DateTimeField(null=True, blank=True)  # Date de validatio
    

    class Meta:
        ordering = ["-date_debut_olympiade"]

    def __str__(self):
        return f"Olympiade {self.titre} — {self.edition}"

    @property
    def statut_auto(self):
        now = timezone.now()
        if now < self.date_ouverture_inscription:
            return "bientot"
        if now <= self.date_cloture_inscription:
            return "inscription"
        if now < self.date_debut_olympiade:
            return "fermée"
        if now <= self.date_fin_olympiade:
            return "en_cours"
        return "terminée"

    def clean(self):
        if self.date_cloture_inscription >= self.date_debut_olympiade:
            raise ValidationError("La clôture des inscriptions doit être avant le début de l'olympiade.")
        if self.date_debut_olympiade >= self.date_fin_olympiade:
            raise ValidationError("La date de début doit être avant la date de fin.")


class InscriptionOlympiade(models.Model):
    """Inscription d'un apprenant à une olympiade."""
    STATUT_CHOICES = [
        ("inscrit",    "Inscrit"),
        ("confirme",   "Confirmé"),
        ("disqualifie","Disqualifié"),
    ]

    olympiade   = models.ForeignKey(Olympiade, on_delete=models.CASCADE, related_name="inscriptions")
    apprenant   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="inscriptions_olympiade")
    statut      = models.CharField(max_length=15, choices=STATUT_CHOICES, default="inscrit")
    inscrit_le  = models.DateTimeField(auto_now_add=True)

    # ── Session de composition ───────────────────────────────────
    session_demarree    = models.BooleanField(default=False)
    heure_debut_compo   = models.DateTimeField(null=True, blank=True)
    heure_fin_compo     = models.DateTimeField(null=True, blank=True)
    soumis              = models.BooleanField(default=False)
    soumis_automatique  = models.BooleanField(default=False,
                                               help_text="True si soumis automatiquement (temps écoulé / triche)")

    # ── Anti-triche ──────────────────────────────────────────────
    nb_focus_perdu      = models.PositiveIntegerField(default=0)
    ip_inscription      = models.GenericIPAddressField(null=True, blank=True)
    ip_composition      = models.GenericIPAddressField(null=True, blank=True)
    user_agent          = models.TextField(blank=True)
    est_suspecte        = models.BooleanField(default=False)
    raison_suspicion    = models.TextField(blank=True)

    # ── Résultat ─────────────────────────────────────────────────
    note        = models.FloatField(null=True, blank=True)
    classement  = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("olympiade", "apprenant")

    def __str__(self):
        return f"{self.apprenant.username} @ {self.olympiade.titre}"

    def temps_restant_secondes(self):
        if not self.heure_debut_compo or self.soumis:
            return 0
        elapsed = (timezone.now() - self.heure_debut_compo).total_seconds()
        return max(0, self.olympiade.duree_minutes * 60 - elapsed)


class ReponseOlympiade(models.Model):
    """Réponse d'un participant à une question de l'olympiade."""
    inscription  = models.ForeignKey(InscriptionOlympiade, on_delete=models.CASCADE, related_name="reponses")
    question     = models.ForeignKey(QuestionDevoir, on_delete=models.CASCADE)
    choix        = models.ForeignKey(ChoixReponse, on_delete=models.SET_NULL, null=True, blank=True)
    reponse_texte = models.TextField(blank=True)
    est_correct  = models.BooleanField(null=True, blank=True)
    points_obtenus = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ("inscription", "question")


class ClassementOlympiade(models.Model):
    """Classement final calculé après correction."""
    olympiade   = models.ForeignKey(Olympiade, on_delete=models.CASCADE, related_name="classement")
    apprenant   = models.ForeignKey(User, on_delete=models.CASCADE)
    rang        = models.PositiveIntegerField()
    note        = models.FloatField()
    mention     = models.CharField(max_length=50, blank=True)  # Or, Argent, Bronze…

    class Meta:
        ordering = ["rang"]
        unique_together = ("olympiade", "apprenant")


# ─────────────────────────────────────────────────────────────────
# QUESTION FORUM
# Peut être liée à une leçon, un exercice ou un devoir
# ─────────────────────────────────────────────────────────────────
class QuestionForum(models.Model):
    SOURCE_CHOICES = [
        ("lecon",    "Leçon"),
        ("exercice", "Exercice"),
        ("devoir",   "Devoir"),
        ("libre",    "Question libre"),
    ]

    auteur          = models.ForeignKey(User, on_delete=models.CASCADE, related_name="questions_forum")
    contenu         = models.TextField()
    source          = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="libre")
    cree_le         = models.DateTimeField(auto_now_add=True)
    modifie_le      = models.DateTimeField(auto_now=True)

    # Liens optionnels
    lecon_id        = models.IntegerField(null=True, blank=True)
    lecon_titre     = models.CharField(max_length=255, blank=True)
    cours_id        = models.IntegerField(null=True, blank=True)
    cours_titre     = models.CharField(max_length=255, blank=True)
    exercice_id     = models.IntegerField(null=True, blank=True)
    exercice_titre  = models.CharField(max_length=255, blank=True)
    devoir_id       = models.IntegerField(null=True, blank=True)
    devoir_titre    = models.CharField(max_length=255, blank=True)

    est_resolue     = models.BooleanField(default=False)
    nb_vues         = models.IntegerField(default=0)

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self):
        return f"[{self.source}] {self.auteur.username} — {self.contenu[:60]}"



# ─────────────────────────────────────────────────────────────────
# RÉPONSE À UNE QUESTION
# ─────────────────────────────────────────────────────────────────

class ReponseQuestion(models.Model):
    question        = models.ForeignKey(QuestionForum, on_delete=models.CASCADE, related_name="reponses")
    auteur          = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reponses_forum")
    contenu         = models.TextField()
    cree_le         = models.DateTimeField(auto_now_add=True)
    est_solution    = models.BooleanField(default=False)

    class Meta:
        ordering = ["cree_le"]

    def __str__(self):
        return f"Réponse de {self.auteur.username} à Q{self.question.id}"


# ─────────────────────────────────────────────────────────────────
# LIKE sur une réponse
# ─────────────────────────────────────────────────────────────────

class LikeReponse(models.Model):
    reponse         = models.ForeignKey(ReponseQuestion, on_delete=models.CASCADE, related_name="likes")
    utilisateur     = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("reponse", "utilisateur")

        
'''@receiver(post_save, sender=Lecon)
def convertir_docx_en_html(sender, instance, **kwargs):
    if instance.fichier and instance.fichier.name.endswith(".docx"):
        with open(instance.fichier.path, "rb") as docx_file:
            result = mammoth.convert_to_html(docx_file)
            html = result.value  # HTML du contenu
            instance.contenu_html = html
            instance.save()'''


# ─────────────────────────────────────────────────────────────────
# HISTORIQUE DES ACTIVITÉS
# Enregistre toutes les actions importantes des enseignants
# ─────────────────────────────────────────────────────────────────

class HistoriqueActivite(models.Model):
    """
    Journal des actions importantes réalisées par les utilisateurs.
    Créé automatiquement via des signals ou manuellement via le helper
    `enregistrer_activite(...)`.
    """

    ACTION_CHOICES = [
        # ── Cours ───────────────────────────────────────────────
        ('course_created',       'Cours créé'),
        ('course_modified',      'Cours modifié'),
        ('course_deleted',       'Cours supprimé'),

        # ── Enseignants ─────────────────────────────────────────
        ('teacher_assigned',     'Enseignant principal assigné'),
        ('teacher_changed',      'Enseignant principal changé'),
        ('secondary_added',      'Enseignant secondaire ajouté'),
        ('secondary_removed',    'Enseignant secondaire retiré'),

        # ── Modules ─────────────────────────────────────────────
        ('module_created',       'Module créé'),
        ('module_modified',      'Module modifié'),
        ('module_deleted',       'Module supprimé'),

        # ── Leçons ──────────────────────────────────────────────
        ('lesson_created',       'Leçon créée'),
        ('lesson_modified',      'Leçon modifiée'),
        ('lesson_deleted',       'Leçon supprimée'),

        # ── Devoirs ─────────────────────────────────────────────
        ('homework_created',     'Devoir créé'),
        ('homework_modified',    'Devoir modifié'),
        ('homework_graded',      'Devoir corrigé'),

        # ── Exercices ────────────────────────────────────────────
        ('exercise_created',     'Exercice créé'),
        ('question_added',       'Question ajoutée'),

        # ── Olympiades ───────────────────────────────────────────
        ('olympiad_created',     'Olympiade créée'),
        ('olympiad_closed',      'Olympiade clôturée'),
        ('ranking_computed',     'Classement calculé'),

        # ── Département / Parcours ───────────────────────────────
        ('department_created',   'Département créé'),
        ('cadre_assigned',       'Cadre assigné'),

        # ── Soumissions ──────────────────────────────────────────
        ('submission_graded',    'Soumission corrigée'),

        # ── Connexion ────────────────────────────────────────────
        ('login',                'Connexion'),
        ('logout',               'Déconnexion'),
    ]

    user        = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='historique_activites',
    )
    action      = models.CharField(max_length=50, choices=ACTION_CHOICES)
    description = models.TextField(blank=True)

    # Données contextuelles JSON (titre du cours, nom de l'enseignant, etc.)
    data        = models.JSONField(default=dict, blank=True)

    timestamp   = models.DateTimeField(auto_now_add=True)

    # Référence optionnelle vers l'objet concerné
    objet_id    = models.PositiveIntegerField(null=True, blank=True)
    objet_type  = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Activité'
        verbose_name_plural = 'Historique des activités'

    def __str__(self):
        return f"[{self.user.username}] {self.get_action_display()} — {self.timestamp:%d/%m/%Y %H:%M}"


# ─────────────────────────────────────────────────────────────────
# HELPER : enregistrer une activité facilement depuis n'importe
#          quelle view
# ─────────────────────────────────────────────────────────────────

def enregistrer_activite(
    user,
    action: str,
    description: str = '',
    data: dict = None,
    objet_id: int = None,
    objet_type: str = '',
):
    """
    Crée une entrée HistoriqueActivite.

    Usage dans une view :
        from .models import enregistrer_activite
        enregistrer_activite(
            user=request.user,
            action='course_created',
            description=f"Cours '{cours.titre}' créé",
            data={'titre': cours.titre, 'niveau': cours.niveau},
            objet_id=cours.id,
            objet_type='Cours',
        )
    """
    try:
        HistoriqueActivite.objects.create(
            user        = user,
            action      = action,
            description = description,
            data        = data or {},
            objet_id    = objet_id,
            objet_type  = objet_type,
        )
    except Exception:
        pass   # Ne jamais bloquer une view à cause du journal

class Paiement(models.Model):
    """
    Registre centralisé de tous les paiements Yeki.
    Couvre : abonnements, prépa concours (accès au dept), olympiades payantes.
    Commission Yeki : 15% sur tout paiement lié à un département payant.
    """
    TYPE_CHOICES = [
        ('abonnement_mensuel',  'Abonnement mensuel cursus'),
        ('abonnement_annuel',   'Abonnement annuel cursus'),
        ('acces_departement',   'Accès département (concours/formation)'),
        ('olympiade',           'Participation olympiade'),
    ]
    MOYEN_CHOICES = [
        ('mtn_momo',  'MTN Mobile Money'),
        ('orange_om', 'Orange Money'),
        ('carte',     'Carte bancaire'),
    ]
    STATUT_CHOICES = [
        ('en_attente', 'En attente'),
        ('succes',     'Succès'),
        ('echec',      'Échec'),
        ('rembourse',  'Remboursé'),
    ]

    utilisateur    = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='paiements')
    type_paiement  = models.CharField(max_length=25, choices=TYPE_CHOICES)
    moyen          = models.CharField(max_length=15, choices=MOYEN_CHOICES)
    montant        = models.PositiveIntegerField(help_text="Montant en FCFA")
    statut         = models.CharField(
        max_length=15, choices=STATUT_CHOICES, default='en_attente')
    reference      = models.CharField(max_length=100, unique=True, blank=True)
    date           = models.DateTimeField(auto_now_add=True)
    transaction_id = models.CharField(
        max_length=200, blank=True, help_text="ID transaction opérateur")

    # Lien optionnel vers olympiade (pour participation payante)
    olympiade_liee = models.ForeignKey(
        Olympiade, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='paiements')

    # Commission Yeki prélevée (15% si paiement > 0 pour département)
    commission_yeki = models.PositiveIntegerField(
        default=0, help_text="Part Yeki en FCFA")

    class Meta:
        ordering = ['-date']
        verbose_name = 'Paiement'

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"YEKI-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} – {self.utilisateur.username} – {self.montant} FCFA [{self.statut}]"


# ══════════════════════════════════════════════════════════════════
# ABONNEMENT PREMIUM
# ══════════════════════════════════════════════════════════════════

class AbonnementPremium(models.Model):
    """
    Abonnement premium d'un apprenant au cursus.
    1 500 FCFA/mois ou 13 000 FCFA/an.
    Donne accès aux vidéos, exercices, devoirs, forum et Yeki IA.
    """
    TYPE_CHOICES = [
        ('mensuel', 'Mensuel – 1 500 FCFA'),
        ('annuel',  'Annuel – 13 000 FCFA'),
    ]
    TARIFS = {'mensuel': 1500, 'annuel': 13000}

    utilisateur     = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='abonnement')
    type_abonnement = models.CharField(max_length=10, choices=TYPE_CHOICES)
    actif           = models.BooleanField(default=True)
    debut           = models.DateTimeField(auto_now_add=True)
    fin             = models.DateTimeField()
    paiement        = models.ForeignKey(
        Paiement, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-debut']
        verbose_name = 'Abonnement Premium'

    def __str__(self):
        return (f"{self.utilisateur.username} – "
                f"{self.type_abonnement} (expire {self.fin:%d/%m/%Y})")

    @property
    def est_actif(self):
        return self.actif and timezone.now() < self.fin

    def renouveler(self, type_abonnement: str):
        self.type_abonnement = type_abonnement
        jours = 30 if type_abonnement == 'mensuel' else 365
        self.fin = timezone.now() + timedelta(days=jours)
        self.actif = True
        self.save()


# ══════════════════════════════════════════════════════════════════
# YEKI IA — PERSONNALITÉ PAR CONTEXTE
# ══════════════════════════════════════════════════════════════════

class YekiIAPersonalite(models.Model):
    """
    Personnalité de Yeki IA pour un contexte donné.
    Contexte = parcours (nom), cours, ou niveau.
    Pas de FK vers des modèles inexistants.
    """
    CONTEXTE_CHOICES = [
        ('cursus_niveau',  'Niveau dans le cursus'),
        ('parcours',       'Parcours complet (Prépa Concours, Formations…)'),
        ('cours',          'Cours spécifique'),
        ('olympiade',      'Olympiade'),
    ]
    STYLE_CHOICES = [
        ('pedagogique',   'Pédagogique (explications détaillées)'),
        ('socratique',    'Socratique (questions pour guider)'),
        ('direct',        'Direct (réponses concises)'),
        ('encourageant',  'Encourageant (bienveillant et motivant)'),
        ('academique',    'Académique (rigoureux et formel)'),
        ('professionnel', 'Professionnel (orienté compétences)'),
    ]
    NIVEAU_DIFFICULTE_CHOICES = [
        ('debutant',      'Débutant'),
        ('intermediaire', 'Intermédiaire'),
        ('avance',        'Avancé'),
    ]

    nom               = models.CharField(max_length=200)
    contexte          = models.CharField(max_length=20, choices=CONTEXTE_CHOICES)
    style             = models.CharField(
        max_length=20, choices=STYLE_CHOICES, default='pedagogique')
    niveau_difficulte = models.CharField(
        max_length=15, choices=NIVEAU_DIFFICULTE_CHOICES, default='intermediaire')

    # Liens optionnels — cours ou niveau texte
    cours_lie     = models.ForeignKey(
        Cours, on_delete=models.CASCADE,
        null=True, blank=True, related_name='ia_personnalites')
    # Pour les parcours : on stocke simplement le nom du parcours
    nom_parcours  = models.CharField(
        max_length=100, blank=True,
        help_text="Nom du Parcours (ex: 'Prépa Concours', 'Formations')")
    niveau_cursus = models.CharField(
        max_length=50, blank=True,
        help_text="Ex: Terminale, 3ème…")

    # Prompt et cache
    prompt_systeme       = models.TextField(blank=True)
    contexte_cours_cache = models.TextField(blank=True)
    cache_updated_at     = models.DateTimeField(null=True, blank=True)
    created_at           = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Personnalité IA'
        verbose_name_plural = 'Personnalités IA'

    def __str__(self):
        return f"[{self.get_contexte_display()}] {self.nom}"

    def build_system_prompt(self) -> str:
        style_desc = {
            'pedagogique':   "Tu expliques chaque concept en détail avec des exemples concrets.",
            'socratique':    "Tu guides par des questions plutôt que donner directement la réponse.",
            'direct':        "Tu donnes des réponses concises et précises.",
            'encourageant':  "Tu es très bienveillant et tu encourages l'apprenant.",
            'academique':    "Tu utilises un vocabulaire rigoureux et académique.",
            'professionnel': "Tu orientes vers les compétences pratiques et professionnelles.",
        }
        niveau_desc = {
            'debutant':      "Utilise un langage simple, évite le jargon technique.",
            'intermediaire': "Utilise un langage adapté à un niveau intermédiaire.",
            'avance':        "Tu peux utiliser la terminologie experte du domaine.",
        }
        prompt = (
            "Tu es Yéki IA, l'assistant pédagogique de la plateforme Yéki.\n"
            "Tu réponds TOUJOURS en commençant par \"Yeki IA :\" suivi de ta réponse.\n"
            "Tu t'exprimes en français.\n\n"
            f"STYLE : {style_desc.get(self.style, '')}\n"
            f"NIVEAU : {niveau_desc.get(self.niveau_difficulte, '')}\n"
        )
        if self.niveau_cursus:
            prompt += f"\nTu t'adresses à des apprenants de niveau {self.niveau_cursus}.\n"
        if self.nom_parcours:
            prompt += f"\nContexte : parcours '{self.nom_parcours}'.\n"
        if self.prompt_systeme:
            prompt += f"\nINSTRUCTIONS SPÉCIFIQUES :\n{self.prompt_systeme}\n"
        if self.contexte_cours_cache:
            prompt += f"\nCONTEXTE :\n{self.contexte_cours_cache[:3000]}\n"
        prompt += (
            "\nRÈGLES : réponds uniquement aux questions liées à la formation/au cours. "
            "N'invente jamais de faits. Pour les exercices, aide à comprendre sans donner "
            "la réponse brute.\n"
        )
        return prompt




# ══════════════════════════════════════════════════════════════════
# YEKI IA — HISTORIQUE DES CONVERSATIONS PRIVÉES
# Une conversation par (apprenant, cours)
# ══════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════
# YEKI WALLET — PORTEFEUILLE UTILISATEUR
# Chaque utilisateur possède un portefeuille rechargeable.
# Sert à payer : IA (débit auto), cours, formations, olympiades.
# La commission Yeki (IA) va dans le compte principal Yeki.
# ══════════════════════════════════════════════════════════════════

# Tarification IA Yeki
TARIF_IA_PAR_TOKEN = 0.002          # 0.002 FCFA par token OpenAI (gpt-3.5-turbo)
COMMISSION_YEKI_IA = 5              # 5 FCFA commission Yeki par requête IA
TARIF_IA_MIN_PAR_REQUETE = 10       # minimum 10 FCFA par requête IA


class YekiWallet(models.Model):
    """Portefeuille rechargeable de l'utilisateur."""
    utilisateur = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='wallet'
    )
    solde       = models.PositiveIntegerField(
        default=0, help_text="Solde en FCFA"
    )
    total_recharge  = models.PositiveIntegerField(default=0)
    total_depense   = models.PositiveIntegerField(default=0)
    cree_le         = models.DateTimeField(auto_now_add=True)
    modifie_le      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Portefeuille Yéki'

    def __str__(self):
        return f"{self.utilisateur.username} — {self.solde} FCFA"

    def peut_debiter(self, montant: int) -> bool:
        return self.solde >= montant

    @transaction.atomic
    def debiter(self, montant: int, description: str = '') -> bool:
        if not self.peut_debiter(montant):
            return False
        self.solde          -= montant
        self.total_depense  += montant
        self.save(update_fields=['solde', 'total_depense', 'modifie_le'])
        WalletTransaction.objects.create(
            wallet=self, type_transaction='debit',
            montant=montant, description=description
        )
        return True

    @transaction.atomic
    def crediter(self, montant: int, description: str = '', reference: str = ''):
        self.solde          += montant
        self.total_recharge += montant
        self.save(update_fields=['solde', 'total_recharge', 'modifie_le'])
        WalletTransaction.objects.create(
            wallet=self, type_transaction='credit',
            montant=montant, description=description,
            reference_paiement=reference,
        )

    @classmethod
    def get_or_create_wallet(cls, user):
        wallet, _ = cls.objects.get_or_create(utilisateur=user)
        return wallet


class WalletTransaction(models.Model):
    """Historique des mouvements du portefeuille."""
    TYPE_CHOICES = [
        ('credit', 'Crédit (recharge)'),
        ('debit',  'Débit (dépense)'),
    ]
    wallet             = models.ForeignKey(
        YekiWallet, on_delete=models.CASCADE, related_name='transactions'
    )
    type_transaction   = models.CharField(max_length=10, choices=TYPE_CHOICES)
    montant            = models.PositiveIntegerField()
    description        = models.CharField(max_length=255, blank=True)
    reference_paiement = models.CharField(max_length=100, blank=True)
    cree_le            = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-cree_le']
        verbose_name = 'Transaction Wallet'

    def __str__(self):
        sign = '+' if self.type_transaction == 'credit' else '-'
        return f"{sign}{self.montant} FCFA — {self.description}"


class YekiCompteIA(models.Model):
    """
    Compte central Yeki alimenté par les commissions sur l'IA.
    Singleton (id=1). Consultation admin uniquement.
    """
    total_commissions = models.PositiveIntegerField(default=0)
    nb_requetes_ia    = models.PositiveIntegerField(default=0)
    modifie_le        = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Compte Central Yéki IA'

    @classmethod
    def crediter_commission(cls, montant: int):
        obj, _ = cls.objects.get_or_create(pk=1)
        obj.total_commissions += montant
        obj.nb_requetes_ia    += 1
        obj.save(update_fields=['total_commissions', 'nb_requetes_ia', 'modifie_le'])

    def __str__(self):
        return f"Compte Yéki IA — {self.total_commissions} FCFA ({self.nb_requetes_ia} requêtes)"


class YekiIAChatHistorique(models.Model):
    """
    Message dans la conversation privée apprenant ↔ Yeki IA,
    dans le contexte d'un cours.
    """
    ROLE_CHOICES = [('user', 'Apprenant'), ('assistant', 'Yeki IA')]

    apprenant   = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='ia_chat_historique'
    )
    cours       = models.ForeignKey(
        Cours, on_delete=models.CASCADE,
        related_name='ia_chat_messages'
    )
    role        = models.CharField(max_length=10, choices=ROLE_CHOICES)
    contenu     = models.TextField()
    # Source optionnelle (lecon, exercice, devoir)
    source      = models.CharField(
        max_length=20, blank=True,
        help_text="lecon | exercice | devoir | libre"
    )
    source_id   = models.IntegerField(null=True, blank=True)
    source_titre = models.CharField(max_length=255, blank=True)
    # Image jointe (optionnel)
    image       = models.ImageField(
        upload_to='ia_chat_images/', null=True, blank=True
    )
    cree_le     = models.DateTimeField(auto_now_add=True)
    tokens      = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['cree_le']
        verbose_name = 'Message IA Chat'

    def __str__(self):
        return f"[{self.role}] {self.apprenant.username} — {self.cours.titre} — {self.cree_le:%d/%m %H:%M}"


# models.py - Transaction


class CinetPayTransaction(models.Model):
    """Transaction CinetPay"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cinetpay_transactions')
    amount = models.PositiveIntegerField()
    reference = models.CharField(max_length=100, unique=True)
    transaction_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'En attente'),
        ('success', 'Succès'),
        ('failed', 'Échec'),
    ], default='pending')
    payment_method = models.CharField(max_length=20, choices=[
        ('mtn_momo', 'MTN Mobile Money'),
        ('orange_money', 'Orange Money'),
        ('card', 'Carte bancaire'),
    ], blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"CinetPay {self.reference} - {self.status}"
    

# models.py - Ajouter à la fin du fichier

class AppVersion(models.Model):
    """
    Gestion des versions de l'application pour les mises à jour.
    """
    PLATFORM_CHOICES = [
        ('android', 'Android'),
        ('ios', 'iOS'),
        ('desktop', 'Desktop'),
        ('web', 'Web'),
    ]
    
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='android')
    version_code = models.PositiveIntegerField(help_text="Numéro de version interne (ex: 2, 3, 4...)")
    version_name = models.CharField(max_length=20, help_text="Nom de version (ex: v1.0.3)")
    download_url = models.URLField(help_text="URL de téléchargement de l'APK/EXE/DMG")
    changelog = models.TextField(blank=True, help_text="Description des nouveautés")
    min_version_code = models.PositiveIntegerField(default=1, help_text="Version minimale requise")
    force_update = models.BooleanField(default=False, help_text="Si True, oblige l'utilisateur à mettre à jour")
    is_active = models.BooleanField(default=True, help_text="Version active/public")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-version_code']
        verbose_name = "Version de l'application"
        verbose_name_plural = "Versions de l'application"
        unique_together = ('platform', 'version_code')
    
    def __str__(self):
        return f"{self.get_platform_display()} - {self.version_name} (code: {self.version_code})"
