from django.db import models
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.models import User
#import mammoth
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


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
            return "fermee"
        if now <= self.date_fin_olympiade:
            return "en_cours"
        return "terminee"

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


class ForumMessage(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, null=True, blank=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')
    text = models.TextField(blank=True)
    image = models.ImageField(upload_to='forum_images/', null=True, blank=True)
    audio = models.FileField(upload_to='forum_audios/', null=True, blank=True)
    role = models.CharField(max_length=50, choices=(('enseignant','enseignant'),('eleve','élève')))
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sender.username} - {self.text[:20]}"


'''@receiver(post_save, sender=Lecon)
def convertir_docx_en_html(sender, instance, **kwargs):
    if instance.fichier and instance.fichier.name.endswith(".docx"):
        with open(instance.fichier.path, "rb") as docx_file:
            result = mammoth.convert_to_html(docx_file)
            html = result.value  # HTML du contenu
            instance.contenu_html = html
            instance.save()'''

