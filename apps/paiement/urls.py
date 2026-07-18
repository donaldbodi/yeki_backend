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
]
