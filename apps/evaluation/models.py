from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
from django.utils import timezone

from apps.evaluation.validators import valider_pas_de_0_25
from apps.formation.models import Cours, Module, Lecon, Departement


class Exercice(models.Model):
    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, related_name="exercices")
    titre = models.CharField(max_length=255)
    enonce = models.TextField()
    etoiles = models.IntegerField()
    duree_minutes = models.IntegerField(default=10)  # durée examen
    tentatives_max = models.IntegerField(default=1)
    nb_questions = models.PositiveIntegerField(
        default=0, help_text="Nombre de questions de l'exercice (mis à jour automatiquement)"
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exercices",
        help_text="Module auquel l'exercice est rattaché (optionnel)",
    )
    lecon = models.ForeignKey(
        Lecon,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exercices",
        help_text="Leçon à laquelle l'exercice est rattaché (optionnel)",
    )
    type_exercice = models.CharField(
        max_length=20,
        choices=[
            ("general", "Général"),
            ("module", "Module"),
            ("lecon", "Leçon"),
            ("epreuve", "Épreuve"),
        ],
        default="general",
        help_text="Type d'exercice pour le filtrage",
    )

    # Pour les épreuves (ensemble d'exercices)
    est_epreuve = models.BooleanField(
        default=False, help_text="True si c'est une épreuve composée d'exercices"
    )
    exercices_composes = models.ManyToManyField(
        "self",
        blank=True,
        symmetrical=False,
        related_name="epreuves_parentes",
        help_text="Exercices composant cette épreuve",
    )

    # Image pour l'énoncé
    enonce_image = models.ImageField(
        upload_to="exercices/enonces/",
        null=True,
        blank=True,
        help_text="Image pour l'énoncé (optionnel)",
    )

    class Meta:
        db_table = "yeki_exercice"

    # TODO(bug pré-existant, non corrigé — "déplacer, ne pas réécrire") :
    # `__str__` est défini DEUX FOIS dans cette classe (repéré en P1.6 via
    # ruff F811) — celui-ci (avec `get_type_exercice_display`) est
    # silencieusement ignoré, seul celui ci-dessous (avec `etoiles`)
    # s'applique réellement.
    def __str__(self):
        return f"{self.titre} ({self.get_type_exercice_display()})"

    @property
    def duree(self):
        """Durée en secondes pour Flutter"""
        return self.duree_minutes * 60

    def __str__(self):  # noqa: F811
        return f"{self.titre} ({self.etoiles}⭐)"


class SessionExercice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    exercice = models.ForeignKey(Exercice, on_delete=models.CASCADE)
    debut = models.DateTimeField(auto_now_add=True)
    termine = models.BooleanField(default=False)

    class Meta:
        db_table = "yeki_sessionexercice"

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
    # P2.2 : dépréciée pour les QCM (la bonne réponse y est désormais portée
    # par Choix.est_correct, comparaison texte-à-texte trop fragile —
    # casse/espaces/accents). Conservée et toujours obligatoire pour les
    # questions de type 'texte'. Pour les QCM, ce champ devient un mirroir
    # dérivé (auto-rempli avec le texte du choix correct à la création),
    # conservé pour compatibilité descendante d'affichage.
    bonne_reponse = models.CharField(max_length=255)
    points = models.FloatField(
        default=1.0,
        validators=[MinValueValidator(0.25), valider_pas_de_0_25],
    )

    class Meta:
        db_table = "yeki_question"

    def __str__(self):
        return self.text


