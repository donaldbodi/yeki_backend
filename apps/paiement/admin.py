from django.contrib import admin

from apps.paiement.models import (
    CinetPayTransaction,
    DemandePaiementManuelle,
    DemandeRetrait,
    FraisOperateur,
    Paiement,
)


@admin.register(FraisOperateur)
class FraisOperateurAdmin(admin.ModelAdmin):
    """P9.4 : seule interface pour peupler la grille de frais opérateur —
    sans elle, `calculer_frais()` dégrade à 0 (aucune tranche configurée)."""

    list_display = ["operateur", "tranche_min", "tranche_max", "frais_fixe", "frais_pourcent"]
    list_filter = ["operateur"]
    ordering = ["operateur", "tranche_min"]


@admin.register(DemandeRetrait)
class DemandeRetraitAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "beneficiaire",
        "montant_brut",
        "montant_net",
        "operateur",
        "statut",
        "date_creation",
    ]
    list_filter = ["statut", "operateur"]
    search_fields = ["beneficiaire__user__username", "numero_destination"]
    ordering = ["-date_creation"]
    readonly_fields = ["date_creation", "date_traitement"]


@admin.register(DemandePaiementManuelle)
class DemandePaiementManuelleAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "apprenant",
        "categorie",
        "montant",
        "montant_constate",
        "operateur",
        "statut",
        "date_creation",
    ]
    list_filter = ["statut", "categorie", "operateur"]
    search_fields = ["apprenant__user__username", "id_transaction"]
    ordering = ["-date_creation"]
    readonly_fields = ["date_creation", "date_traitement"]


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "utilisateur",
        "type_paiement",
        "moyen",
        "montant",
        "commission_yeki",
        "statut",
        "date",
    ]
    list_filter = ["statut", "moyen", "type_paiement"]
    search_fields = ["utilisateur__username", "reference", "transaction_id"]
    ordering = ["-date"]


@admin.register(CinetPayTransaction)
class CinetPayTransactionAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "amount", "reference", "status", "payment_method", "created_at"]
    list_filter = ["status", "payment_method"]
    search_fields = ["user__username", "reference", "transaction_id"]
    ordering = ["-created_at"]
