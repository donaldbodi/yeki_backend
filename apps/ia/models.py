from django.db import models
from django.contrib.auth.models import User

from apps.formation.models import Cours


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
        ("cursus_niveau", "Niveau dans le cursus"),
        ("parcours", "Parcours complet (Prépa Concours, Formations…)"),
        ("cours", "Cours spécifique"),
        ("olympiade", "Olympiade"),
    ]
    STYLE_CHOICES = [
        ("pedagogique", "Pédagogique (explications détaillées)"),
        ("socratique", "Socratique (questions pour guider)"),
        ("direct", "Direct (réponses concises)"),
        ("encourageant", "Encourageant (bienveillant et motivant)"),
        ("academique", "Académique (rigoureux et formel)"),
        ("professionnel", "Professionnel (orienté compétences)"),
    ]
    NIVEAU_DIFFICULTE_CHOICES = [
        ("debutant", "Débutant"),
        ("intermediaire", "Intermédiaire"),
        ("avance", "Avancé"),
    ]

    nom = models.CharField(max_length=200)
    contexte = models.CharField(max_length=20, choices=CONTEXTE_CHOICES)
    style = models.CharField(max_length=20, choices=STYLE_CHOICES, default="pedagogique")
    niveau_difficulte = models.CharField(
        max_length=15, choices=NIVEAU_DIFFICULTE_CHOICES, default="intermediaire"
    )

    # Liens optionnels — cours ou niveau texte
    cours_lie = models.ForeignKey(
        Cours, on_delete=models.CASCADE, null=True, blank=True, related_name="ia_personnalites"
    )
    # Pour les parcours : on stocke simplement le nom du parcours
    nom_parcours = models.CharField(
        max_length=100, blank=True, help_text="Nom du Parcours (ex: 'Prépa Concours', 'Formations')"
    )
    niveau_cursus = models.CharField(max_length=50, blank=True, help_text="Ex: Terminale, 3ème…")

    # Prompt et cache
    prompt_systeme = models.TextField(blank=True)
    contexte_cours_cache = models.TextField(blank=True)
    cache_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "yeki_yekiiapersonalite"
        verbose_name = "Personnalité IA"
        verbose_name_plural = "Personnalités IA"

    def __str__(self):
        return f"[{self.get_contexte_display()}] {self.nom}"

    def build_system_prompt(self) -> str:
        style_desc = {
            "pedagogique": "Tu expliques chaque concept en détail avec des exemples concrets.",
            "socratique": "Tu guides par des questions plutôt que donner directement la réponse.",
            "direct": "Tu donnes des réponses concises et précises.",
            "encourageant": "Tu es très bienveillant et tu encourages l'apprenant.",
            "academique": "Tu utilises un vocabulaire rigoureux et académique.",
            "professionnel": "Tu orientes vers les compétences pratiques et professionnelles.",
        }
        niveau_desc = {
            "debutant": "Utilise un langage simple, évite le jargon technique.",
            "intermediaire": "Utilise un langage adapté à un niveau intermédiaire.",
            "avance": "Tu peux utiliser la terminologie experte du domaine.",
        }
        prompt = (
            "Tu es Yéki IA, l'assistant pédagogique de la plateforme Yéki.\n"
            'Tu réponds TOUJOURS en commençant par "Yeki IA :" suivi de ta réponse.\n'
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


class YekiIAChatHistorique(models.Model):
    """
    Message dans la conversation privée apprenant ↔ Yeki IA,
    dans le contexte d'un cours.
    """

    ROLE_CHOICES = [("user", "Apprenant"), ("assistant", "Yeki IA")]

    apprenant = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ia_chat_historique")
    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, related_name="ia_chat_messages")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    contenu = models.TextField()
    # Source optionnelle (lecon, exercice, devoir)
    source = models.CharField(
        max_length=20, blank=True, help_text="lecon | exercice | devoir | libre"
    )
    source_id = models.IntegerField(null=True, blank=True)
    source_titre = models.CharField(max_length=255, blank=True)
    # Image jointe (optionnel)
    image = models.ImageField(upload_to="ia_chat_images/", null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    tokens = models.PositiveIntegerField(default=0)
    tokens_input = models.PositiveIntegerField(default=0, help_text="Nombre de tokens en entrée")
    tokens_output = models.PositiveIntegerField(default=0, help_text="Nombre de tokens en sortie")
    audio = models.FileField(
        upload_to="ia_chat_audios/",
        null=True,
        blank=True,
        help_text="Fichier audio joint à la question",
    )

    class Meta:
        db_table = "yeki_yekiiachathistorique"
        ordering = ["cree_le"]
        verbose_name = "Message IA Chat"

    def __str__(self):
        return f"[{self.role}] {self.apprenant.username} — {self.cours.titre} — {self.cree_le:%d/%m %H:%M}"
