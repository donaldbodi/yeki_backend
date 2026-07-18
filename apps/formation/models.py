from django.db import models
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.models import User
from django.utils import timezone

from apps.accounts.models import Profile


# --- NIVEAU 1 ---


class Parcours(models.Model):
    """
    Parcours de haut niveau créé par l'admin général.
    Exemples : "Cursus Universitaire", "Prépa Concours", "Formations", etc.
    """

    TYPE_CHOICES = [
        ("cursus", "Cursus scolaire / universitaire"),
        ("prepa", "Prépa Concours"),
        ("formation", "Formations professionnelles"),
        ("autre", "Autre"),
    ]
    nom = models.CharField(max_length=100)
    type_parcours = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default="autre",
        help_text="Nature du parcours pour guider l'affichage",
    )
    description = models.TextField(blank=True)
    admin = models.ForeignKey(
        "accounts.Profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"user_type": "enseignant_admin"},
        related_name="parcours_admin",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "yeki_parcours"

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
    nom = models.CharField(max_length=200)
    parcours = models.ForeignKey(Parcours, on_delete=models.CASCADE, related_name="departements")
    cadre = models.ForeignKey(
        "accounts.Profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"user_type": "enseignant_cadre"},
        related_name="departements_cadre",
    )

    niveau_formation = models.CharField(
        max_length=20,
        choices=[
            ("debutant", "Débutant"),
            ("intermediaire", "Intermédiaire"),
            ("avance", "Avancé"),
        ],
        blank=True,
        default="debutant",
        help_text="Niveau de la formation (pour les formations métier)",
    )

    # ── Présentation visuelle (tous les types) ────────────────────
    description = models.TextField(blank=True, help_text="Description détaillée")
    image = models.ImageField(
        upload_to="departements/images/",
        null=True,
        blank=True,
        help_text="Image de couverture du département",
    )
    couleur = models.CharField(
        max_length=7, default="#2884A0", help_text="Couleur principale #RRGGBB"
    )
    est_actif = models.BooleanField(default=True, help_text="Visible aux apprenants si True")
    prix = models.PositiveIntegerField(default=0, help_text="Prix d'accès en FCFA (0 = gratuit)")
    created_at = models.DateTimeField(auto_now_add=True)

    # ── Période de classement (Partie 9.2) ─────────────────────────
    periode = models.PositiveIntegerField(
        default=6, help_text="Durée d'une période de classement en mois (1, 3, 6, 12)"
    )
    date_debut_periode = models.DateTimeField(
        auto_now_add=True, help_text="Début de la période de classement en cours"
    )
    date_fin_periode = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Calculée = date_debut_periode + periode mois. Recalculée à chaque réinitialisation.",
    )

    def reinitialiser_periode(self):
        """
        Archive le classement actuel (ClassementHistorique) puis redémarre
        une nouvelle période de classement à partir de maintenant.

        P2.3 : avant cette correction, cette méthode PRÉTENDAIT archiver
        mais n'écrasait que les dates — le classement de la période
        précédente (RangApprenant/ScoreDetail) était purement et simplement
        perdu, en contradiction directe avec « rien ne se perd ». Corrigée
        pour archiver réellement, dans une transaction atomique (archivage
        + reset des dates réussissent ou échouent ensemble).
        """
        from dateutil.relativedelta import relativedelta
        from django.db import transaction

        # Imports différés : apps.evaluation.models importe déjà
        # apps.formation.models (Cours/Module/Lecon/Departement) — un
        # import en tête de ce fichier créerait un cycle au chargement des
        # apps.
        from apps.evaluation.models import ClassementHistorique, RangApprenant

        ancien_debut = self.date_debut_periode
        maintenant = timezone.now()

        with transaction.atomic():
            rangs = RangApprenant.objects.filter(departement=self).prefetch_related("details")
            for rang_apprenant in rangs:
                detail = {d.categorie: d.score for d in rang_apprenant.details.all()}
                ClassementHistorique.objects.update_or_create(
                    departement=self,
                    apprenant=rang_apprenant.apprenant,
                    periode_debut=ancien_debut,
                    defaults={
                        "periode_fin": maintenant,
                        "rang": rang_apprenant.rang,
                        "points": rang_apprenant.score,
                        "detail": detail,
                    },
                )

            self.date_debut_periode = maintenant
            self.date_fin_periode = maintenant + relativedelta(months=self.periode)
            self.save(update_fields=["date_debut_periode", "date_fin_periode"])

    # ── CHAMPS PRÉPA CONCOURS ──────────────────────────────────────
    # Activés quand parcours.type_parcours == 'prepa'
    est_prepa_concours = models.BooleanField(
        default=False, help_text="True = ce département est un concours à préparer"
    )
    nom_concours = models.CharField(
        max_length=255,
        blank=True,
        help_text="Nom officiel du concours (ex: ENS, Polytechnique, BEPC…)",
    )
    organisme_concours = models.CharField(
        max_length=255, blank=True, help_text="Organisme/institution organisateur"
    )
    date_limite_inscription = models.DateField(
        null=True, blank=True, help_text="Date limite d'inscription au concours"
    )
    date_examen = models.DateField(
        null=True, blank=True, help_text="Date prévue de l'examen / concours"
    )
    arrete_ministeriel = models.CharField(
        max_length=255, blank=True, help_text="Référence de l'arrêté ministériel d'organisation"
    )
    niveaux_cibles = models.CharField(
        max_length=255, blank=True, help_text="Niveaux ciblés ex: Terminale, Licence 3, Master 1"
    )
    places_disponibles = models.PositiveIntegerField(
        null=True, blank=True, help_text="Nombre de places au concours (null = non précisé)"
    )
    debouches = models.TextField(blank=True, help_text="Débouchés après réussite du concours")

    # Ajouter ces champs pour la gestion des accès
    acces_restreint = models.BooleanField(
        default=False, help_text="Accès limité aux apprenants sélectionnés"
    )
    apprenants_autorises = models.ManyToManyField(
        User,
        blank=True,
        related_name="formations_autorisees",
        help_text="Apprenants autorisés à accéder à cette formation (si acces_restreint=True)",
    )

    # ── CHAMPS FORMATION ──────────────────────────────────────────
    # Activés quand parcours.type_parcours == 'formation'
    est_formation_metier = models.BooleanField(
        default=False, help_text="True = formation orientée compétences métier"
    )
    est_formation_classique = models.BooleanField(
        default=False, help_text="True = formation académique classique (université, grande école…)"
    )
    duree_formation = models.CharField(
        max_length=100, blank=True, help_text="Ex: 6 mois, 2 ans, 200 heures…"
    )
    mode = models.CharField(
        max_length=20,
        choices=[("presentiel", "Présentiel"), ("distance", "À distance"), ("hybride", "Hybride")],
        default="hybride",
        blank=True,
        help_text="Mode de diffusion",
    )
    certificat_delivre = models.CharField(
        max_length=255, blank=True, help_text="Certificat / diplôme délivré à la fin"
    )
    prerequis = models.TextField(blank=True, help_text="Prérequis pour intégrer la formation")
    objectifs = models.TextField(blank=True, help_text="Objectifs pédagogiques de la formation")
    domaine = models.CharField(
        max_length=255,
        blank=True,
        help_text="Domaine professionnel (Informatique, Gestion, Santé…)",
    )
    ville = models.CharField(
        max_length=100, blank=True, help_text="Ville principale où se déroule la formation"
    )
    est_certifiante = models.BooleanField(
        default=False, help_text="True si la formation délivre un certificat reconnu"
    )

    niveaux_accessibles = models.TextField(
        blank=True,
        help_text="Liste des niveaux séparés par des virgules (ex: 'Terminale,Licence 1,Licence 2')",
    )

    prix_presentiel = models.PositiveIntegerField(
        default=0,
        help_text="Prix en présentiel (supplément) en FCFA. Le prix total = prix (en ligne) + prix_presentiel",
    )

    # ── Tarification Premium détaillée (Partie 6.2) ────────────────
    # Seuls prix_mensuel et prix_annuel donnent accès à la version Premium ;
    # les tarifs présentiel sont facultatifs (supplément cours en présentiel).
    # `prix` / `prix_presentiel` restent en base pour compatibilité ascendante.
    prix_mensuel = models.PositiveIntegerField(
        default=0, help_text="Prix abonnement mensuel en ligne (FCFA)"
    )
    prix_annuel = models.PositiveIntegerField(
        default=0, help_text="Prix abonnement annuel en ligne (FCFA)"
    )
    prix_presentiel_mensuel = models.PositiveIntegerField(
        default=0, blank=True, help_text="Supplément présentiel mensuel, facultatif (FCFA)"
    )
    prix_presentiel_annuel = models.PositiveIntegerField(
        default=0, blank=True, help_text="Supplément présentiel annuel, facultatif (FCFA)"
    )

    @property
    def prix_total(self) -> int:
        """Retourne le prix total (en ligne + présentiel)"""
        return self.prix + self.prix_presentiel

    @property
    def a_paiement_presentiel(self) -> bool:
        """Indique si un paiement présentiel est requis en plus"""
        return self.prix_presentiel > 0

    def get_niveaux_accessibles_list(self):
        """Retourne la liste des niveaux accessibles"""
        if not self.niveaux_accessibles:
            return []
        return [n.strip().lower() for n in self.niveaux_accessibles.split(",") if n.strip()]

    def est_accessible_par_niveau(self, niveau_apprenant: str) -> bool:
        """Vérifie si le niveau de l'apprenant est dans la liste des niveaux accessibles"""
        if not niveau_apprenant:
            return True  # Si pas de niveau défini, on autorise
        niveaux = self.get_niveaux_accessibles_list()
        if not niveaux:
            return True  # Si aucun niveau spécifié, on autorise
        return niveau_apprenant.lower() in niveaux

    class Meta:
        db_table = "yeki_departement"
        ordering = ["parcours", "nom"]

    def __str__(self):
        return f"{self.nom} ({self.parcours.nom} | cadre: {self.cadre})"

    @property
    def type_departement(self):
        """Retourne le type logique du département."""
        if self.est_prepa_concours:
            return "prepa_concours"
        if self.est_formation_metier:
            return "formation_metier"
        if self.est_formation_classique:
            return "formation_classique"
        return "cursus"

    # ✅ Seul un enseignant_admin peut créer un département
    @staticmethod
    def create_departement(user, parcours, nom, cadre):
        if user.user_type != "enseignant_admin":
            raise PermissionDenied("Seul un enseignant_admin peut créer un département.")
        return Departement.objects.create(parcours=parcours, nom=nom, cadre=cadre)


