import hashlib
import hmac
import json
import logging
import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta

import requests

from rest_framework.parsers import JSONParser
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

from apps.core.exceptions import ConflictError, PaymentRequiredError, InsufficientBalanceError
from apps.core.models import ParametreSysteme, enregistrer_activite
from apps.core.pagination import PaginatedListMixin
from apps.formation.models import Cours, Departement
from apps.paiement.models import (
    Paiement,
    AbonnementPremium,
    YekiWallet,
    YekiCompteIA,
    WalletTransaction,
    CinetPayTransaction,
    DemandePaiementManuelle,
    DemandeRetrait,
    calculer_frais,
)
from apps.paiement.providers import CinetPayProvider, ManuelProvider, mode_paiement_actif
from yeki.permissions import IsAdminGeneral, IsServiceClient

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from drf_spectacular.types import OpenApiTypes
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
    EXEMPLE_PAYMENT_REQUIRED,
    EXEMPLE_INSUFFICIENT_BALANCE,
    EXEMPLE_THROTTLED,
)

logger = logging.getLogger(__name__)

# P9.7 : traduit le vocabulaire `type_paiement` de CinetPay
# (InitierPaiementCinetPayView) vers le vocabulaire `categorie` de
# `finaliser_paiement` (celui de `DemandePaiementManuelle.CATEGORIES`) —
# un seul point de mapping, pas un `if/elif` de plus dans le webhook.
CATEGORIE_PAR_TYPE_CINETPAY = {
    "wallet_recharge": "recharge",
    "acces_departement": "formation",
    "olympiade": "olympiade",
    "abonnement_mensuel": "abonnement",
    "abonnement_annuel": "abonnement",
}

# P9.6 : traduit `Paiement.type_paiement` (vocabulaire large, tous
# fournisseurs confondus) vers la `categorie` affichée à l'admin général —
# même esprit que CATEGORIE_PAR_TYPE_CINETPAY ci-dessus, vocabulaire
# légèrement différent car `Paiement.TYPE_CHOICES` distingue
# "olympiade"/"olympiade_participation" (deux chemins historiques
# différents, wallet-direct vs. global) sous une même catégorie affichée.
CATEGORIE_PAR_TYPE_PAIEMENT = {
    "recharge_wallet": "recharge",
    "abonnement_mensuel": "abonnement",
    "abonnement_annuel": "abonnement",
    "olympiade": "olympiade",
    "olympiade_participation": "olympiade",
    "acces_departement": "formation",
    "supplement_presentiel": "presentiel",
}
TYPES_PAR_CATEGORIE = {}
for _type_paiement, _categorie in CATEGORIE_PAR_TYPE_PAIEMENT.items():
    TYPES_PAR_CATEGORIE.setdefault(_categorie, []).append(_type_paiement)


def _verifier_signature_webhook_cinetpay(request) -> bool:
    """
    Vérifie la signature HMAC-SHA256 du webhook CinetPay (en-tête `X-Token`,
    calculée sur le corps brut de la requête, secret `CINETPAY_WEBHOOK_SECRET`).

    Secret non configuré → échec SYSTÉMATIQUE (fail-closed) : l'absence de
    secret ne doit jamais être interprétée comme "vérification non
    nécessaire" (P9.7 — un webhook de paiement non vérifié est une
    invitation à créditer des comptes gratuitement).

    Le nom exact de l'en-tête et la composition précise de la signature
    doivent être confirmés auprès du tableau de bord marchand CinetPay
    (Notifications) avant la mise en production réelle — ce qui compte ici
    est le MÉCANISME (HMAC + comparaison à temps constant), indépendamment
    du détail exact du format CinetPay, à ajuster si besoin sans changer
    l'appelant.
    """
    secret = settings.CINETPAY_WEBHOOK_SECRET
    if not secret:
        return False
    signature_recue = request.headers.get("X-Token", "")
    if not signature_recue:
        return False
    signature_attendue = hmac.new(secret.encode("utf-8"), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_attendue, signature_recue)


