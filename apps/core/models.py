import logging

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

logger = logging.getLogger(__name__)


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
        # ── Admin general ───────────────────────────────────────────────
        ("teacher_activated", "Enseignant activé"),
        ("teacher_type_changed", "Type enseignant modifié"),
        ("parcours_modified", "Parcours modifié"),
        # ── Cours ───────────────────────────────────────────────
        ("course_created", "Cours créé"),
        ("course_modified", "Cours modifié"),
        ("course_deleted", "Cours supprimé"),
        # ── Enseignants ─────────────────────────────────────────
        ("teacher_assigned", "Enseignant principal assigné"),
        ("teacher_changed", "Enseignant principal changé"),
        ("secondary_added", "Enseignant secondaire ajouté"),
        ("secondary_removed", "Enseignant secondaire retiré"),
        # ── Modules ─────────────────────────────────────────────
        ("module_created", "Module créé"),
        ("module_modified", "Module modifié"),
        ("module_deleted", "Module supprimé"),
        # ── Leçons ──────────────────────────────────────────────
        ("lesson_created", "Leçon créée"),
        ("lesson_modified", "Leçon modifiée"),
        ("lesson_deleted", "Leçon supprimée"),
        # ── Devoirs ─────────────────────────────────────────────
        ("homework_created", "Devoir créé"),
        ("homework_modified", "Devoir modifié"),
        ("homework_graded", "Devoir corrigé"),
        # ── Exercices ────────────────────────────────────────────
        ("exercise_created", "Exercice créé"),
        ("question_added", "Question ajoutée"),
        # ── Olympiades ───────────────────────────────────────────
        ("olympiad_created", "Olympiade créée"),
        ("olympiad_closed", "Olympiade clôturée"),
        ("ranking_computed", "Classement calculé"),
        # ── Département / Parcours ───────────────────────────────
        ("department_created", "Département créé"),
        ("cadre_assigned", "Cadre assigné"),
        # ── Soumissions ──────────────────────────────────────────
        ("submission_graded", "Soumission corrigée"),
        # ── Connexion ────────────────────────────────────────────
        ("login", "Connexion"),
        ("logout", "Déconnexion"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="historique_activites",
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    description = models.TextField(blank=True)

    # Données contextuelles JSON (titre du cours, nom de l'enseignant, etc.)
    data = models.JSONField(default=dict, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    # Référence optionnelle vers l'objet concerné
    objet_id = models.PositiveIntegerField(null=True, blank=True)
    objet_type = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = "yeki_historiqueactivite"
        ordering = ["-timestamp"]
        verbose_name = "Activité"
        verbose_name_plural = "Historique des activités"

    def __str__(self):
        return (
            f"[{self.user.username}] {self.get_action_display()} — {self.timestamp:%d/%m/%Y %H:%M}"
        )


# ─────────────────────────────────────────────────────────────────
# HELPER : enregistrer une activité facilement depuis n'importe
#          quelle view
# ─────────────────────────────────────────────────────────────────


def enregistrer_activite(
    user,
    action: str,
    description: str = "",
    data: dict = None,
    objet_id: int = None,
    objet_type: str = "",
):
    """
    Crée une entrée HistoriqueActivite.

    Usage dans une view :
        from apps.core.models import enregistrer_activite
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
            user=user,
            action=action,
            description=description,
            data=data or {},
            objet_id=objet_id,
            objet_type=objet_type,
        )
        return True
    except Exception:
        # Volontairement large : le journal d'activité ne doit jamais faire
        # échouer l'action métier qui l'appelle, quelle que soit la cause.
        logger.exception("Échec enregistrement HistoriqueActivite (action=%s)", action)
        return False


class AppVersion(models.Model):
    PLATFORM_CHOICES = [
        ("android", "Android"),
        ("desktop", "Desktop"),
        ("ios", "iOS"),
        ("web", "Web"),
    ]

    platform = models.CharField(
        max_length=20, choices=PLATFORM_CHOICES, default="android", help_text="Plateforme cible"
    )
    version_code = models.PositiveIntegerField(
        help_text="Numéro de version interne (ex: 2, 3, 4...)"
    )
    version_name = models.CharField(max_length=20, help_text="Nom de version (ex: v1.0.3)")
    download_url = models.URLField(help_text="URL de téléchargement (Firebase Storage)")
    changelog = models.TextField(blank=True, help_text="Description des nouveautés")
    min_version_code = models.PositiveIntegerField(default=1, help_text="Version minimale requise")
    force_update = models.BooleanField(
        default=False, help_text="Si True, oblige l'utilisateur à mettre à jour"
    )
    is_active = models.BooleanField(default=True, help_text="Version active/public")
    file_size = models.PositiveIntegerField(default=0, help_text="Taille du fichier en octets")
    release_date = models.DateTimeField(default=timezone.now, help_text="Date de publication")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "yeki_appversion"
        ordering = ["-version_code"]
        verbose_name = "Version de l'application"
        verbose_name_plural = "Versions de l'application"
        unique_together = ("platform", "version_code")

    def __str__(self):
        return f"{self.get_platform_display()} - {self.version_name} (code: {self.version_code})"


# ─────────────────────────────────────────────────────────────────
# PARAMÈTRES SYSTÈME
# Valeurs métier configurables sans redéploiement (CDC_BACKEND §7.2,
# §15 Phase 2, §16) : poids, taux, commissions, seuils, codes USSD,
# numéros, frais... Modèle clé/valeur minimal ; d'autres modèles dédiés
# (ex: FraisOperateur) restent séparés pour les grilles tarifaires.
# ─────────────────────────────────────────────────────────────────


class ParametreSysteme(models.Model):
    """
    Paramètre système clé/valeur, éditable par l'administrateur général
    depuis l'admin Django sans redéploiement. Voir `ParametreSysteme.get()`
    pour la lecture depuis le code (jamais de valeur en dur, jamais dans
    settings.py — voir docs/API_FOUNDATIONS.md et docs/AUDIT_BACKEND.md §6).

    P2.4 : `.get()` passe par un cache mémoire (voir `apps/core/signals.py`
    pour l'invalidation à l'écriture) — ces paramètres sont lus très
    fréquemment (chaque appel IA, chaque paiement), un aller-retour DB à
    chaque lecture serait coûteux pour rien.
    """

    TYPE_CHOICES = [
        ("string", "Texte"),
        ("int", "Entier"),
        ("float", "Décimal"),
        ("bool", "Booléen"),
    ]

    cle = models.CharField(max_length=100, unique=True, db_index=True)
    valeur = models.TextField(blank=True)
    # Purement descriptif (aide l'administrateur à savoir comment
    # interpréter `valeur` dans l'admin) — n'altère PAS le contrat de
    # retour de `.get()`, qui reste une chaîne comme avant (le typage/cast
    # reste à la charge de l'appelant, comme pour toute valeur de
    # `request.data`/env var dans ce projet).
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default="string")
    description = models.TextField(blank=True)
    # Rôle informatif (ex: 'admin') — non un champ de rôle appliqué par un
    # contrôle d'accès dans cette tâche (non spécifié par le CDC), utile
    # pour documenter qui est censé pouvoir éditer ce paramètre.
    modifiable_par = models.CharField(max_length=30, blank=True, default="admin")

    class Meta:
        db_table = "yeki_parametre_systeme"
        verbose_name = "Paramètre système"
        verbose_name_plural = "Paramètres système"

    def __str__(self):
        return self.cle

    @classmethod
    def _cache_key(cls, cle):
        return f"parametre_systeme:{cle}"

    @classmethod
    def get(cls, cle, default=None):
        from django.core.cache import cache

        cache_key = cls._cache_key(cle)
        valeur = cache.get(cache_key)
        if valeur is not None:
            return valeur

        try:
            valeur = cls.objects.get(cle=cle).valeur
        except cls.DoesNotExist:
            return default

        cache.set(cache_key, valeur, timeout=None)
        return valeur