# Champs de Departement historisés par le signal (apps/formation/signals.py)
# — portée limitée au prix : seule motivation donnée par le CDC (rendre la
# règle « promotion » calculable), pas un audit générique de tout champ.
CHAMPS_PRIX_HISTORISES = ["prix", "prix_presentiel"]


class HistoriquePrixDepartement(models.Model):
    """
    Historique des changements de prix d'un département (P2.4, CDC §6.4).
    Sans cet historique, la règle « prix inférieur à l'ancien → afficher
    PROMOTION » n'a aucun référent : rien ne permet de savoir si le prix
    actuel est une baisse. Alimenté automatiquement par un signal
    (apps/formation/signals.py), jamais écrit à la main.
    """

    departement = models.ForeignKey(
        Departement, on_delete=models.CASCADE, related_name="historique_prix"
    )
    champ = models.CharField(max_length=50, help_text="'prix' ou 'prix_presentiel'")
    ancienne_valeur = models.PositiveIntegerField()
    nouvelle_valeur = models.PositiveIntegerField()
    date = models.DateTimeField(auto_now_add=True)
    # Un signal post_save n'a pas accès à « qui » a fait la requête HTTP —
    # laissé null par le signal ; à renseigner par les vues d'écriture de
    # département si souhaité (hors périmètre de cette tâche).
    par_qui = models.ForeignKey(
        "accounts.Profile", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "yeki_historique_prix_departement"
        verbose_name = "Historique de prix (département)"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.departement.nom} — {self.champ}: {self.ancienne_valeur} → {self.nouvelle_valeur}"