class Choix(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choix")
    texte = models.CharField(max_length=255)
    # P2.2 : source de vérité pour la bonne réponse d'un QCM (remplace la
    # comparaison texte-à-texte contre Question.bonne_reponse — fragile,
    # cause confirmée du bug de création QCM échouant sur un simple écart
    # de casse/espace).
    est_correct = models.BooleanField(default=False)

    class Meta:
        db_table = "yeki_choix"

    def __str__(self):
        return f"{'✓' if self.est_correct else '✗'} {self.texte}"


class ExerciceTentative(models.Model):
    """
    Enregistre CHAQUE tentative d'un apprenant sur un exercice, y compris
    l'intégralité des réponses soumises. `EvaluationExercice` continue de
    porter la note "officielle" (dernière tentative valide) ; ce modèle
    porte l'historique complet consultable depuis ResultatExercicePage.
    """

    apprenant = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="tentatives_exercice"
    )
    exercice = models.ForeignKey(Exercice, on_delete=models.CASCADE, related_name="tentatives")
    tentative_numero = models.PositiveIntegerField(help_text="1, 2, 3… dans l'ordre chronologique")
    reponses = models.JSONField(default=dict, help_text="Snapshot complet des réponses soumises")
    score = models.FloatField(default=0.0, help_text="Points obtenus pour cette tentative")
    total_points = models.FloatField(default=0.0, help_text="Points maximum de l'exercice")
    date_tentative = models.DateTimeField(auto_now_add=True)
    est_soumise = models.BooleanField(
        default=False, help_text="False = quittée sans validation explicite (auto-soumission)"
    )
    est_terminee = models.BooleanField(
        default=False, help_text="True = toutes les questions ont une réponse"
    )

    class Meta:
        db_table = "yeki_exercicetentative"
        unique_together = ("apprenant", "exercice", "tentative_numero")
        ordering = ["-date_tentative"]
        verbose_name = "Tentative d'exercice"
        verbose_name_plural = "Tentatives d'exercice"

    def __str__(self):
        return (
            f"{self.apprenant.username} — {self.exercice.titre} (tentative {self.tentative_numero})"
        )

    @staticmethod
    def prochain_numero(apprenant, exercice):
        """Calcule le numéro de la prochaine tentative pour ce couple apprenant/exercice."""
        derniere = (
            ExerciceTentative.objects.filter(apprenant=apprenant, exercice=exercice)
            .order_by("-tentative_numero")
            .first()
        )
        return (derniere.tentative_numero + 1) if derniere else 1

    @property
    def tentatives_epuisees(self):
        """True si l'apprenant a atteint le nombre maximum de tentatives autorisées."""
        total = ExerciceTentative.objects.filter(
            apprenant=self.apprenant, exercice=self.exercice
        ).count()
        return total >= self.exercice.tentatives_max