def _verifier_aupres_cinetpay(transaction_id: str) -> dict:
    """
    Interroge l'API CinetPay (`/v2/payment/check`) pour le statut et le
    montant RÉELS d'une transaction — ne JAMAIS se fier uniquement au corps
    d'un webhook pour créditer quoi que ce soit (P9.7). Factorisé pour être
    appelé à la fois par `CinetPayWebhookView` (revérification obligatoire
    avant crédit) et `VerifierPaiementCinetPayView` (rafraîchissement
    optionnel côté client) — un seul appel HTTP à maintenir.

    Retourne `{"status": ..., "amount": ...}`. Lève `requests.RequestException`
    en cas d'échec de communication ou de réponse CinetPay non exploitable.
    """
    response = requests.post(
        "https://api-checkout.cinetpay.com/v2/payment/check",
        json={
            "site_id": settings.CINETPAY_SITE_ID,
            "apikey": settings.CINETPAY_API_KEY,
            "transaction_id": transaction_id,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 200:
        raise requests.RequestException(f"CinetPay check a échoué : {data}")
    payload = data.get("data", {})
    return {"status": payload.get("status"), "amount": payload.get("amount")}


@extend_schema_view(
    post=extend_schema(
        summary="Initier un paiement CinetPay",
        description=(
            "Crée une transaction CinetPay (Mobile Money MTN/Orange ou carte) et "
            "retourne l'URL de paiement à ouvrir côté client. Utilisé pour recharger "
            "le wallet, accéder à un département, s'inscrire à une olympiade ou "
            "souscrire un abonnement premium (mensuel/annuel). La transaction est "
            "créée avec le statut `pending` ; elle sera confirmée de façon "
            "asynchrone par le webhook `CinetPayWebhookView`.\n\n"
            "Réponse 200 : `{reference, payment_url, status, message}`.\n"
            "Limité par `throttle_scope='paiement'` (anti-spam)."
        ),
        tags=["paiement"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class InitierPaiementCinetPayView(APIView):
    """
    POST /api/paiements/cinetpay/initier/

    Body:
    {
        "type_paiement": "wallet_recharge" | "acces_departement" | "olympiade" | "abonnement_mensuel" | "abonnement_annuel",
        "montant": 5000,
        "payment_method": "mtn_momo" | "orange_money" | "card",
        "phone": "691234567",  // Optionnel pour carte
        "departement_id": 1,   // Si type = acces_departement
        "olympiade_id": 2      // Si type = olympiade
    }
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "paiement"  # anti-spam de demandes (CDC_BACKEND §2.5) : 10/min

    def post(self, request):
        # P9.7 : garde serveur — CinetPay peut être éteint via
        # ParametreSysteme['mode_paiement'] sans redéploiement. Défense en
        # profondeur : le frontend masque déjà cette option, mais un appel
        # direct à l'API ne doit pas pouvoir la contourner.
        if mode_paiement_actif() not in ("cinetpay", "les_deux"):
            return Response({"detail": "CinetPay n'est pas disponible actuellement."}, status=403)

        type_paiement = request.data.get("type_paiement", "").strip()
        montant = request.data.get("montant")
        payment_method = request.data.get("payment_method", "mtn_momo").strip()
        phone = request.data.get("phone", "").strip()
        departement_id = request.data.get("departement_id")
        olympiade_id = request.data.get("olympiade_id")

        # ── Validation ──────────────────────────────────────────
        types_valides = [
            "wallet_recharge",
            "acces_departement",
            "olympiade",
            "abonnement_mensuel",
            "abonnement_annuel",
        ]
        if type_paiement not in types_valides:
            return Response(
                {"detail": f"type_paiement invalide. Valeurs: {types_valides}"}, status=400
            )

        try:
            montant = int(montant)
            if montant < 500:
                return Response({"detail": "Montant minimum: 500 FCFA"}, status=400)
        except (TypeError, ValueError):
            return Response({"detail": "Montant invalide"}, status=400)

        if type_paiement in ("abonnement_mensuel", "abonnement_annuel") and not departement_id:
            # Rectification : l'abonnement est désormais PAR DÉPARTEMENT —
            # aucun département à défaut à deviner.
            return Response(
                {"detail": "departement_id est obligatoire pour un abonnement premium."}, status=400
            )

        # ── Créer la transaction ────────────────────────────────
        reference = f"YEKI-{uuid.uuid4().hex[:8].upper()}"

        transaction = CinetPayTransaction.objects.create(
            user=request.user,
            amount=montant,
            reference=reference,
            payment_method=payment_method,
            status="pending",
        )

        # ── Préparer les données pour CinetPay ──────────────────
        site_id = settings.CINETPAY_SITE_ID
        api_key = settings.CINETPAY_API_KEY
        notify_url = "https://yeki.pythonanywhere.com/api/paiements/cinetpay/notify/"
        return_url = "https://yeki.pythonanywhere.com/payment-result/"

        # Construire le payload
        payment_data = {
            "amount": montant,
            "currency": "XAF",
            "transaction_id": reference,
            "description": f"Yéki - {type_paiement}",
            "site_id": site_id,
            "apikey": api_key,
            "notify_url": notify_url,
            "return_url": return_url,
            "channels": "ALL",
            "metadata": json.dumps(
                {
                    "user_id": request.user.id,
                    "type_paiement": type_paiement,
                    "departement_id": departement_id,
                    "olympiade_id": olympiade_id,
                    "reference": reference,
                }
            ),
            "customer_name": f"{request.user.first_name} {request.user.last_name}".strip()
            or request.user.username,
            "customer_email": request.user.email,
            "customer_phone_number": phone or "",
            "customer_address": "Cameroun",
        }

        # Ajouter le canal spécifique si demandé
        if payment_method == "mtn_momo":
            payment_data["channels"] = "MOBILE_MONEY"
            payment_data["payment_method"] = "MTN"
        elif payment_method == "orange_money":
            payment_data["channels"] = "MOBILE_MONEY"
            payment_data["payment_method"] = "ORANGE"
        elif payment_method == "card":
            payment_data["channels"] = "CARD"

        try:
            response = requests.post(
                "https://api-checkout.cinetpay.com/v2/payment", json=payment_data, timeout=30
            )

            if response.status_code == 200 or response.status_code == 201:
                data = response.json()
                if data.get("code") in [200, 201]:
                    payment_url = data.get("data", {}).get("payment_url")
                    transaction_id = data.get("data", {}).get("transaction_id")

                    transaction.transaction_id = transaction_id
                    transaction.save()

                    return Response(
                        {
                            "reference": reference,
                            "payment_url": payment_url,
                            "status": "pending",
                            "message": "Paiement initié. Veuillez compléter la transaction.",
                        },
                        status=200,
                    )
                else:
                    transaction.status = "failed"
                    transaction.save()
                    return Response({"detail": data.get("message", "Erreur CinetPay")}, status=400)
            else:
                transaction.status = "failed"
                transaction.save()
                return Response({"detail": "Erreur de communication avec CinetPay"}, status=500)

        except requests.exceptions.RequestException:
            transaction.status = "failed"
            transaction.save()
            logger.exception("CinetPay : échec de communication à l'initiation du paiement")
            return Response({"detail": "Erreur de communication avec CinetPay"}, status=500)


@extend_schema_view(
    post=extend_schema(
        summary="Webhook de notification CinetPay (serveur à serveur)",
        description=(
            "**Webhook serveur-à-serveur** appelé directement par la plateforme "
            "CinetPay après le traitement d'un paiement — ce n'est PAS un endpoint "
            "destiné à être appelé par un utilisateur final ou l'app mobile/web "
            "Yéki. Volontairement sans authentification utilisateur "
            "(`AllowAny`, `authentication_classes=[]`) puisque CinetPay ne "
            "porte pas de token Yéki, et sans `throttle_scope` (le volume est "
            "dicté par CinetPay, pas par un client abusif) — voir "
            "docs/API_FOUNDATIONS.md pour le contexte exact de ce choix.\n\n"
            "Selon le statut reçu (`cpm_result`/`status`), met à jour la "
            "transaction et, en cas de succès, crédite le wallet, active "
            "l'abonnement premium ou confirme l'inscription à l'olympiade "
            "concernée. Réponse 200 : `{status: 'ok'|'already_processed'}`."
        ),
        tags=["paiement"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    ),
)
class CinetPayWebhookView(APIView):
    """
    POST /api/paiements/cinetpay/notify/
    Webhook appelé par CinetPay après paiement
    """

    permission_classes = [AllowAny]  # Public : webhook serveur-à-serveur CinetPay
    authentication_classes = []  # Pas de token utilisateur : CinetPay n'en a pas

    def post(self, request):
        # P9.7 — 1er contrôle, avant tout traitement : signature HMAC
        # obligatoire. Un webhook non signé (ou mal signé) est rejeté sans
        # qu'aucune ligne de crédit ne soit exécutée.
        if not _verifier_signature_webhook_cinetpay(request):
            logger.warning("CinetPay webhook : signature absente ou invalide")
            return Response({"detail": "Signature invalide."}, status=401)

        data = request.data
        transaction_id = data.get("cpm_trans_id") or data.get("transaction_id")
        status_ = data.get("cpm_result") or data.get("status")

        if not transaction_id:
            return Response({"detail": "transaction_id manquant"}, status=400)

        try:
            transaction = CinetPayTransaction.objects.get(transaction_id=transaction_id)
        except CinetPayTransaction.DoesNotExist:
            # Essayer par référence
            reference = data.get("cpm_custom") or data.get("reference")
            if reference:
                try:
                    transaction = CinetPayTransaction.objects.get(reference=reference)
                except CinetPayTransaction.DoesNotExist:
                    return Response({"detail": "Transaction non trouvée"}, status=404)
            else:
                return Response({"detail": "Transaction non trouvée"}, status=404)

        # Ne pas traiter deux fois
        if transaction.status == "success":
            return Response({"status": "already_processed"})

        if status_ in ["00", "ACCEPTED", "SUCCESS", "success"]:
            # P9.7 — 2ᵉ contrôle : revérification OBLIGATOIRE du montant et
            # du statut directement auprès de l'API CinetPay, jamais une
            # confiance aveugle dans le corps du webhook (le corps POST est
            # falsifiable par quiconque connaît/devine l'URL). Un écart —
            # ou un échec de communication — bloque tout crédit.
            try:
                verification = _verifier_aupres_cinetpay(transaction.transaction_id or transaction_id)
            except requests.exceptions.RequestException:
                logger.exception("CinetPay webhook : échec de la revérification du montant")
                return Response({"status": "rejected_verification_failed"}, status=200)

            if verification.get("status") != "ACCEPTED" or verification.get("amount") != transaction.amount:
                logger.warning(
                    "CinetPay webhook : écart détecté à la revérification (statut=%s, "
                    "montant CinetPay=%s, montant attendu=%s) — transaction #%s non créditée",
                    verification.get("status"),
                    verification.get("amount"),
                    transaction.amount,
                    transaction.id,
                )
                return Response({"status": "rejected_verification_failed"}, status=200)

            transaction.status = "success"
            transaction.save()

            metadata = json.loads(data.get("metadata", "{}")) if data.get("metadata") else {}
            type_paiement = metadata.get("type_paiement", "wallet_recharge")
            categorie = CATEGORIE_PAR_TYPE_CINETPAY.get(type_paiement, "recharge")
            type_abonnement = None
            if categorie == "abonnement":
                type_abonnement = "mensuel" if type_paiement == "abonnement_mensuel" else "annuel"

            # P9.7 : même point de finalisation que le flux manuel — split
            # 80/20 ou 30/70, déblocage département/olympiade, activation
            # abonnement, tout identique quel que soit le fournisseur.
            CinetPayProvider().finaliser(
                user_apprenant=transaction.user,
                categorie=categorie,
                montant=transaction.amount,
                moyen="cinetpay",
                transaction_id=transaction.transaction_id,
                reference=transaction.reference,
                objet_id=metadata.get("olympiade_id") or metadata.get("departement_id"),
                type_abonnement=type_abonnement,
            )

        elif status_ in ["-1", "FAILED", "failed", "CANCELLED"]:
            transaction.status = "failed"
            transaction.save()

        return Response({"status": "ok"})


@extend_schema_view(
    get=extend_schema(
        summary="Vérifier le statut d'une transaction CinetPay",
        description=(
            "Retourne le statut actuel (`pending`, `success`, `failed`) d'une "
            "transaction CinetPay identifiée par sa référence, appartenant à "
            "l'utilisateur connecté. Tente en plus un rafraîchissement optionnel "
            "auprès de l'API CinetPay (best-effort, non bloquant) ; la source de "
            "vérité reste le statut déjà mis à jour en base par le webhook.\n\n"
            "Réponse 200 : `{reference, status, amount, created_at}`."
        ),
        tags=["paiement"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class VerifierPaiementCinetPayView(APIView):
    """
    GET /api/paiements/cinetpay/verifier/<reference>/
    Vérifie le statut d'une transaction
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        transaction = get_object_or_404(CinetPayTransaction, reference=reference, user=request.user)

        # Rafraîchissement optionnel auprès de CinetPay (même helper que le
        # webhook, voir _verifier_aupres_cinetpay) — best-effort, non
        # bloquant : le statut déjà en base (mis à jour par le webhook,
        # seul point de crédit réel) reste la source de vérité en cas
        # d'échec ici. Cette vue ne finalise JAMAIS un paiement elle-même.
        try:
            _verifier_aupres_cinetpay(transaction.transaction_id or reference)
        except requests.exceptions.RequestException:
            logger.exception("CinetPay : échec de la vérification optionnelle du statut")

        return Response(
            {
                "reference": transaction.reference,
                "status": transaction.status,
                "amount": transaction.amount,
                "created_at": transaction.created_at.isoformat(),
            }
        )


@extend_schema_view(
    get=extend_schema(
        summary="Historique des paiements de l'utilisateur",
        description=(
            "Retourne la liste paginée (plus récent d'abord) de tous les "
            "paiements effectués par l'utilisateur connecté, tous moyens "
            "confondus (CinetPay, wallet, Google Play). Chaque élément contient "
            "`reference, type_paiement, montant, moyen, statut, date`."
        ),
        tags=["paiement"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class HistoriquePaiementsView(PaginatedListMixin, APIView):
    """GET /api/paiements/historique/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        paiements = Paiement.objects.filter(utilisateur=request.user).order_by("-date")

        page = self.paginate_queryset(paiements)
        data = [
            {
                "reference": p.reference,
                "type_paiement": p.get_type_paiement_display(),
                "montant": p.montant,
                "moyen": p.get_moyen_display(),
                "statut": p.statut,
                "date": p.date,
            }
            for p in page
        ]

        return self.get_paginated_response(data)


@extend_schema_view(
    get=extend_schema(
        summary="Statut de l'abonnement premium (par département)",
        description=(
            "Retourne le statut de l'abonnement premium de l'utilisateur connecté "
            "POUR LE DÉPARTEMENT du cours `cours_id` fourni (rectification : "
            "l'abonnement n'est plus global, il est propre à chaque département) : "
            "`actif, type_abonnement, debut, fin, jours_restants, departement_id, "
            "prix_mensuel, prix_annuel, disponible`. `disponible=False` si "
            "l'administrateur du département n'a fixé aucun prix réel "
            "(`prix_mensuel`/`prix_annuel` tous deux à 0) — aucun montant inventé, "
            "pas d'abonnement possible tant que ce n'est pas le cas."
        ),
        tags=["paiement"],
        parameters=[
            OpenApiParameter("cours_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)
        ],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class StatutAbonnementView(APIView):
    """
    GET /api/abonnement/statut/?cours_id=<id>
    Retourne le statut de l'abonnement premium de l'apprenant DANS le
    département du cours donné.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cours_id = request.query_params.get("cours_id")
        if not cours_id:
            return Response({"detail": "cours_id est obligatoire."}, status=400)
        cours = get_object_or_404(Cours, pk=cours_id)
        departement = cours.departement

        reponse = {
            "departement_id": departement.id,
            "prix_mensuel": departement.prix_mensuel,
            "prix_annuel": departement.prix_annuel,
            "disponible": bool(departement.prix_mensuel or departement.prix_annuel),
        }

        try:
            abo = AbonnementPremium.objects.get(utilisateur=request.user, departement=departement)
            reponse.update(
                {
                    "actif": abo.est_actif,
                    "type_abonnement": abo.type_abonnement,
                    "debut": abo.debut,
                    "fin": abo.fin,
                    "jours_restants": max(0, (abo.fin - timezone.now()).days),
                }
            )
        except AbonnementPremium.DoesNotExist:
            reponse.update(
                {"actif": False, "type_abonnement": None, "debut": None, "fin": None, "jours_restants": 0}
            )
        return Response(reponse)


@extend_schema_view(
    get=extend_schema(
        summary="Solde et transactions récentes du wallet Yéki",
        description=(
            "Retourne le solde courant du wallet Yéki de l'utilisateur connecté "
            "(créé automatiquement s'il n'existe pas encore), les totaux "
            "cumulés de recharge/dépense, ainsi que les 30 dernières "
            "transactions (`id, type, montant, description, cree_le`)."
        ),
        tags=["paiement"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class WalletSoldeView(APIView):
    """GET /api/wallet/solde/ — solde et historique des transactions"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = YekiWallet.get_or_create_wallet(request.user)
        transactions = wallet.transactions.all()[:30]
        return Response(
            {
                "solde": wallet.solde,
                "total_recharge": wallet.total_recharge,
                "total_depense": wallet.total_depense,
                "transactions": [
                    {
                        "id": t.id,
                        "type": t.type_transaction,
                        "montant": t.montant,
                        "description": t.description,
                        "cree_le": t.cree_le.isoformat(),
                    }
                    for t in transactions
                ],
            }
        )


@extend_schema_view(
    post=extend_schema(
        summary="Recharger le wallet Yéki",
        description=(
            "Recharge le wallet Yéki de l'utilisateur connecté via l'un des "
            "moyens suivants (`moyen` dans le corps) :\n"
            "- `google_play` : vérifie un achat in-app via Google Play Developer "
            "API (`purchase_token`, `sku`) — crédite le wallet ou active un "
            "abonnement premium selon le SKU. Anti-rejeu : un `purchase_token` "
            "déjà enregistré est refusé (400).\n"
            "- `mtn_momo` / `orange_om` : recharge Mobile Money (`montant`, "
            "`telephone`) — simulée automatiquement en mode DEBUG, sinon "
            "retourne 503 (intégration SDK non branchée en production).\n\n"
            "Réponse 200 typique : `{statut, solde, montant, detail, ...}`. "
            "Limité par `throttle_scope='paiement'` (anti-spam)."
        ),
        tags=["paiement"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAYMENT_REQUIRED, EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class WalletRechargerView(APIView):
    """
    POST /api/wallet/recharger/
    Body: {
      "moyen": "google_play" | "mtn_momo" | "orange_om",
      "montant": 5000,                        ← pour Mobile Money
      "purchase_token": "...",                 ← pour Google Play
      "sku": "yeki_recharge_5000",             ← pour Google Play
      "telephone": "6XXXXXXXX"                 ← pour Mobile Money
    }
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_scope = "paiement"  # anti-spam de demandes (CDC_BACKEND §2.5) : 10/min

    # SKUs Google Play → montants (FCFA)
    GOOGLE_PLAY_SKUS = {
        "yeki_recharge_1000": 1000,
        "yeki_recharge_2000": 2000,
        "yeki_recharge_5000": 5000,
        "yeki_recharge_10000": 10000,
        "yeki_recharge_20000": 20000,
        "yeki_premium_1500": 1500,  # Abonnement mensuel
        "yeki_premium_13000": 13000,  # Abonnement annuel
    }

    def post(self, request):
        moyen = request.data.get("moyen", "").strip()

        if moyen == "google_play":
            return self._google_play(request)
        elif moyen in ("mtn_momo", "orange_om"):
            return self._mobile_money(request, moyen)
        else:
            return Response(
                {"detail": "moyen invalide. Valeurs: google_play, mtn_momo, orange_om"}, status=400
            )

    def _google_play(self, request):
        """Vérification d'un achat Google Play et crédit du wallet."""
        purchase_token = request.data.get("purchase_token", "").strip()
        sku = request.data.get("sku", "").strip()
        package_name = "com.yeki.app"

        if not purchase_token or not sku:
            return Response({"detail": "purchase_token et sku requis."}, status=400)

        if sku not in self.GOOGLE_PLAY_SKUS:
            return Response({"detail": f"SKU inconnu: {sku}"}, status=400)

        montant = self.GOOGLE_PLAY_SKUS[sku]

        # ── Vérification Google Play Developer API ──────────────
        # Pas de try/except ici : `_verifier_google_play_purchase` ne lève
        # que si GOOGLE_SERVICE_ACCOUNT_JSON est mal configuré côté serveur
        # (ValueError) — une vraie erreur serveur qui doit remonter à
        # EXCEPTION_HANDLER en SERVER_ERROR, pas être reformatée ici.
        valide, message = self._verifier_google_play_purchase(package_name, sku, purchase_token)

        if not valide:
            raise PaymentRequiredError(f"Achat Google Play invalide : {message}")

        # Vérifier que ce token n'a pas déjà été utilisé (anti-replay)
        if WalletTransaction.objects.filter(reference_paiement=purchase_token).exists():
            return Response({"detail": "Cet achat a déjà été enregistré."}, status=400)

        wallet = YekiWallet.get_or_create_wallet(request.user)

        # SKU abonnement Premium → activer l'abonnement
        if "premium" in sku:
            # Rectification : l'abonnement est désormais PAR DÉPARTEMENT —
            # ce SKU Google Play (catalogue à prix fixe, distinct du flux
            # principal manuel/CinetPay qui lit déjà les prix réels du
            # département) exige donc un département cible explicite.
            departement_id = request.data.get("departement_id")
            if not departement_id:
                return Response(
                    {"detail": "departement_id est obligatoire pour un abonnement premium."},
                    status=400,
                )
            departement = get_object_or_404(Departement, pk=departement_id)

            type_abo = "mensuel" if "1500" in sku else "annuel"
            paiement = Paiement.objects.create(
                utilisateur=request.user,
                type_paiement=f"abonnement_{type_abo}",
                moyen="google_play",
                montant=montant,
                statut="succes",
                transaction_id=purchase_token,
            )
            jours = 30 if type_abo == "mensuel" else 365
            try:
                abo = AbonnementPremium.objects.get(utilisateur=request.user, departement=departement)
                abo.renouveler(type_abo)
                abo.paiement = paiement
                abo.save()
            except AbonnementPremium.DoesNotExist:
                AbonnementPremium.objects.create(
                    utilisateur=request.user,
                    departement=departement,
                    type_abonnement=type_abo,
                    actif=True,
                    fin=timezone.now() + timedelta(days=jours),
                    paiement=paiement,
                )
            return Response(
                {
                    "statut": "succes",
                    "detail": f"Abonnement {type_abo} activé pour {departement.nom}.",
                    "montant": montant,
                }
            )

        # SKU recharge → créditer le wallet
        wallet.crediter(
            montant=montant,
            description=f"Recharge Google Play ({sku})",
            reference=purchase_token,
        )

        return Response(
            {
                "statut": "succes",
                "solde": wallet.solde,
                "montant": montant,
                "detail": f"Wallet rechargé de {montant} FCFA.",
                "sku": sku,
            }
        )

    def _verifier_google_play_purchase(self, package_name: str, sku: str, purchase_token: str):
        """
        Vérifie un achat via Google Play Developer API.
        Nécessite : GOOGLE_SERVICE_ACCOUNT_JSON dans les settings.
        """
        service_account_json = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", None)

        # En mode DEBUG sans credentials → simuler succès
        if settings.DEBUG and not service_account_json:
            return True, "Mode DEBUG — achat simulé"

        if not service_account_json:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON non configuré")

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds_dict = (
                json.loads(service_account_json)
                if isinstance(service_account_json, str)
                else service_account_json
            )
            creds = service_account.Credentials.from_service_account_info(
                creds_dict, scopes=["https://www.googleapis.com/auth/androidpublisher"]
            )
            service = build("androidpublisher", "v3", credentials=creds)

            # Pour un produit consommable (recharge)
            result = (
                service.purchases()
                .products()
                .get(
                    packageName=package_name,
                    productId=sku,
                    token=purchase_token,
                )
                .execute()
            )

            # purchaseState: 0 = acheté, 1 = annulé
            if result.get("purchaseState") == 0:
                return True, "Achat valide"
            else:
                return False, f"État achat: {result.get('purchaseState')}"
        except Exception as e:
            # Volontairement large : le SDK Google API peut lever de
            # nombreux types d'exceptions (HttpError, erreurs d'auth...) ;
            # le contrat de cette fonction est de renvoyer un tuple, pas de
            # laisser remonter une exception brute à l'appelant.
            logger.exception("Google Play : échec de vérification d'achat")
            return False, str(e)

    def _mobile_money(self, request, moyen):
        """Recharge via MTN MoMo ou Orange Money."""
        montant = request.data.get("montant")
        telephone = request.data.get("telephone", "").strip()

        try:
            montant = int(montant)
            if montant < 500:
                return Response({"detail": "Montant minimum: 500 FCFA"}, status=400)
        except (TypeError, ValueError):
            return Response({"detail": "Montant invalide"}, status=400)

        if not telephone:
            return Response({"detail": "telephone requis"}, status=400)

        # En mode DEBUG → simuler le succès
        if settings.DEBUG:
            wallet = YekiWallet.get_or_create_wallet(request.user)
            ref = f"SIM-{uuid.uuid4().hex[:10].upper()}"
            wallet.crediter(
                montant=montant,
                description=f"Recharge {moyen.upper()} (simulation)",
                reference=ref,
            )
            return Response(
                {
                    "statut": "succes",
                    "solde": wallet.solde,
                    "montant": montant,
                    "reference": ref,
                    "detail": f"Wallet rechargé de {montant} FCFA (simulation DEBUG).",
                }
            )

        # En production → intégrer SDK MTN / Orange
        return Response(
            {
                "detail": "Intégration Mobile Money non configurée. Contactez le support.",
            },
            status=503,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Payer avec le wallet Yéki",
        description=(
            "Débite le wallet Yéki de l'utilisateur connecté pour l'achat d'un "
            "cours, d'une formation, d'une inscription à une olympiade ou d'une "
            "session Yéki IA (`type`, `objet_id`, `montant`). Si le solde est "
            "insuffisant, lève `InsufficientBalanceError` (402) avec le détail "
            "`{solde, requis}`. Enregistre un `Paiement` de traçabilité "
            "(`moyen='wallet'`) en cas de succès.\n\n"
            "Réponse 200 : `{statut, solde, debite, detail}`. Limité par "
            "`throttle_scope='paiement'` (anti-spam)."
        ),
        tags=["paiement"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_INSUFFICIENT_BALANCE, EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class WalletPayerView(APIView):
    """
    POST /api/wallet/payer/
    Body: {
      "type": "cours"|"formation"|"olympiade"|"ia",
      "objet_id": 5,
      "montant": 2000
    }
    Débite le wallet de l'utilisateur.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "paiement"  # anti-spam de demandes (CDC_BACKEND §2.5) : 10/min

    def post(self, request):
        type_achat = request.data.get("type", "").strip()
        objet_id = request.data.get("objet_id")
        montant = request.data.get("montant")

        try:
            montant = int(montant)
            if montant <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"detail": "Montant invalide"}, status=400)

        wallet = YekiWallet.get_or_create_wallet(request.user)

        if not wallet.peut_debiter(montant):
            raise InsufficientBalanceError(
                "Solde insuffisant.",
                fields={"solde": wallet.solde, "requis": montant},
            )

        descriptions = {
            "cours": f"Accès cours #{objet_id}",
            "formation": f"Accès formation #{objet_id}",
            "olympiade": f"Inscription olympiade #{objet_id}",
            "ia": f"Session Yéki IA #{objet_id}",
        }
        description = descriptions.get(type_achat, f"Paiement {type_achat}")
        wallet.debiter(montant=montant, description=description)

        # Enregistrer dans Paiement
        type_map = {
            "cours": "acces_departement",
            "formation": "acces_departement",
            "olympiade": "olympiade",
            "ia": "acces_departement",
        }
        Paiement.objects.create(
            utilisateur=request.user,
            type_paiement=type_map.get(type_achat, "acces_departement"),
            moyen="wallet",
            montant=montant,
            statut="succes",
            transaction_id=f"WALLET-{uuid.uuid4().hex[:10].upper()}",
        )

        return Response(
            {
                "statut": "succes",
                "solde": wallet.solde,
                "debite": montant,
                "detail": f"{description} payé avec succès.",
            }
        )


@extend_schema_view(
    post=extend_schema(
        summary="Vérifier un achat Google Play (IAP) et créditer le wallet",
        description=(
            "Vérifie un achat in-app Google Play (`purchase_token`, `sku`) "
            "effectué côté client mobile et crédite le wallet Yéki en "
            "conséquence — délègue entièrement à la logique de "
            "`WalletRechargerView._google_play()`. Peut lever "
            "`PaymentRequiredError` (402) si l'achat n'est pas valide auprès "
            "de l'API Google Play Developer.\n\n"
            "Réponse 200 : `{statut, solde, montant, detail, sku}` (recharge) "
            "ou `{statut, detail, montant}` (abonnement premium)."
        ),
        tags=["paiement"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAYMENT_REQUIRED, *ERREURS_ECRITURE],
    ),
)
class WalletVerifierIAPView(APIView):
    """
    POST /api/wallet/verifier-iap/
    Webhook appelé par le frontend après achat Google Play.
    Body: { "purchase_token": "...", "sku": "yeki_recharge_5000", "platform": "android" }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Déléguer à WalletRechargerView._google_play()
        request.data._mutable = True if hasattr(request.data, "_mutable") else None
        request.data["moyen"] = "google_play"
        view = WalletRechargerView()
        view.request = request
        view.format_kwarg = None
        return view._google_play(request)


@extend_schema_view(
    post=extend_schema(
        summary="Soumettre une demande de paiement manuel",
        description=(
            "L'apprenant a payé hors application (USSD, agence Orange Money/MTN "
            "Mobile Money) et soumet son ID de transaction pour vérification "
            "manuelle par le Service Client (CDC §9.1). Un même "
            "(`operateur`, `id_transaction`) ne peut être soumis qu'une fois — "
            "409 Conflict sinon (empêche la réclamation d'un même dépôt pour "
            "deux achats ou par deux comptes). Statut créé à `en_attente` ; "
            "aucune vue de validation/refus par le Service Client dans cette "
            "tâche (P2.4) — à traiter séparément. Limité par "
            "`throttle_scope='paiement'`."
        ),
        tags=["paiement"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class SoumettrePaiementManuelView(APIView):
    """
    POST /api/paiements/manuel/soumettre/
    Body: {
      "categorie": "abonnement"|"olympiade"|"formation"|"recharge"|"presentiel",
      "departement_id": 5,          (optionnel)
      "objet_id": 12,               (optionnel, ID olympiade/formation)
      "montant": 2000,
      "operateur": "orange_money"|"mtn_momo",
      "id_transaction": "...",      (saisi par l'apprenant)
      "numero_emetteur": "..."      (optionnel)
    }
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "paiement"  # anti-spam de demandes (CDC_BACKEND §2.5) : 10/min

    def post(self, request):
        # P9.7 : garde serveur symétrique à celle de CinetPay ci-dessus.
        if mode_paiement_actif() not in ("manuel", "les_deux"):
            return Response(
                {"detail": "Le paiement manuel n'est pas disponible actuellement."}, status=403
            )

        try:
            profile = request.user.profile
        except Exception:
            return Response({"detail": "Profil introuvable."}, status=404)

        categorie = request.data.get("categorie", "").strip()
        categories_valides = [c for c, _ in DemandePaiementManuelle.CATEGORIES]
        if categorie not in categories_valides:
            return Response(
                {"detail": f"categorie invalide. Valeurs : {categories_valides}"}, status=400
            )

        operateur = request.data.get("operateur", "").strip()
        operateurs_valides = [
            o for o, _ in DemandePaiementManuelle._meta.get_field("operateur").choices
        ]
        if operateur not in operateurs_valides:
            return Response(
                {"detail": f"operateur invalide. Valeurs : {operateurs_valides}"}, status=400
            )

        id_transaction = (request.data.get("id_transaction") or "").strip()
        if not id_transaction:
            return Response({"detail": "id_transaction est obligatoire."}, status=400)

        try:
            montant = int(request.data.get("montant"))
            if montant <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"detail": "montant invalide."}, status=400)

        departement = None
        departement_id = request.data.get("departement_id")
        if departement_id:
            departement = get_object_or_404(Departement, pk=departement_id)
        elif categorie == "abonnement":
            # Rectification : l'abonnement est désormais PAR DÉPARTEMENT —
            # ce champ, optionnel pour les autres catégories, devient
            # obligatoire ici (aucun département à défaut à deviner).
            return Response(
                {"detail": "departement_id est obligatoire pour un abonnement premium."}, status=400
            )

        # P9.2 : optionnel, uniquement pertinent pour categorie="abonnement"
        # (évite de devoir déduire mensuel/annuel du montant à la
        # validation, fragile si les tarifs changent).
        type_abonnement = (request.data.get("type_abonnement") or "").strip()
        if type_abonnement:
            types_valides = [t for t, _ in AbonnementPremium.TYPE_CHOICES]
            if type_abonnement not in types_valides:
                return Response(
                    {"detail": f"type_abonnement invalide. Valeurs : {types_valides}"}, status=400
                )

        try:
            # `transaction.atomic()` : sans ce savepoint dédié, l'IntegrityError
            # de la contrainte unique laisserait la transaction englobante
            # dans un état inutilisable (toute requête suivante lèverait
            # TransactionManagementError) — capturée ici, seule cette
            # écriture est annulée.
            with transaction.atomic():
                demande = DemandePaiementManuelle.objects.create(
                    apprenant=profile,
                    categorie=categorie,
                    departement=departement,
                    objet_id=request.data.get("objet_id"),
                    montant=montant,
                    operateur=operateur,
                    id_transaction=id_transaction,
                    numero_emetteur=(request.data.get("numero_emetteur") or "").strip(),
                    type_abonnement=type_abonnement,
                )
        except IntegrityError:
            # Contrainte unique (operateur, id_transaction) — cet ID de
            # transaction a déjà été soumis, par ce compte ou un autre.
            raise ConflictError(
                "Cet identifiant de transaction a déjà été soumis pour cet opérateur."
            )

        return Response(
            {
                "id": demande.id,
                "statut": demande.statut,
                "categorie": demande.categorie,
                "montant": demande.montant,
                "detail": (
                    "Demande enregistrée. Le Service Client la vérifiera sous "
                    f"{ParametreSysteme.get('delai_validation_paiement_minutes', default=60)} minutes."
                ),
            },
            status=201,
        )


def _demande_manuelle_dict(d):
    """Représentation JSON commune à MesDemandesPaiementManuelView et
    FileAttentePaiementsServiceClientView — factorisée pour ne pas
    dupliquer les mêmes clés deux fois."""
    return {
        "id": d.id,
        "categorie": d.categorie,
        "montant": d.montant,
        "montant_constate": d.montant_constate,
        "operateur": d.operateur,
        "id_transaction": d.id_transaction,
        "numero_emetteur": d.numero_emetteur,
        "statut": d.statut,
        "motif_refus": d.motif_refus,
        "date_creation": d.date_creation,
        "date_traitement": d.date_traitement,
    }


@extend_schema_view(
    get=extend_schema(
        summary="Mes demandes de paiement manuel",
        description=(
            "Retourne la liste paginée des demandes de paiement manuel de "
            "l'apprenant connecté, triées de la plus récente à la plus "
            "ancienne. Filtrable par `statut` (en_attente|validee|refusee)."
        ),
        tags=["paiement"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class MesDemandesPaiementManuelView(PaginatedListMixin, APIView):
    """GET /api/paiements/manuel/mes-demandes/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Exception:
            return Response({"detail": "Profil introuvable."}, status=404)

        qs = DemandePaiementManuelle.objects.filter(apprenant=profile).order_by("-date_creation")
        statut = request.query_params.get("statut")
        if statut:
            qs = qs.filter(statut=statut)

        page = self.paginate_queryset(qs)
        return self.get_paginated_response([_demande_manuelle_dict(d) for d in page])


@extend_schema_view(
    get=extend_schema(
        summary="File d'attente des paiements manuels (Service Client)",
        description=(
            "Retourne, paginées et triées par ordre d'arrivée (FIFO), les "
            "demandes de paiement manuel à traiter. Réservé au Service "
            "Client. Filtrable par `statut` (défaut : `en_attente` ; "
            "`all` pour tout voir)."
        ),
        tags=["paiement"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class FileAttentePaiementsServiceClientView(PaginatedListMixin, APIView):
    """GET /api/service-client/paiements/"""

    permission_classes = [IsServiceClient]

    def get(self, request):
        # Pas d'ordering par défaut sur DemandePaiementManuelle — tri
        # explicite obligatoire pour une vraie file d'attente (FIFO).
        qs = DemandePaiementManuelle.objects.select_related(
            "apprenant__user", "departement"
        ).order_by("date_creation")
        statut = request.query_params.get("statut", "en_attente")
        if statut != "all":
            qs = qs.filter(statut=statut)

        page = self.paginate_queryset(qs)
        data = []
        for d in page:
            item = _demande_manuelle_dict(d)
            item["apprenant"] = d.apprenant.user.username
            data.append(item)
        return self.get_paginated_response(data)


@extend_schema_view(
    post=extend_schema(
        summary="Valider une demande de paiement manuel (Service Client)",
        description=(
            "Valide une demande de paiement manuel : active l'abonnement, "
            "débloque l'olympiade/la formation, ou crédite le portefeuille "
            "selon la catégorie, avec répartition 80/20 (olympiade) ou "
            "30/70 (formation) si applicable — le tout dans une seule "
            "transaction atomique. `montant_constate` (optionnel dans le "
            "corps) est le montant réellement reçu ; s'il diffère du "
            "montant déclaré à la soumission, l'écart est journalisé dans "
            "HistoriqueActivite. Réservé au Service Client, qui ne peut "
            "pas traiter sa propre demande. `select_for_update()` + garde "
            "sur le statut empêchent une double validation concurrente."
        ),
        tags=["paiement"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class ValiderPaiementManuelView(APIView):
    """POST /api/service-client/paiements/<pk>/valider/"""

    permission_classes = [IsServiceClient]
    throttle_scope = "paiement"

    def post(self, request, pk):
        profile = request.user.profile

        montant_constate_raw = request.data.get("montant_constate")
        montant_constate = None
        if montant_constate_raw is not None:
            try:
                montant_constate = int(montant_constate_raw)
                if montant_constate <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return Response({"detail": "montant_constate invalide."}, status=400)

        with transaction.atomic():
            demande = get_object_or_404(
                DemandePaiementManuelle.objects.select_for_update(), pk=pk
            )

            # ── Garde anti double-validation concurrente ──────────────
            if demande.statut != "en_attente":
                raise ConflictError("Cette demande a déjà été traitée.")

            # ── Le Service Client ne valide pas ses propres demandes ──
            if demande.apprenant_id == profile.id:
                return Response(
                    {"detail": "Vous ne pouvez pas traiter votre propre demande."}, status=403
                )

            # « Montant réellement constaté » : c'est l'argent réellement
            # encaissé qui doit être crédité/réparti, pas la déclaration a
            # priori de l'apprenant à la soumission.
            montant_retenu = montant_constate if montant_constate is not None else demande.montant
            ecart = montant_retenu - demande.montant
            user_apprenant = demande.apprenant.user
            moyen = "orange_om" if demande.operateur == "orange_money" else "mtn_momo"

            # P9.7 : le branchement par catégorie (crédit wallet, split
            # 80/20 ou 30/70, déblocage département/olympiade, activation
            # abonnement) est désormais partagé avec le fournisseur CinetPay
            # via `finaliser_paiement` — voir apps/paiement/providers.py.
            ManuelProvider().finaliser(
                user_apprenant=user_apprenant,
                categorie=demande.categorie,
                montant=montant_retenu,
                moyen=moyen,
                transaction_id=demande.id_transaction,
                objet_id=demande.objet_id,
                departement=demande.departement,
                type_abonnement=demande.type_abonnement,
                demande_manuelle=demande,
            )

            demande.statut = "validee"
            demande.montant_constate = montant_retenu
            demande.traite_par = profile
            demande.date_traitement = timezone.now()
            demande.save(
                update_fields=["statut", "montant_constate", "traite_par", "date_traitement"]
            )

            if ecart:
                enregistrer_activite(
                    user=request.user,
                    action="ecart_montant_paiement",
                    description=f"Écart constaté sur la demande de paiement #{demande.id}",
                    data={"declare": demande.montant, "constate": montant_retenu, "ecart": ecart},
                    objet_id=demande.id,
                    objet_type="DemandePaiementManuelle",
                )

            enregistrer_activite(
                user=request.user,
                action="payment_validated",
                description=f"Paiement manuel #{demande.id} validé ({demande.categorie})",
                data={"categorie": demande.categorie, "montant": montant_retenu},
                objet_id=demande.id,
                objet_type="DemandePaiementManuelle",
            )
            # Notification à l'apprenant : signal post_save sur
            # DemandePaiementManuelle (apps/paiement/signals.py, P10.3) —
            # plus d'appel manuel ici.

        return Response(
            {
                "id": demande.id,
                "statut": demande.statut,
                "montant_constate": demande.montant_constate,
                "ecart": ecart,
            },
            status=200,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Refuser une demande de paiement manuel (Service Client)",
        description=(
            "Refuse une demande de paiement manuel. `motif_refus` est "
            "OBLIGATOIRE (400 sinon). Aucun rollback financier nécessaire : "
            "rien n'est débité/crédité avant validation. Mêmes gardes que "
            "`valider/` (select_for_update + statut + Service Client ≠ "
            "apprenant)."
        ),
        tags=["paiement"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class RefuserPaiementManuelView(APIView):
    """POST /api/service-client/paiements/<pk>/refuser/"""

    permission_classes = [IsServiceClient]
    throttle_scope = "paiement"

    def post(self, request, pk):
        profile = request.user.profile

        motif = (request.data.get("motif_refus") or "").strip()
        if not motif:
            return Response({"detail": "motif_refus est obligatoire."}, status=400)

        with transaction.atomic():
            demande = get_object_or_404(
                DemandePaiementManuelle.objects.select_for_update(), pk=pk
            )
            if demande.statut != "en_attente":
                raise ConflictError("Cette demande a déjà été traitée.")
            if demande.apprenant_id == profile.id:
                return Response(
                    {"detail": "Vous ne pouvez pas traiter votre propre demande."}, status=403
                )

            demande.statut = "refusee"
            demande.motif_refus = motif
            demande.traite_par = profile
            demande.date_traitement = timezone.now()
            demande.save(
                update_fields=["statut", "motif_refus", "traite_par", "date_traitement"]
            )

            enregistrer_activite(
                user=request.user,
                action="payment_rejected",
                description=f"Paiement manuel #{demande.id} refusé : {motif}",
                data={"motif": motif},
                objet_id=demande.id,
                objet_type="DemandePaiementManuelle",
            )
            # Notification à l'apprenant : signal post_save sur
            # DemandePaiementManuelle (apps/paiement/signals.py, P10.3) —
            # plus d'appel manuel ici.

        return Response({"id": demande.id, "statut": demande.statut}, status=200)


@extend_schema_view(
    post=extend_schema(
        summary="Demander un retrait",
        description=(
            "Demande de retrait du portefeuille Yéki vers Mobile Money (CDC §5.6), "
            "réservée aux cadres (`user_type='enseignant_cadre'`). Le montant doit "
            "être ≥ `ParametreSysteme['retrait_minimum']` et ≤ au solde disponible. "
            "Les frais opérateur (`FraisOperateur`) sont calculés et le solde est "
            "**immédiatement débité** (gelé) à la création — validée ou refusée "
            "(libérant le gel) par le Service Client via "
            "`/api/service-client/retraits/<pk>/valider|refuser/` (P9.4). "
            "Limité par `throttle_scope='paiement'`."
        ),
        tags=["paiement"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_INSUFFICIENT_BALANCE, EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class DemanderRetraitView(APIView):
    """
    POST /api/retraits/demander/
    Body: { "montant_brut": 5000, "operateur": "orange_money"|"mtn_momo", "numero_destination": "..." }
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "paiement"  # anti-spam de demandes (CDC_BACKEND §2.5) : 10/min

    def post(self, request):
        try:
            profile = request.user.profile
        except Exception:
            return Response({"detail": "Profil introuvable."}, status=404)
        if profile.user_type != "enseignant_cadre":
            return Response({"detail": "Le retrait est réservé aux cadres."}, status=403)

        operateur = request.data.get("operateur", "").strip()
        operateurs_valides = [o for o, _ in DemandeRetrait._meta.get_field("operateur").choices]
        if operateur not in operateurs_valides:
            return Response(
                {"detail": f"operateur invalide. Valeurs : {operateurs_valides}"}, status=400
            )

        numero_destination = (request.data.get("numero_destination") or "").strip()
        if not numero_destination:
            return Response({"detail": "numero_destination est obligatoire."}, status=400)

        retrait_min = int(ParametreSysteme.get("retrait_minimum", default=1000))
        try:
            montant_brut = int(request.data.get("montant_brut"))
        except (TypeError, ValueError):
            return Response({"detail": "montant_brut invalide."}, status=400)

        if montant_brut < retrait_min:
            return Response(
                {"detail": f"Le montant minimum de retrait est {retrait_min} FCFA."}, status=400
            )

        wallet = YekiWallet.get_or_create_wallet(request.user)
        if not wallet.peut_debiter(montant_brut):
            raise InsufficientBalanceError(
                "Solde insuffisant pour ce retrait.",
                fields={"solde": wallet.solde, "requis": montant_brut},
            )

        frais, montant_net = calculer_frais(operateur, montant_brut)

        # Gel du solde : débit immédiat à la création (CDC §5.6 — « le
        # solde est gelé à la création de la demande »). Libéré (remboursé)
        # ou définitivement débité selon la décision du Service Client —
        # vue de décision hors périmètre de cette tâche.
        wallet.debiter(montant_brut, description="Demande de retrait (solde gelé)")

        demande = DemandeRetrait.objects.create(
            beneficiaire=profile,
            montant_brut=montant_brut,
            frais_operateur=frais,
            montant_net=montant_net,
            operateur=operateur,
            numero_destination=numero_destination,
        )

        return Response(
            {
                "id": demande.id,
                "statut": demande.statut,
                "montant_brut": montant_brut,
                "frais_operateur": frais,
                "montant_net": montant_net,
                "solde_restant": wallet.solde,
                "detail": "Demande de retrait créée. Solde gelé en attente de traitement par le Service Client.",
            },
            status=201,
        )


def _demande_retrait_dict(d):
    """Représentation JSON commune à `MesDemandesRetraitView` et
    `FileAttenteRetraitsServiceClientView` — même convention que
    `_demande_manuelle_dict` (P9.2)."""
    return {
        "id": d.id,
        "montant_brut": d.montant_brut,
        "frais_operateur": d.frais_operateur,
        "montant_net": d.montant_net,
        "operateur": d.operateur,
        "numero_destination": d.numero_destination,
        "statut": d.statut,
        "motif_refus": d.motif_refus,
        "date_creation": d.date_creation,
        "date_traitement": d.date_traitement,
    }


@extend_schema_view(
    get=extend_schema(
        summary="Mes demandes de retrait (cadre)",
        description=(
            "Retourne la liste paginée des demandes de retrait du cadre "
            "connecté, triées de la plus récente à la plus ancienne. "
            "Filtrable par `statut` (en_attente|validee|refusee)."
        ),
        tags=["paiement"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class MesDemandesRetraitView(PaginatedListMixin, APIView):
    """GET /api/retraits/mes-demandes/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Exception:
            return Response({"detail": "Profil introuvable."}, status=404)

        qs = DemandeRetrait.objects.filter(beneficiaire=profile).order_by("-date_creation")
        statut = request.query_params.get("statut")
        if statut:
            qs = qs.filter(statut=statut)

        page = self.paginate_queryset(qs)
        return self.get_paginated_response([_demande_retrait_dict(d) for d in page])


@extend_schema_view(
    get=extend_schema(
        summary="File d'attente des retraits (Service Client)",
        description=(
            "Retourne, paginées et triées par ordre d'arrivée (FIFO), les "
            "demandes de retrait à traiter. Réservé au Service Client. "
            "Filtrable par `statut` (défaut : `en_attente` ; `all` pour "
            "tout voir). Chaque ligne inclut le solde ACTUEL du bénéficiaire "
            "(`solde_beneficiaire`), pour que le Service Client sache si le "
            "cadre a d'autres fonds avant de traiter la demande."
        ),
        tags=["paiement"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class FileAttenteRetraitsServiceClientView(PaginatedListMixin, APIView):
    """GET /api/service-client/retraits/"""

    permission_classes = [IsServiceClient]

    def get(self, request):
        # Pas d'ordering par défaut sur DemandeRetrait — tri explicite
        # obligatoire pour une vraie file d'attente (FIFO).
        qs = DemandeRetrait.objects.select_related("beneficiaire__user").order_by("date_creation")
        statut = request.query_params.get("statut", "en_attente")
        if statut != "all":
            qs = qs.filter(statut=statut)

        page = self.paginate_queryset(qs)
        data = []
        for d in page:
            item = _demande_retrait_dict(d)
            item["beneficiaire"] = d.beneficiaire.user.username
            item["solde_beneficiaire"] = YekiWallet.get_or_create_wallet(d.beneficiaire.user).solde
            data.append(item)
        return self.get_paginated_response(data)


@extend_schema_view(
    post=extend_schema(
        summary="Valider un retrait (Service Client)",
        description=(
            "Valide une demande de retrait : le solde a déjà été débité "
            "(gelé) à la création de la demande, donc valider NE TOUCHE "
            "PAS le wallet — seul le statut passe à `validee` (l'argent a "
            "réellement été envoyé au bénéficiaire, en dehors de l'app, "
            "via Mobile Money). Réservé au Service Client, qui ne peut pas "
            "traiter sa propre demande. `select_for_update()` + garde sur "
            "le statut empêchent une double validation concurrente."
        ),
        tags=["paiement"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class ValiderRetraitView(APIView):
    """POST /api/service-client/retraits/<pk>/valider/"""

    permission_classes = [IsServiceClient]
    throttle_scope = "paiement"

    def post(self, request, pk):
        profile = request.user.profile

        with transaction.atomic():
            demande = get_object_or_404(DemandeRetrait.objects.select_for_update(), pk=pk)

            if demande.statut != "en_attente":
                raise ConflictError("Cette demande a déjà été traitée.")
            if demande.beneficiaire_id == profile.id:
                return Response(
                    {"detail": "Vous ne pouvez pas traiter votre propre demande."}, status=403
                )

            # Aucune opération wallet ici : le solde a déjà été débité
            # (gelé) à la création par DemanderRetraitView — valider un
            # retrait ne fait que confirmer que l'argent a été envoyé, ne
            # JAMAIS re-débiter ni créditer à cette étape.
            demande.statut = "validee"
            demande.traite_par = profile
            demande.date_traitement = timezone.now()
            demande.save(update_fields=["statut", "traite_par", "date_traitement"])

            enregistrer_activite(
                user=request.user,
                action="retrait_validated",
                description=f"Retrait #{demande.id} validé",
                data={"montant_brut": demande.montant_brut, "montant_net": demande.montant_net},
                objet_id=demande.id,
                objet_type="DemandeRetrait",
            )
            # Notification au bénéficiaire : signal post_save sur
            # DemandeRetrait (apps/paiement/signals.py, P10.3) — plus
            # d'appel manuel ici.

        return Response({"id": demande.id, "statut": demande.statut}, status=200)


@extend_schema_view(
    post=extend_schema(
        summary="Refuser un retrait (Service Client)",
        description=(
            "Refuse une demande de retrait. `motif_refus` est OBLIGATOIRE "
            "(400 sinon). CONTRAIREMENT au paiement manuel, un rollback "
            "financier EST nécessaire ici : le solde (`montant_brut`) avait "
            "été gelé (débité) à la création, refuser DOIT donc le créditer "
            "de nouveau pour libérer le gel. Mêmes gardes que `valider/` "
            "(select_for_update + statut + Service Client ≠ bénéficiaire)."
        ),
        tags=["paiement"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class RefuserRetraitView(APIView):
    """POST /api/service-client/retraits/<pk>/refuser/"""

    permission_classes = [IsServiceClient]
    throttle_scope = "paiement"

    def post(self, request, pk):
        profile = request.user.profile

        motif = (request.data.get("motif_refus") or "").strip()
        if not motif:
            return Response({"detail": "motif_refus est obligatoire."}, status=400)

        with transaction.atomic():
            demande = get_object_or_404(DemandeRetrait.objects.select_for_update(), pk=pk)

            if demande.statut != "en_attente":
                raise ConflictError("Cette demande a déjà été traitée.")
            if demande.beneficiaire_id == profile.id:
                return Response(
                    {"detail": "Vous ne pouvez pas traiter votre propre demande."}, status=403
                )

            # Libère le gel : le montant BRUT (pas net) avait été débité à
            # la création — c'est ce montant exact qu'il faut recréditer.
            wallet = YekiWallet.get_or_create_wallet(demande.beneficiaire.user)
            wallet.crediter(
                demande.montant_brut,
                description=f"Retrait #{demande.id} refusé — solde libéré",
                reference=f"RETRAIT-REFUS-{demande.id}",
            )

            demande.statut = "refusee"
            demande.motif_refus = motif
            demande.traite_par = profile
            demande.date_traitement = timezone.now()
            demande.save(
                update_fields=["statut", "motif_refus", "traite_par", "date_traitement"]
            )

            enregistrer_activite(
                user=request.user,
                action="retrait_refused",
                description=f"Retrait #{demande.id} refusé : {motif}",
                data={"motif": motif, "montant_libere": demande.montant_brut},
                objet_id=demande.id,
                objet_type="DemandeRetrait",
            )
            # Notification au bénéficiaire : signal post_save sur
            # DemandeRetrait (apps/paiement/signals.py, P10.3) — plus
            # d'appel manuel ici.

        return Response({"id": demande.id, "statut": demande.statut}, status=200)


def _decideur_dict(p):
    """« Décideur » d'un `Paiement` : `traite_par` de la demande manuelle
    d'origine si elle existe (P9.2), sinon un libellé générique selon le
    moyen — un paiement CinetPay/wallet n'a jamais de décideur humain."""
    if p.demande_manuelle_id and p.demande_manuelle.traite_par_id:
        u = p.demande_manuelle.traite_par.user
        return u.get_full_name() or u.username
    if p.moyen == "cinetpay":
        return "Automatique (CinetPay)"
    if p.moyen == "wallet":
        return "Portefeuille (immédiat)"
    return None


def _transaction_dict(p):
    categorie = CATEGORIE_PAR_TYPE_PAIEMENT.get(p.type_paiement, p.type_paiement)
    # Part tiers+bénéficiaire n'a de sens que pour formation/olympiade
    # (les seules catégories avec un split cadre) — 0 pour les autres, PAS
    # (montant - commission_yeki) qui vaudrait le montant entier par erreur
    # puisque commission_yeki reste à 0 pour recharge/abonnement/presentiel.
    part_tiers = (p.montant - p.commission_yeki) if categorie in ("formation", "olympiade") else 0

    beneficiaire = None
    if categorie == "formation" and p.departement_id and p.departement.cadre_id:
        u = p.departement.cadre.user
        beneficiaire = u.get_full_name() or u.username
    elif categorie == "olympiade" and p.olympiade_liee_id and p.olympiade_liee.organisateur_id:
        u = p.olympiade_liee.organisateur.user
        beneficiaire = u.get_full_name() or u.username

    return {
        "id": p.id,
        "date": p.date,
        "apprenant": p.utilisateur.get_full_name() or p.utilisateur.username,
        "categorie": categorie,
        "departement": p.departement.nom if p.departement_id else None,
        "montant_brut": p.montant,
        "part_yeki": p.commission_yeki,
        "part_tiers_beneficiaire": part_tiers,
        "beneficiaire": beneficiaire,
        "operateur": p.moyen,
        "statut": p.statut,
        "decideur": _decideur_dict(p),
    }


@extend_schema_view(
    get=extend_schema(
        summary="Transactions (admin général)",
        description=(
            "Retourne, paginées et triées par date décroissante, TOUTES les "
            "transactions (`Paiement`), tous fournisseurs confondus (manuel, "
            "CinetPay, portefeuille). Filtrable par `departement` (id), "
            "`categorie` (abonnement|olympiade|formation|recharge|presentiel), "
            "`du`/`au` (dates AAAA-MM-JJ) et `statut`. Par ligne : date, "
            "apprenant, categorie, departement, montant_brut, part_yeki, "
            "part_tiers_beneficiaire, beneficiaire, operateur, statut, "
            "decideur. Réservé à l'admin général."
        ),
        tags=["paiement"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class AdminTransactionsView(PaginatedListMixin, APIView):
    """GET /api/admin/transactions/"""

    permission_classes = [IsAdminGeneral]

    def get(self, request):
        qs = Paiement.objects.select_related(
            "utilisateur",
            "departement__cadre__user",
            "olympiade_liee__organisateur__user",
            "demande_manuelle__traite_par__user",
        ).order_by("-date")

        departement_id = request.query_params.get("departement")
        if departement_id:
            qs = qs.filter(departement_id=departement_id)

        categorie = request.query_params.get("categorie")
        if categorie:
            qs = qs.filter(type_paiement__in=TYPES_PAR_CATEGORIE.get(categorie, []))

        du = request.query_params.get("du")
        if du:
            qs = qs.filter(date__date__gte=du)

        au = request.query_params.get("au")
        if au:
            qs = qs.filter(date__date__lte=au)

        statut = request.query_params.get("statut")
        if statut:
            qs = qs.filter(statut=statut)

        page = self.paginate_queryset(qs)
        return self.get_paginated_response([_transaction_dict(p) for p in page])


def _delai_moyen_minutes(demandes):
    """Délai moyen (minutes) entre `date_creation` et `date_traitement`
    sur un itérable de tuples `(date_creation, date_traitement)` — `None`
    si aucune demande traitée (pas de division par zéro silencieuse)."""
    demandes = list(demandes)
    if not demandes:
        return None
    total_secondes = sum((traite - cree).total_seconds() for cree, traite in demandes)
    return round(total_secondes / len(demandes) / 60, 1)


@extend_schema_view(
    get=extend_schema(
        summary="Tableau de bord financier (admin général)",
        description=(
            "Agrégats financiers pour l'admin général : total encaissé "
            "(EXCLUT les paiements par portefeuille — un mouvement interne "
            "déjà compté à la recharge d'origine, le resommer doublerait "
            "l'argent), ventilation par catégorie et par département (même "
            "exclusion), solde du compte IA (`YekiCompteIA`, existant), "
            "solde général Yéki calculé (somme de `commission_yeki` — aucun "
            "ledger dédié n'existe), TOTAL DÛ AUX CADRES (somme des soldes "
            "portefeuille des `enseignant_cadre` — un PASSIF, jamais fondu "
            "dans le total encaissé), demandes en attente et délai moyen de "
            "traitement (paiements manuels + retraits). Réservé à l'admin "
            "général."
        ),
        tags=["paiement"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class AdminDashboardFinancierView(APIView):
    """GET /api/admin/dashboard-financier/"""

    permission_classes = [IsAdminGeneral]

    def get(self, request):
        # Mouvement interne (argent déjà compté à la recharge d'origine) —
        # exclu du "total encaissé" pour ne pas compter deux fois le même
        # argent (point comptable explicitement signalé par le ticket).
        qs_encaisse = Paiement.objects.filter(statut="succes").exclude(moyen="wallet")

        total_encaisse = qs_encaisse.aggregate(total=Sum("montant"))["total"] or 0

        ventilation_categorie = {}
        for type_paiement, categorie in CATEGORIE_PAR_TYPE_PAIEMENT.items():
            montant = (
                qs_encaisse.filter(type_paiement=type_paiement).aggregate(total=Sum("montant"))["total"]
                or 0
            )
            ventilation_categorie[categorie] = ventilation_categorie.get(categorie, 0) + montant

        ventilation_departement = list(
            qs_encaisse.exclude(departement__isnull=True)
            .values("departement_id", "departement__nom")
            .annotate(total=Sum("montant"))
            .order_by("-total")
        )

        solde_compte_ia = (
            YekiCompteIA.objects.filter(pk=1).values_list("total_commissions", flat=True).first() or 0
        )
        # Aucun ledger "Yéki général" n'existe (la part Yéki n'est jamais
        # réellement virée nulle part) — calculé à la volée, PAS un solde
        # de compte réel. Documenté comme une limite connue plutôt que
        # fabriqué silencieusement.
        solde_general_yeki_calcule = (
            Paiement.objects.filter(statut="succes").aggregate(total=Sum("commission_yeki"))["total"] or 0
        )

        # DETTE de Yéki envers les cadres — jamais un revenu. À afficher
        # SÉPARÉMENT de total_encaisse côté frontend, jamais additionné.
        total_du_aux_cadres = (
            YekiWallet.objects.filter(utilisateur__profile__user_type="enseignant_cadre").aggregate(
                total=Sum("solde")
            )["total"]
            or 0
        )

        demandes_paiement_traitees = DemandePaiementManuelle.objects.exclude(
            date_traitement__isnull=True
        ).values_list("date_creation", "date_traitement")
        demandes_retrait_traitees = DemandeRetrait.objects.exclude(
            date_traitement__isnull=True
        ).values_list("date_creation", "date_traitement")

        return Response(
            {
                "total_encaisse": total_encaisse,
                "ventilation_categorie": ventilation_categorie,
                "ventilation_departement": ventilation_departement,
                "solde_compte_ia": solde_compte_ia,
                "solde_general_yeki_calcule": solde_general_yeki_calcule,
                "total_du_aux_cadres": total_du_aux_cadres,
                "demandes_en_attente": {
                    "paiement": DemandePaiementManuelle.objects.filter(statut="en_attente").count(),
                    "retrait": DemandeRetrait.objects.filter(statut="en_attente").count(),
                },
                "delai_moyen_minutes": {
                    "paiement": _delai_moyen_minutes(demandes_paiement_traitees),
                    "retrait": _delai_moyen_minutes(demandes_retrait_traitees),
                },
            }
        )


def _taux_refus(qs_traitees):
    """Pourcentage de demandes refusées parmi les demandes TRAITÉES
    (validées + refusées, `en_attente` exclu) — `None` si aucune demande
    traitée (pas de division par zéro silencieuse)."""
    total = qs_traitees.count()
    if total == 0:
        return None
    refusees = qs_traitees.filter(statut="refusee").count()
    return round(refusees / total * 100, 1)


@extend_schema_view(
    get=extend_schema(
        summary="Statistiques Service Client",
        description=(
            "Agrégats pour l'onglet Statistiques du dashboard Service Client "
            "(P9.5) : demandes en attente, délai moyen de traitement et taux "
            "de refus, paiements manuels et retraits confondus. Distinct du "
            "tableau de bord financier admin général (P9.6, réservé à "
            "`IsAdminGeneral`) — celui-ci est accessible au Service Client."
        ),
        tags=["paiement"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class ServiceClientStatistiquesView(APIView):
    """GET /api/service-client/statistiques/"""

    permission_classes = [IsServiceClient]

    def get(self, request):
        paiements_traites = DemandePaiementManuelle.objects.exclude(date_traitement__isnull=True)
        retraits_traites = DemandeRetrait.objects.exclude(date_traitement__isnull=True)

        return Response(
            {
                "demandes_en_attente": {
                    "paiement": DemandePaiementManuelle.objects.filter(statut="en_attente").count(),
                    "retrait": DemandeRetrait.objects.filter(statut="en_attente").count(),
                },
                "delai_moyen_minutes": {
                    "paiement": _delai_moyen_minutes(
                        paiements_traites.values_list("date_creation", "date_traitement")
                    ),
                    "retrait": _delai_moyen_minutes(
                        retraits_traites.values_list("date_creation", "date_traitement")
                    ),
                },
                "taux_refus_pourcent": {
                    "paiement": _taux_refus(paiements_traites),
                    "retrait": _taux_refus(retraits_traites),
                },
            }
        )