class DemandeAccesFormation(models.Model):
    STATUT_CHOICES = [
        ("en_attente", "En attente"),
        ("acceptee", "Acceptée"),
        ("refusee", "Refusée"),
    ]

    apprenant = models.ForeignKey(User, on_delete=models.CASCADE, related_name="demandes_acces")
    departement = models.ForeignKey(
        Departement, on_delete=models.CASCADE, related_name="demandes_acces"
    )
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default="en_attente")
    message = models.TextField(blank=True, help_text="Message de l'apprenant")
    reponse_cadre = models.TextField(blank=True, help_text="Réponse du cadre")
    cree_le = models.DateTimeField(auto_now_add=True)
    traite_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "yeki_demandeaccesformation"
        unique_together = ("apprenant", "departement")
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.apprenant.username} → {self.departement.nom} ({self.statut})"


# --- NIVEAU 3 ---
# ═══════════════════════════════════════════════════════════════
# PALETTE OFFICIELLE DES COULEURS DE COURS
# La couleur d'un cours n'est jamais calculée côté Flutter : elle est
# choisie ici, côté backend, et proposée à l'enseignant qui crée le cours
# via GET /api/cours/palette-couleurs/ (voir ListeNiveauxView à proximité
# dans views.py pour le même pattern).
# ⚠️ Cette liste DOIT rester strictement synchronisée, dans le même ordre,
# avec `YekiCoursePalette.official` dans yeki_design_system.dart (Flutter).
# ═══════════════════════════════════════════════════════════════
COURSE_COLOR_PALETTE = [
    {"code": "#7C3AED", "nom": "Violet Électrique"},
    {"code": "#10B981", "nom": "Émeraude"},
    {"code": "#EA580C", "nom": "Orange Brûlé"},
    {"code": "#DB2777", "nom": "Rose Fuchsia"},
    {"code": "#2563EB", "nom": "Bleu Roi"},
    {"code": "#CA8A04", "nom": "Or Ambré"},
    {"code": "#0D9488", "nom": "Sarcelle"},
    {"code": "#DC2626", "nom": "Rouge Corail"},
    {"code": "#9333EA", "nom": "Pourpre"},
    {"code": "#059669", "nom": "Vert Jade"},
    {"code": "#EC4899", "nom": "Magenta"},
    {"code": "#0284C7", "nom": "Cyan Profond"},
]
COURSE_COLOR_CHOICES = [(c["code"], c["nom"]) for c in COURSE_COLOR_PALETTE]


