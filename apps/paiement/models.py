import uuid
from datetime import timedelta

from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone

from apps.accounts.models import Profile
from apps.evaluation.models import Olympiade
from apps.formation.models import Departement


class Paiement(models.Model):
    """
    Registre centralisé de tous les paiements Yeki.
    Couvre : abonnements, prépa concours (accès au dept), olympiades payantes.
    Commission Yeki : 15% sur tout paiement lié à un département payant.
    """

    TYPE_CHOICES = [
        ("abonnement_mensuel", "Abonnement mensuel cursus"),
        ("abonnement_annuel", "Abonnement annuel cursus"),
        ("acces_departement", "Accès département (concours/formation)"),
        ("olympiade", "Participation olympiade"),
        ("olympiade_participation", "Participation apprenant à une olympiade"),
    ]
    MOYEN_CHOICES = [
        ("mtn_momo", "MTN Mobile Money"),
        ("orange_om", "Orange Money"),
        ("carte", "Carte bancaire"),
        ("wallet", "Portefeuille Yeki"),
        ("cinetpay", "CinetPay"),
    ]
    STATUT_CHOICES = [
        ("en_attente", "En attente"),
        ("succes", "Succès"),
        ("echec", "Échec"),
        ("rembourse", "Remboursé"),
    ]

    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="paiements")
    type_paiement = models.CharField(max_length=25, choices=TYPE_CHOICES)
    moyen = models.CharField(max_length=15, choices=MOYEN_CHOICES)
    montant = models.PositiveIntegerField(help_text="Montant en FCFA")
    statut = models.CharField(max_length=15, choices=STATUT_CHOICES, default="en_attente")
    reference = models.CharField(max_length=100, unique=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    transaction_id = models.CharField(
        max_length=200, blank=True, help_text="ID transaction opérateur"
    )

    # Lien optionnel vers olympiade (pour paiement global)
    olympiade_liee = models.ForeignKey(
        Olympiade,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paiements_globaux",
    )

    # Commission Yeki prélevée (15% si paiement > 0 pour département)
    commission_yeki = models.PositiveIntegerField(default=0, help_text="Part Yeki en FCFA")

    class Meta:
        db_table = "yeki_paiement"
        ordering = ["-date"]
        verbose_name = "Paiement"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"YEKI-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.reference} – {self.utilisateur.username} – {self.montant} FCFA [{self.statut}]"
        )


# ─────────────────────────────────────────────────────────────────
# PAIEMENT OLYMPIADE (pour les participants)
# ─────────────────────────────────────────────────────────────────