class EvaluationExercice(models.Model):
    """
    Note "officielle" d'un apprenant sur un exercice : toujours celle de la
    dernière tentative valide. `tentative_finale` référence la tentative
    (dans ExerciceTentative) retenue pour ce calcul.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    exercice = models.ForeignKey(Exercice, on_delete=models.CASCADE)
    score = models.FloatField(default=0.0)
    total = models.FloatField(default=0.0)
    date = models.DateTimeField(auto_now_add=True)
    tentative_finale = models.ForeignKey(
        ExerciceTentative,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluation_associee",
        help_text="Référence vers la tentative retenue comme note finale.",
    )

    class Meta:
        db_table = "yeki_evaluationexercice"

    def __str__(self):
        return f"{self.user.username} - {self.exercice.titre} ({self.score}/{self.total})"


class ReponseExercice(models.Model):
    """
    Stocke la réponse d'un apprenant à une question d'exercice.
    Permet l'historique détaillé des tentatives.
    """

    evaluation = models.ForeignKey(
        EvaluationExercice, on_delete=models.CASCADE, related_name="reponses"
    )
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    reponse = models.TextField(blank=True)
    est_correct = models.BooleanField(default=False)
    points_obtenus = models.FloatField(default=0.0)

    class Meta:
        db_table = "yeki_reponseexercice"
        verbose_name = "Réponse d'exercice"
        verbose_name_plural = "Réponses d'exercices"

    def __str__(self):
        return f"Réponse à {self.question.text[:30]} - {self.evaluation.user.username}"


# ============================================================
# DEVOIR GÉNÉRAL (cursus, concours, formation classique/métier)
# ============================================================


class Devoir(models.Model):
    # ── Type de devoir ──────────────────────────────────────────
    TYPE_CHOICES = [
        ("cursus", "Devoir de cursus"),
        ("concours", "Préparation concours"),
        ("formation_classique", "Formation classique"),
        ("formation_metier", "Formation métier"),
        ("olympiade", "Olympiade"),
    ]

    # ── Champs de base ───────────────────────────────────────────
    titre = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    type_devoir = models.CharField(max_length=25, choices=TYPE_CHOICES, default="cursus")
    # P2.3 : conservé en lecture seule pour compatibilité descendante — la
    # source de vérité est désormais EnonceDevoir(ordre=1), alimenté
    # automatiquement à la création (voir DevoirCreateSerializer.create).
    # Retiré plus tard, pas supprimé maintenant ("ne rien perdre").
    enonce = models.TextField()

    # ⚠️ SUPPRESSION DES CHAMPS MATIERE ET NIVEAU
    # matiere      = models.CharField(max_length=100, choices=MATIERE_CHOICES)
    # niveau       = models.CharField(max_length=50, choices=NIVEAU_CHOICES, default="Terminale")

    # ── Dates ────────────────────────────────────────────────────
    date_creation = models.DateTimeField(auto_now_add=True)
    date_debut = models.DateTimeField(
        default=timezone.now, help_text="Quand le devoir devient visible/accessible"
    )
    date_limite = models.DateTimeField(help_text="Date de remise obligatoire")

    # ── Concours / Formation ─────────────────────────────────────
    concours_lie = models.CharField(
        max_length=255, blank=True, null=True, help_text="Ex: BEPC, BAC, Concours ENS…"
    )
    formation_liee = models.CharField(
        max_length=255, blank=True, null=True, help_text="Nom de la formation liée"
    )

    # ── Paramètres pédagogiques ──────────────────────────────────
    duree_minutes = models.PositiveIntegerField(
        default=60, help_text="Durée max de composition en minutes"
    )
    tentatives_max = models.PositiveIntegerField(
        default=1, help_text="Nombre de sorties autorisées avant soumission auto"
    )
    note_sur = models.PositiveIntegerField(default=20)
    coefficient = models.FloatField(default=1.0)

    # ── Visibilité & accès ───────────────────────────────────────
    est_publie = models.BooleanField(default=False)
    acces_restreint = models.BooleanField(
        default=False, help_text="Si True, seuls les apprenants du cursus lié peuvent y accéder"
    )
    cours_lie = models.ForeignKey(
        "formation.Cours", on_delete=models.SET_NULL, null=True, blank=True, related_name="devoirs"
    )
    TYPE_CORRECTION_CHOICES = [
        ("auto", "Correction automatique"),
        ("manuel", "Correction manuelle"),
    ]
    type_correction = models.CharField(
        max_length=10,
        choices=TYPE_CORRECTION_CHOICES,
        default="auto",
        help_text="auto = QCM/texte exact corrigé auto ; manuel = enseignant corrige avec fichier PDF",
    )

    # ── Fichier de correction pour correction manuelle ──────────
    fichier_correction = models.FileField(
        upload_to="devoirs/corrections/",
        null=True,
        blank=True,
        help_text="Fichier PDF de correction pour les devoirs manuels",
    )

    # ── Plusieurs énoncés ────────────────────────────────────────
    # @deprecated (P2.3) : remplacé par le modèle EnonceDevoir (un énoncé,
    # ses propres questions — voir EnonceDevoir/QuestionDevoir.enonce_devoir).
    # Conservé, PAS supprimé ("ne rien perdre") ; ne plus écrire dedans pour
    # du nouveau contenu.
    enonces_supplementaires = models.JSONField(
        default=list,
        blank=True,
        help_text="[Déprécié, voir EnonceDevoir] Énoncés supplémentaires (JSON)",
    )

    # ── Auteur ───────────────────────────────────────────────────
    cree_par = models.ForeignKey(
        "accounts.Profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="devoirs_crees",
    )

    # ── Devoir source pour duplication ──────────────────────────
    source_devoir = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="duplicatas",
        help_text="Devoir source si ce devoir est une copie",
    )

    class Meta:
        db_table = "yeki_devoir"
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

    @property
    def peut_modifier_questions(self):
        """Vérifie si on peut encore modifier les questions du devoir."""
        return not self.est_publie

    def clean(self):
        if self.date_debut and self.date_limite:
            if self.date_limite <= self.date_debut:
                raise ValidationError("La date limite doit être après la date de début.")


class EnonceDevoir(models.Model):
    """
    Un devoir peut avoir plusieurs énoncés, chacun avec ses propres
    questions (P2.3, CDC §7.2.1 — « un énoncé a plusieurs questions, ces
    questions »). Remplace `Devoir.enonces_supplementaires` (JSONField de
    strings, sans questions rattachées, @deprecated).
    Après publication du devoir (`est_publie=True`), aucun énoncé ne peut
    être ajouté (voir AjouterEnonceDevoirView, apps/evaluation/views/devoirs.py).
    """

    devoir = models.ForeignKey(Devoir, related_name="enonces", on_delete=models.CASCADE)
    contenu = models.TextField(help_text="HTML enrichi")
    ordre = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "yeki_enoncedevoir"
        ordering = ["ordre"]
        unique_together = ("devoir", "ordre")

    def __str__(self):
        return f"Énoncé {self.ordre} — {self.devoir.titre}"


class QuestionDevoir(models.Model):
    TYPE_CHOICES = [
        ("qcm", "QCM"),
        ("texte", "Texte libre"),
    ]
    devoir = models.ForeignKey(Devoir, on_delete=models.CASCADE, related_name="questions")
    # P2.3 : rattache la question à l'un des (potentiellement plusieurs)
    # énoncés du devoir. Nommé `enonce_devoir` (pas `enonce`, déjà pris par
    # le TextField ci-dessous — le texte propre de la question). Nullable :
    # les questions créées avant P2.3 n'ont pas encore été rattachées
    # (migration de données les attache toutes à l'énoncé d'ordre 1).
    enonce_devoir = models.ForeignKey(
        EnonceDevoir,
        related_name="questions",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    enonce = models.TextField()
    type_question = models.CharField(max_length=10, choices=TYPE_CHOICES)
    points = models.FloatField(
        default=1.0,
        validators=[MinValueValidator(0.25), valider_pas_de_0_25],
    )
    ordre = models.PositiveIntegerField(default=1)

    # Pour les questions de type texte en correction auto
    reponse_attendue = models.TextField(
        blank=True, help_text="Réponse attendue pour correction automatique"
    )

    # Pour les questions de type texte en correction manuelle
    reponse_exemple = models.TextField(
        blank=True, help_text="Exemple de réponse (non utilisé pour correction)"
    )

    class Meta:
        db_table = "yeki_questiondevoir"
        ordering = ["ordre"]

    def __str__(self):
        return f"Q{self.ordre} — {self.enonce[:60]}"


class ChoixReponse(models.Model):
    question = models.ForeignKey(QuestionDevoir, on_delete=models.CASCADE, related_name="choix")
    texte = models.CharField(max_length=500)
    est_correct = models.BooleanField(default=False)
    # P2.2 : sans ordre, les choix revenaient dans un ordre non
    # déterministe (cause probable du bug « ajout consécutif de questions
    # avec plus de 2 choix »).
    ordre = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "yeki_choixreponse"
        ordering = ["ordre"]

    def __str__(self):
        return f"{'✓' if self.est_correct else '✗'} {self.texte[:40]}"


class SoumissionDevoir(models.Model):
    STATUT_CHOICES = [
        ("en_cours", "En cours"),
        ("soumis", "Soumis"),
        ("en_retard", "En retard"),
        ("corrige", "Corrigé"),
    ]

    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="soumissions")
    devoir = models.ForeignKey(Devoir, on_delete=models.CASCADE, related_name="soumissions")
    statut = models.CharField(max_length=15, choices=STATUT_CHOICES, default="en_cours")

    # ── Timestamps ──────────────────────────────────────────────
    debut = models.DateTimeField(auto_now_add=True)
    soumis_le = models.DateTimeField(null=True, blank=True)

    # ── Résultats ────────────────────────────────────────────────
    note = models.FloatField(null=True, blank=True)
    commentaire = models.TextField(blank=True)
    corrige_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="corrections"
    )
    corrige_le = models.DateTimeField(null=True, blank=True)

    fichier_soumis = models.FileField(
        upload_to="soumissions_devoirs/",
        null=True,
        blank=True,
        help_text="Fichier PDF soumis par l'apprenant (correction manuelle)",
    )

    # ── Anti-triche ──────────────────────────────────────────────
    nb_focus_perdu = models.PositiveIntegerField(
        default=0, help_text="Nombre de fois que l'apprenant a quitté la page"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    est_suspecte = models.BooleanField(default=False)

    # ── Sorties enregistrées ────────────────────────────────────
    sorties = models.PositiveIntegerField(default=0, help_text="Nombre de sorties enregistrées")

    class Meta:
        db_table = "yeki_soumissiondevoir"
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

    soumission = models.ForeignKey(
        SoumissionDevoir, on_delete=models.CASCADE, related_name="reponses"
    )
    question = models.ForeignKey(QuestionDevoir, on_delete=models.CASCADE)
    reponse = models.TextField(blank=True)  # texte libre OU texte du choix sélectionné
    choix = models.ForeignKey(
        ChoixReponse, on_delete=models.SET_NULL, null=True, blank=True
    )  # pour QCM
    est_correct = models.BooleanField(null=True, blank=True)  # rempli à la correction
    points_obtenus = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "yeki_reponsedevoir"
        unique_together = ("soumission", "question")


class Olympiade(models.Model):
    STATUT_CHOICES = [
        ("inscription", "Inscriptions ouvertes"),
        ("fermee", "Inscriptions fermées"),
        ("en_cours", "Olympiade en cours"),
        ("terminee", "Terminée"),
    ]

    prix_participation = models.PositiveIntegerField(
        default=100,
        help_text="Prix de participation par apprenant en FCFA (0 = gratuit). 100 FCFA par défaut : 80% compte Yéki, 20% compte du cadre organisateur.",
    )
    recompense = models.TextField(
        blank=True, help_text="Description des récompenses (trophées, certificats, etc.)"
    )
    demande_paiement_participants = models.BooleanField(
        default=False, help_text="Si True, les participants doivent payer pour s'inscrire"
    )

    # Champ pour le prix global (calculé automatiquement)
    prix_global = models.PositiveIntegerField(
        default=0, help_text="Prix global calculé automatiquement (nb_apprenants * 100)"
    )

    # ── Identité ─────────────────────────────────────────────────
    titre = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    edition = models.CharField(max_length=20, blank=True, help_text="Ex: 2025-1")

    # ⚠️ SUPPRESSION DES CHAMPS MATIERE ET NIVEAU
    # matiere      = models.CharField(max_length=100)
    # niveau       = models.CharField(max_length=50)

    # ── Dates ────────────────────────────────────────────────────
    date_ouverture_inscription = models.DateTimeField()
    date_cloture_inscription = models.DateTimeField()
    date_debut_olympiade = models.DateTimeField()
    date_fin_olympiade = models.DateTimeField()

    # ── Paramètres de composition ────────────────────────────────
    duree_minutes = models.PositiveIntegerField(default=120)
    nb_questions = models.PositiveIntegerField(default=30)
    note_sur = models.PositiveIntegerField(default=20)
    melanger_questions = models.BooleanField(
        default=True, help_text="Mélange l'ordre des questions par participant"
    )
    melanger_choix = models.BooleanField(
        default=True, help_text="Mélange les choix QCM par participant"
    )
    une_seule_session = models.BooleanField(
        default=True, help_text="Impossible de reprendre si on quitte"
    )
    max_focus_perdu = models.PositiveIntegerField(
        default=3, help_text="Nb d'abandons de focus avant soumission forcée"
    )

    # ── Devoir lié ───────────────────────────────────────────────
    devoir = models.OneToOneField(
        Devoir,
        on_delete=models.CASCADE,
        related_name="olympiade_config",
        null=True,
        blank=True,
        help_text="Le devoir contenant les questions de l'olympiade",
    )

    # ⚠️ SUPPRESSION DES CHAMPS PRIX_1ER, PRIX_2EME, PRIX_3EME
    # prix_1er    = models.CharField(max_length=255, blank=True)
    # prix_2eme   = models.CharField(max_length=255, blank=True)
    # prix_3eme   = models.CharField(max_length=255, blank=True)

    # ── Auteur ───────────────────────────────────────────────────
    organisateur = models.ForeignKey(
        "accounts.Profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="olympiades_organisees",
    )

    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    # ---validation olympiade ----
    est_validee = models.BooleanField(default=False)  # Validée par l'admin
    est_refusee = models.BooleanField(default=False)  # Refusée par l'admin
    motif_refus = models.TextField(blank=True)  # Motif du refus
    validee_le = models.DateTimeField(null=True, blank=True)  # Date de validation

    niveaux_accessibles = models.TextField(
        blank=True,
        help_text="Liste des niveaux séparés par des virgules (ex: 'Terminale,Licence 1')",
    )

    def get_niveaux_accessibles_list(self):
        if not self.niveaux_accessibles:
            return []
        return [n.strip().lower() for n in self.niveaux_accessibles.split(",") if n.strip()]

    def est_accessible_par_niveau(self, niveau_apprenant: str) -> bool:
        if not niveau_apprenant:
            return True
        niveaux = self.get_niveaux_accessibles_list()
        if not niveaux:
            return True
        return niveau_apprenant.lower() in niveaux

    class Meta:
        db_table = "yeki_olympiade"
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
            raise ValidationError(
                "La clôture des inscriptions doit être avant le début de l'olympiade."
            )
        if self.date_debut_olympiade >= self.date_fin_olympiade:
            raise ValidationError("La date de début doit être avant la date de fin.")


class InscriptionOlympiade(models.Model):
    """Inscription d'un apprenant à une olympiade."""

    STATUT_CHOICES = [
        ("inscrit", "Inscrit"),
        ("confirme", "Confirmé"),
        ("disqualifie", "Disqualifié"),
    ]

    olympiade = models.ForeignKey(Olympiade, on_delete=models.CASCADE, related_name="inscriptions")
    apprenant = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="inscriptions_olympiade"
    )
    statut = models.CharField(max_length=15, choices=STATUT_CHOICES, default="inscrit")
    inscrit_le = models.DateTimeField(auto_now_add=True)

    # ── Session de composition ───────────────────────────────────
    session_demarree = models.BooleanField(default=False)
    heure_debut_compo = models.DateTimeField(null=True, blank=True)
    heure_fin_compo = models.DateTimeField(null=True, blank=True)
    soumis = models.BooleanField(default=False)
    soumis_automatique = models.BooleanField(
        default=False, help_text="True si soumis automatiquement (temps écoulé / triche)"
    )

    # ── Anti-triche ──────────────────────────────────────────────
    nb_focus_perdu = models.PositiveIntegerField(default=0)
    ip_inscription = models.GenericIPAddressField(null=True, blank=True)
    ip_composition = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    est_suspecte = models.BooleanField(default=False)
    raison_suspicion = models.TextField(blank=True)

    # ── Résultat ─────────────────────────────────────────────────
    note = models.FloatField(null=True, blank=True)
    classement = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "yeki_inscriptionolympiade"
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

    inscription = models.ForeignKey(
        InscriptionOlympiade, on_delete=models.CASCADE, related_name="reponses"
    )
    question = models.ForeignKey(QuestionDevoir, on_delete=models.CASCADE)
    choix = models.ForeignKey(ChoixReponse, on_delete=models.SET_NULL, null=True, blank=True)
    reponse_texte = models.TextField(blank=True)
    est_correct = models.BooleanField(null=True, blank=True)
    points_obtenus = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "yeki_reponseolympiade"
        unique_together = ("inscription", "question")