class Cours(models.Model):
    titre = models.CharField(max_length=200)
    niveau = models.CharField(max_length=200)
    # --- EXISTANTS ---
    matiere = models.CharField(max_length=255, blank=True)
    concours = models.CharField(max_length=255, blank=True)

    enseignant_principal = models.ForeignKey(
        "accounts.Profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"user_type": "enseignant_principal"},
        related_name="cours_principal",
    )

    enseignants = models.ManyToManyField(
        "accounts.Profile",
        blank=True,
        limit_choices_to={"user_type": "enseignant"},
        related_name="cours_secondaires",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    nb_apprenants = models.PositiveIntegerField(default=0)

    # Relations
    departement = models.ForeignKey(Departement, on_delete=models.CASCADE, related_name="cours")

    # --- NOUVEAUX CHAMPS ---
    description_brief = models.CharField(
        max_length=255, help_text="Description courte du cours", blank=True, null=True
    )

    color_code = models.CharField(
        max_length=7,
        choices=COURSE_COLOR_CHOICES,
        default="#2563EB",
        help_text="Couleur d'accentuation du cours, choisie parmi la palette YÉKI officielle (voir COURSE_COLOR_PALETTE).",
    )

    icon_name = models.CharField(
        max_length=50,
        default="school",
        help_text="Nom de l’icône Flutter (MaterialIcons)",
    )

    nb_devoirs = models.PositiveIntegerField(default=0)
    nb_lecons = models.PositiveIntegerField(default=0)

    niveau_professionnel = models.CharField(
        max_length=20,
        choices=[
            ("amateur", "Amateur"),
            ("expert", "Expert"),
            ("professionnel", "Professionnel"),
        ],
        blank=True,
        null=True,
        help_text="Niveau professionnel visé (formations métier uniquement)",
    )

    class Meta:
        db_table = "yeki_cours"

    def __str__(self):
        return f"{self.titre} ({self.niveau})"

    # ✅ Seul un enseignant_cadre peut créer un cours
    @staticmethod
    def create_cours(
        user,
        departement,
        titre,
        niveau,
        color_code,
        icon_name,
        enseignant_principal=None,
        description_brief=None,
    ):
        try:
            profile = user.profile
        except Profile.DoesNotExist:
            raise PermissionDenied("Profil utilisateur introuvable.")

        if profile.user_type != "enseignant_cadre":
            raise PermissionDenied("Seul un enseignant_cadre peut créer un cours.")

        # La couleur doit obligatoirement provenir de la palette officielle
        codes_valides = [c["code"] for c in COURSE_COLOR_PALETTE]
        if color_code not in codes_valides:
            raise ValidationError(
                f"Couleur invalide. Choisissez parmi : {', '.join(codes_valides)}"
            )

        return Cours.objects.create(
            description_brief=description_brief,
            color_code=color_code,
            icon_name=icon_name,
            departement=departement,
            titre=titre,
            niveau=niveau,
            enseignant_principal=enseignant_principal,
        )


class Module(models.Model):
    titre = models.CharField(max_length=200)

    description = models.CharField(max_length=200, default="")

    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, related_name="modules")

    ordre = models.PositiveIntegerField(help_text="Ordre défini par l'enseignant principal")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "yeki_module"
        ordering = ["ordre"]
        unique_together = ("cours", "ordre")

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
        upload_to="lecons/pdf/",
        help_text="PDF du cours",
        null=True,
        blank=True,
    )

    video = models.FileField(upload_to="lecons/video/", blank=True, null=True)

    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, related_name="lecons")

    created_by = models.ForeignKey(
        "accounts.Profile", on_delete=models.SET_NULL, null=True, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "yeki_lecon"

    def __str__(self):
        return f"{self.titre} ({self.cours.titre})"


class SupplementCours(models.Model):
    """
    Contenu annexe rattaché à une leçon (lien, PDF, vidéo, PowerPoint),
    affiché en défilement vertical façon TikTok depuis DetailLeconPage.
    """

    TYPE_CHOICES = [
        ("lien", "Lien"),
        ("pdf", "PDF"),
        ("video", "Vidéo"),
        ("ppt", "PowerPoint"),
    ]
    lecon = models.ForeignKey(Lecon, on_delete=models.CASCADE, related_name="supplements")
    titre = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    type_contenu = models.CharField(max_length=20, choices=TYPE_CHOICES)
    fichier = models.FileField(upload_to="supplements/", null=True, blank=True)
    url = models.URLField(null=True, blank=True)
    ordre = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "yeki_supplementcours"
        ordering = ["ordre", "created_at"]
        verbose_name = "Supplément de cours"

    def __str__(self):
        return f"{self.titre} ({self.get_type_contenu_display()}) — {self.lecon.titre}"

    def clean(self):
        if self.type_contenu in ("pdf", "video", "ppt") and not self.fichier and not self.url:
            raise ValidationError("Un fichier ou une URL est requis pour ce type de contenu.")
        if self.type_contenu == "lien" and not self.url:
            raise ValidationError("Une URL est requise pour un supplément de type lien.")


class ProgressionLecon(models.Model):
    apprenant = models.ForeignKey(User, on_delete=models.CASCADE, related_name="progressions")
    lecon = models.ForeignKey(Lecon, on_delete=models.CASCADE, related_name="progressions")
    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, related_name="progressions")
    pourcentage = models.PositiveSmallIntegerField(default=0)
    # 0-100
    derniere_vue = models.DateTimeField(auto_now=True)
    terminee = models.BooleanField(default=False)

    class Meta:
        db_table = "yeki_progressionlecon"
        unique_together = ("apprenant", "lecon")
        ordering = ["-derniere_vue"]

    def __str__(self):
        return f"{self.apprenant.username} → {self.lecon.titre} ({self.pourcentage}%)"


class LeconLike(models.Model):
    """Like d'une leçon par un apprenant"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="lecon_likes")
    lecon = models.ForeignKey(Lecon, on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "yeki_leconlike"
        unique_together = ("user", "lecon")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} → {self.lecon.titre}"