class PaiementOlympiade(models.Model):
    """
    Paiement effectué par un apprenant pour participer à une olympiade.
    """

    STATUT_CHOICES = [
        ("en_attente", "En attente"),
        ("paye", "Payé"),
        ("rembourse", "Remboursé"),
    ]

    apprenant = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="paiements_olympiade"
    )
    olympiade = models.ForeignKey(
        Olympiade, on_delete=models.CASCADE, related_name="paiements_participants"
    )
    montant = models.PositiveIntegerField()
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default="en_attente")
    reference = models.CharField(max_length=100, unique=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    paye_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "yeki_paiementolympiade"
        unique_together = ("apprenant", "olympiade")
        ordering = ["-cree_le"]
        verbose_name = "Paiement Olympiade"
        verbose_name_plural = "Paiements Olympiades"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"PAY-OLYMP-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.apprenant.username} → {self.olympiade.titre} ({self.statut})"


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
        ("mensuel", "Mensuel – 1 500 FCFA"),
        ("annuel", "Annuel – 13 000 FCFA"),
    ]
    TARIFS = {"mensuel": 1500, "annuel": 13000}

    utilisateur = models.OneToOneField(User, on_delete=models.CASCADE, related_name="abonnement")
    type_abonnement = models.CharField(max_length=10, choices=TYPE_CHOICES)
    actif = models.BooleanField(default=True)
    debut = models.DateTimeField(auto_now_add=True)
    fin = models.DateTimeField()
    paiement = models.ForeignKey(Paiement, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = "yeki_abonnementpremium"
        ordering = ["-debut"]
        verbose_name = "Abonnement Premium"

    def __str__(self):
        return (
            f"{self.utilisateur.username} – " f"{self.type_abonnement} (expire {self.fin:%d/%m/%Y})"
        )

    @property
    def est_actif(self):
        return self.actif and timezone.now() < self.fin

    def renouveler(self, type_abonnement: str):
        self.type_abonnement = type_abonnement
        jours = 30 if type_abonnement == "mensuel" else 365
        self.fin = timezone.now() + timedelta(days=jours)
        self.actif = True
        self.save()


# ══════════════════════════════════════════════════════════════════
# YEKI WALLET — PORTEFEUILLE UTILISATEUR
# Chaque utilisateur possède un portefeuille rechargeable.
# Sert à payer : IA (débit auto), cours, formations, olympiades.
# La commission Yeki (IA) va dans le compte principal Yeki.
# ══════════════════════════════════════════════════════════════════

TARIF_IA_PAR_TOKEN = 0.002  # 0.002 FCFA par token OpenAI (gpt-3.5-turbo)
COMMISSION_YEKI_IA = 5  # 5 FCFA commission Yeki par requête IA
TARIF_IA_MIN_PAR_REQUETE = 10  # minimum 10 FCFA par requête IA


class YekiWallet(models.Model):
    """Portefeuille rechargeable de l'utilisateur."""

    utilisateur = models.OneToOneField(User, on_delete=models.CASCADE, related_name="wallet")
    solde = models.PositiveIntegerField(default=0, help_text="Solde en FCFA")
    total_recharge = models.PositiveIntegerField(default=0)
    total_depense = models.PositiveIntegerField(default=0)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "yeki_yekiwallet"
        verbose_name = "Portefeuille Yéki"

    def __str__(self):
        return f"{self.utilisateur.username} — {self.solde} FCFA"

    def peut_debiter(self, montant: int) -> bool:
        return self.solde >= montant

    @transaction.atomic
    def debiter(self, montant: int, description: str = "") -> bool:
        if not self.peut_debiter(montant):
            return False
        self.solde -= montant
        self.total_depense += montant
        self.save(update_fields=["solde", "total_depense", "modifie_le"])
        WalletTransaction.objects.create(
            wallet=self, type_transaction="debit", montant=montant, description=description
        )
        return True

    @transaction.atomic
    def crediter(self, montant: int, description: str = "", reference: str = ""):
        self.solde += montant
        self.total_recharge += montant
        self.save(update_fields=["solde", "total_recharge", "modifie_le"])
        WalletTransaction.objects.create(
            wallet=self,
            type_transaction="credit",
            montant=montant,
            description=description,
            reference_paiement=reference,
        )

    @classmethod
    def get_or_create_wallet(cls, user):
        wallet, _ = cls.objects.get_or_create(utilisateur=user)
        return wallet


class WalletTransaction(models.Model):
    """Historique des mouvements du portefeuille."""

    TYPE_CHOICES = [
        ("credit", "Crédit (recharge)"),
        ("debit", "Débit (dépense)"),
    ]
    wallet = models.ForeignKey(YekiWallet, on_delete=models.CASCADE, related_name="transactions")
    type_transaction = models.CharField(max_length=10, choices=TYPE_CHOICES)
    montant = models.PositiveIntegerField()
    description = models.CharField(max_length=255, blank=True)
    reference_paiement = models.CharField(max_length=100, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "yeki_wallettransaction"
        ordering = ["-cree_le"]
        verbose_name = "Transaction Wallet"

    def __str__(self):
        sign = "+" if self.type_transaction == "credit" else "-"
        return f"{sign}{self.montant} FCFA — {self.description}"


class YekiCompteIA(models.Model):
    """
    Compte central Yeki alimenté par les commissions sur l'IA.
    Singleton (id=1). Consultation admin uniquement.
    """

    total_commissions = models.PositiveIntegerField(default=0)
    nb_requetes_ia = models.PositiveIntegerField(default=0)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "yeki_yekicompteia"
        verbose_name = "Compte Central Yéki IA"

    @classmethod
    def crediter_commission(cls, montant: int):
        obj, _ = cls.objects.get_or_create(pk=1)
        obj.total_commissions += montant
        obj.nb_requetes_ia += 1
        obj.save(update_fields=["total_commissions", "nb_requetes_ia", "modifie_le"])

    def __str__(self):
        return f"Compte Yéki IA — {self.total_commissions} FCFA ({self.nb_requetes_ia} requêtes)"


class CinetPayTransaction(models.Model):
    """Transaction CinetPay"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="cinetpay_transactions")
    amount = models.PositiveIntegerField()
    reference = models.CharField(max_length=100, unique=True)
    transaction_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "En attente"),
            ("success", "Succès"),
            ("failed", "Échec"),
        ],
        default="pending",
    )
    payment_method = models.CharField(
        max_length=20,
        choices=[
            ("mtn_momo", "MTN Mobile Money"),
            ("orange_money", "Orange Money"),
            ("card", "Carte bancaire"),
        ],
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "yeki_cinetpaytransaction"

    def __str__(self):
        return f"CinetPay {self.reference} - {self.status}"


# ══════════════════════════════════════════════════════════════════
# FRAIS OPÉRATEUR (P2.4, CDC §16)
# Les opérateurs Mobile Money révisent leurs tarifs sans préavis — un tarif
# en dur = un déploiement à chaque changement. Grille de frais paramétrable
# en base, par tranche de montant.
# ══════════════════════════════════════════════════════════════════

OPERATEURS_MOBILE_MONEY = [
    ("orange_money", "Orange Money"),
    ("mtn_momo", "MTN Mobile Money"),
]


class FraisOperateur(models.Model):
    operateur = models.CharField(max_length=20, choices=OPERATEURS_MOBILE_MONEY)
    tranche_min = models.PositiveIntegerField(help_text="Montant minimum de la tranche, en FCFA")
    tranche_max = models.PositiveIntegerField(help_text="Montant maximum de la tranche, en FCFA")
    frais_fixe = models.PositiveIntegerField(default=0, help_text="Frais fixe en FCFA")
    frais_pourcent = models.FloatField(default=0.0, help_text="Frais en pourcentage du montant")

    class Meta:
        db_table = "yeki_frais_operateur"
        verbose_name = "Frais opérateur"
        verbose_name_plural = "Frais opérateur"
        ordering = ["operateur", "tranche_min"]

    def __str__(self):
        return f"{self.get_operateur_display()} [{self.tranche_min}-{self.tranche_max}]"


def calculer_frais(operateur: str, montant: int) -> tuple:
    """
    Cherche la tranche de frais applicable pour cet opérateur/montant.
    Retourne (frais, montant_net). Aucune tranche configurée → frais=0
    (dégradation gracieuse — la grille est vide tant que l'admin général ne
    l'a pas remplie, ce n'est pas une erreur).
    """
    tranche = FraisOperateur.objects.filter(
        operateur=operateur, tranche_min__lte=montant, tranche_max__gte=montant
    ).first()
    if not tranche:
        return 0, montant
    frais = tranche.frais_fixe + int(montant * tranche.frais_pourcent / 100)
    return frais, montant - frais


# ══════════════════════════════════════════════════════════════════
# DEMANDE DE PAIEMENT MANUEL (P2.4, CDC §9.1)
# L'apprenant paie hors application (USSD/agence Orange Money/MTN MoMo) et
# soumet son ID de transaction pour vérification manuelle par le Service
# Client. CONTRAINTE ESSENTIELLE : un même (operateur, id_transaction) ne
# peut être soumis qu'une fois — sinon le même dépôt pourrait être réclamé
# deux fois, pour deux achats, voire par deux comptes différents.
# ══════════════════════════════════════════════════════════════════


class DemandePaiementManuelle(models.Model):
    CATEGORIES = [
        ("abonnement", "Abonnement Premium"),
        ("olympiade", "Participation olympiade"),
        ("formation", "Inscription formation"),
        ("recharge", "Recharge portefeuille"),
        ("presentiel", "Supplément présentiel"),
    ]
    STATUTS = [
        ("en_attente", "En attente"),
        ("validee", "Validée"),
        ("refusee", "Refusée"),
    ]

    apprenant = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name="demandes_paiement"
    )
    categorie = models.CharField(max_length=20, choices=CATEGORIES, db_index=True)
    departement = models.ForeignKey(Departement, null=True, blank=True, on_delete=models.SET_NULL)
    objet_id = models.PositiveIntegerField(
        null=True, blank=True, help_text="ID de l'olympiade / formation concernée"
    )
    montant = models.PositiveIntegerField()
    operateur = models.CharField(max_length=20, choices=OPERATEURS_MOBILE_MONEY)
    id_transaction = models.CharField(max_length=100, help_text="Saisi par l'apprenant")
    numero_emetteur = models.CharField(max_length=20, blank=True)
    statut = models.CharField(max_length=15, choices=STATUTS, default="en_attente", db_index=True)
    motif_refus = models.TextField(blank=True)
    traite_par = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="paiements_traites",
    )
    date_creation = models.DateTimeField(auto_now_add=True, db_index=True)
    date_traitement = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "yeki_demande_paiement_manuelle"
        verbose_name = "Demande de paiement manuel"
        constraints = [
            models.UniqueConstraint(
                fields=["operateur", "id_transaction"],
                name="unique_transaction_par_operateur",
            )
        ]

    def __str__(self):
        return f"{self.apprenant} — {self.montant} FCFA ({self.get_statut_display()})"


# ══════════════════════════════════════════════════════════════════
# DEMANDE DE RETRAIT (P2.4, CDC §5.6)
# ══════════════════════════════════════════════════════════════════


class DemandeRetrait(models.Model):
    STATUTS = [
        ("en_attente", "En attente"),
        ("validee", "Validée"),
        ("refusee", "Refusée"),
        ("envoyee", "Envoyée"),
    ]

    beneficiaire = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name="demandes_retrait"
    )
    montant_brut = models.PositiveIntegerField(help_text="Montant demandé, en FCFA")
    frais_operateur = models.PositiveIntegerField(
        default=0, help_text="Calculé selon la grille FraisOperateur au moment de la demande"
    )
    montant_net = models.PositiveIntegerField(help_text="Montant effectivement envoyé")
    operateur = models.CharField(max_length=20, choices=OPERATEURS_MOBILE_MONEY)
    numero_destination = models.CharField(max_length=20, help_text="Numéro du bénéficiaire")
    statut = models.CharField(max_length=15, choices=STATUTS, default="en_attente", db_index=True)
    motif_refus = models.TextField(blank=True)
    traite_par = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retraits_traites",
    )
    date_creation = models.DateTimeField(auto_now_add=True, db_index=True)
    date_traitement = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "yeki_demande_retrait"
        verbose_name = "Demande de retrait"

    def __str__(self):
        return f"{self.beneficiaire} — {self.montant_net} FCFA ({self.get_statut_display()})"
