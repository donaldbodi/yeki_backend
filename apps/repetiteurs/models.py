from django.db import models

from apps.accounts.models import Profile
from apps.core.models import ParametreSysteme
from apps.formation.models import Cours


# ═══════════════════════════════════════════════════════════════
# RÉPÉTITEURS (Partie 7)
# ═══════════════════════════════════════════════════════════════


def _tarif_repetiteur_defaut():
    """
    P2.4 : callable (pas une constante figée à l'import) — évaluée à
    chaque création de fiche, donc éditable sans redéploiement via
    ParametreSysteme['tarif_repetiteur_mensuel'].
    """
    return int(ParametreSysteme.get("tarif_repetiteur_mensuel", default=7500))


class Repetiteur(models.Model):
    """
    Fiche "répétiteur" d'un enseignant secondaire pour un cours donné.
    Consultée depuis CoursDetailPage ("Voir les répétiteurs") pour trouver
    un enseignant disponible par ville, avec contact WhatsApp direct.
    """

    enseignant = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        # P2.1 : 'enseignant_secondaire' n'a jamais existé dans
        # Profile.USER_TYPES (contrainte morte, docs/AUDIT_BACKEND.md §7) —
        # « enseignant secondaire » désigne en réalité le grade de base
        # 'enseignant' (clarification actée). Un enseignant ne peut avoir de
        # fiche répétiteur que si le Service Client l'a validé
        # (is_repetiteur=True).
        limit_choices_to={"user_type": "enseignant", "is_repetiteur": True},
        related_name="fiches_repetiteur",
    )
    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, related_name="repetiteurs")
    ville = models.CharField(max_length=100)
    telephone = models.CharField(
        max_length=20, help_text="Format international recommandé, ex: 2376XXXXXXXX"
    )
    disponible = models.BooleanField(default=True)
    tarif_mensuel = models.PositiveIntegerField(
        default=_tarif_repetiteur_defaut, help_text="Tarif mensuel en FCFA"
    )
    note_moyenne = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "yeki_repetiteur"
        ordering = ["-disponible", "ville"]
        verbose_name = "Répétiteur"

    def __str__(self):
        return f"{self.enseignant} — {self.cours.titre} ({self.ville})"

    @property
    def lien_whatsapp(self):
        """
        Génère le lien wa.me vers l'UNIQUE numéro WhatsApp du Service
        Client (P2.1, CDC §7.2) — PAS le téléphone de l'enseignant. Le
        message contient le nom et le grade de l'enseignant, un lien vers
        son profil, et le tarif, pour que le Service Client sache
        immédiatement qui contacte et pourquoi.

        Le numéro et la base d'URL de profil viennent de `ParametreSysteme`
        (jamais de settings.py — voir docs/API_FOUNDATIONS.md) : tant que
        l'administrateur général ne les a pas renseignés, la valeur est
        vide et le lien reflète cet état plutôt que de planter.
        """
        import urllib.parse

        grade = (
            self.enseignant.get_user_type_display()
            if hasattr(self.enseignant, "get_user_type_display")
            else ""
        )
        nom = self.enseignant.user.get_full_name() or self.enseignant.user.username

        url_base = ParametreSysteme.get("url_base_frontend", default="")
        lien_profil = (
            f"{url_base.rstrip('/')}/profil/{self.enseignant.user_id}"
            if url_base
            else "(lien de profil non configuré)"
        )

        message = (
            f"Bonjour, je souhaite prendre des cours avec {nom} ({grade}) "
            f"pour la matière {self.cours.titre}. Profil : {lien_profil}. "
            f"Tarif indiqué : {self.tarif_mensuel} FCFA la matière le mois."
        )

        numero = ParametreSysteme.get("whatsapp_service_client", default="")
        numero = numero.replace(" ", "").replace("+", "")
        return f"https://wa.me/{numero}?text={urllib.parse.quote(message)}"