class ClassementOlympiade(models.Model):
    """Classement final calculé après correction."""

    olympiade = models.ForeignKey(Olympiade, on_delete=models.CASCADE, related_name="classement")
    apprenant = models.ForeignKey(User, on_delete=models.CASCADE)
    rang = models.PositiveIntegerField()
    note = models.FloatField()
    mention = models.CharField(max_length=50, blank=True)  # Or, Argent, Bronze…

    class Meta:
        db_table = "yeki_classementolympiade"
        ordering = ["rang"]
        unique_together = ("olympiade", "apprenant")


# ═══════════════════════════════════════════════════════════════════════════
# SYSTÈME DE RANG DES APPRENANTS PAR DÉPARTEMENT
# ═══════════════════════════════════════════════════════════════════════════


class RangApprenant(models.Model):
    """
    Score et rang d'un apprenant dans un département spécifique.
    Calculé périodiquement (batch) ou à la demande.
    """

    apprenant = models.ForeignKey(User, on_delete=models.CASCADE, related_name="rangs")
    departement = models.ForeignKey(
        Departement, on_delete=models.CASCADE, related_name="rangs_apprenants"
    )
    score = models.FloatField(
        default=0.0, help_text="Score calculé (0-1000) basé sur les performances"
    )
    rang = models.PositiveIntegerField(
        null=True, blank=True, help_text="Position dans le département (1 = meilleur)"
    )
    progression_semaine = models.FloatField(
        default=0.0, help_text="Variation de score sur les 7 derniers jours (-100 à +100)"
    )
    calcule_le = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "yeki_rangapprenant"
        unique_together = ("apprenant", "departement")
        ordering = ["rang"]
        indexes = [
            models.Index(fields=["departement", "rang"]),
            models.Index(fields=["apprenant", "score"]),
        ]
        verbose_name = "Rang Apprenant"
        verbose_name_plural = "Rangs Apprenants"

    def __str__(self):
        return f"{self.apprenant.username} | {self.departement.nom} | Rang #{self.rang} | Score {self.score:.0f}"


