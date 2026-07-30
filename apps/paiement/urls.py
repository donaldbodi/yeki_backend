from django.urls import path

from apps.paiement.views import (
    HistoriquePaiementsView,
    StatutAbonnementView,
    WalletSoldeView,
    WalletRechargerView,
    WalletPayerView,
    WalletVerifierIAPView,
    InitierPaiementCinetPayView,
    CinetPayWebhookView,
    VerifierPaiementCinetPayView,
    SoumettrePaiementManuelView,
    DemanderRetraitView,
    MesDemandesPaiementManuelView,
    MesDemandesRetraitView,
    FileAttentePaiementsServiceClientView,
    FileAttenteRetraitsServiceClientView,
    ValiderPaiementManuelView,
    RefuserPaiementManuelView,
    ValiderRetraitView,
    RefuserRetraitView,
    AdminTransactionsView,
    AdminDashboardFinancierView,
    ServiceClientStatistiquesView,
)

urlpatterns = [
    # ── PAIEMENT ──────────────────────────────────────────────────
    path("paiements/historique/", HistoriquePaiementsView.as_view(), name="paiements-historique"),
    path("abonnement/statut/", StatutAbonnementView.as_view(), name="abonnement-statut"),
    # ── WALLET — PORTEFEUILLE YEKI ────────────────────────────────
    path("wallet/solde/", WalletSoldeView.as_view(), name="wallet-solde"),
    path("wallet/recharger/", WalletRechargerView.as_view(), name="wallet-recharger"),
    path("wallet/payer/", WalletPayerView.as_view(), name="wallet-payer"),
    path("wallet/verifier-iap/", WalletVerifierIAPView.as_view(), name="wallet-verifier-iap"),
    # Paiements - CinetPay uniquement
    path(
        "paiements/cinetpay/initier/",
        InitierPaiementCinetPayView.as_view(),
        name="cinetpay-initier",
    ),
    path("paiements/cinetpay/notify/", CinetPayWebhookView.as_view(), name="cinetpay-webhook"),
    path(
        "paiements/cinetpay/verifier/<str:reference>/",
        VerifierPaiementCinetPayView.as_view(),
        name="cinetpay-verifier",
    ),
    # ── Paiement manuel / retrait (P2.4) ──────────────────────────
    path(
        "paiements/manuel/soumettre/",
        SoumettrePaiementManuelView.as_view(),
        name="paiement-manuel-soumettre",
    ),
    path("retraits/demander/", DemanderRetraitView.as_view(), name="retrait-demander"),
    # ── Paiement manuel : validation Service Client (P9.2) ────────
    path(
        "paiements/manuel/mes-demandes/",
        MesDemandesPaiementManuelView.as_view(),
        name="paiement-manuel-mes-demandes",
    ),
    path(
        "service-client/paiements/",
        FileAttentePaiementsServiceClientView.as_view(),
        name="service-client-paiements-liste",
    ),
    path(
        "service-client/paiements/<int:pk>/valider/",
        ValiderPaiementManuelView.as_view(),
        name="service-client-paiement-valider",
    ),
    path(
        "service-client/paiements/<int:pk>/refuser/",
        RefuserPaiementManuelView.as_view(),
        name="service-client-paiement-refuser",
    ),
    # ── Retrait : validation Service Client (P9.4) ────────────────
    path(
        "retraits/mes-demandes/",
        MesDemandesRetraitView.as_view(),
        name="retrait-mes-demandes",
    ),
    path(
        "service-client/retraits/",
        FileAttenteRetraitsServiceClientView.as_view(),
        name="service-client-retraits-liste",
    ),
    path(
        "service-client/retraits/<int:pk>/valider/",
        ValiderRetraitView.as_view(),
        name="service-client-retrait-valider",
    ),
    path(
        "service-client/retraits/<int:pk>/refuser/",
        RefuserRetraitView.as_view(),
        name="service-client-retrait-refuser",
    ),
    # ── Admin général : transactions & tableau de bord financier (P9.6) ──
    path("admin/transactions/", AdminTransactionsView.as_view(), name="admin-transactions"),
    path(
        "admin/dashboard-financier/",
        AdminDashboardFinancierView.as_view(),
        name="admin-dashboard-financier",
    ),
    # ── Service Client : statistiques (P9.5) ──────────────────────
    path(
        "service-client/statistiques/",
        ServiceClientStatistiquesView.as_view(),
        name="service-client-statistiques",
    ),
]