class ScoreDetail(models.Model):
    """
    Détail des scores par catégorie pour traçabilité.
    Stocke les composants du score total.
    """

    rang_apprenant = models.ForeignKey(
        RangApprenant, on_delete=models.CASCADE, related_name="details"
    )
    categorie = models.CharField(
        max_length=50,
        choices=[
            ("devoirs", "Devoirs rendus à temps"),
            ("notes_devoirs", "Notes aux devoirs"),
            ("exercices", "Résultats exercices"),
            ("lecons", "Progression leçons"),
            ("forum", "Participation forum"),
            ("regularite", "Régularité de connexion"),
        ],
    )
    score = models.FloatField(default=0.0)
    poids = models.FloatField(default=1.0)
    calcule_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "yeki_scoredetail"
        unique_together = ("rang_apprenant", "categorie")

    def __str__(self):
        return f"{self.categorie}: {self.score:.1f} (poids {self.poids})"


class ClassementHistorique(models.Model):
    """
    Archive du classement d'un apprenant dans un département, à la fin
    d'une période (P2.3, CDC §6.4/§7.4). Créée par
    `Departement.reinitialiser_periode()` AVANT toute réinitialisation des
    dates de période — auparavant cette méthode prétendait archiver mais
    ne faisait qu'écraser les dates, perdant purement et simplement le
    classement de la période précédente (contradiction directe avec
    « rien ne se perd »).
    """

    departement = models.ForeignKey(
        "formation.Departement", on_delete=models.CASCADE, related_name="historique_classements"
    )
    apprenant = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="historique_classements"
    )
    periode_debut = models.DateTimeField()
    periode_fin = models.DateTimeField()
    rang = models.PositiveIntegerField(null=True, blank=True)
    points = models.FloatField(default=0.0)
    detail = models.JSONField(
        default=dict,
        blank=True,
        help_text="Ventilation par source (catégorie → score), voir ScoreDetail",
    )
    archive_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "yeki_classement_historique"
        unique_together = ("departement", "apprenant", "periode_debut")
        indexes = [models.Index(fields=["departement", "periode_debut", "rang"])]

    def __str__(self):
        return f"{self.apprenant.username} — {self.departement.nom} ({self.periode_debut:%d/%m/%Y})"
