import json
import logging
import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta

import requests

from rest_framework.parsers import JSONParser
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

from apps.core.exceptions import ConflictError, PaymentRequiredError, InsufficientBalanceError
from apps.core.models import ParametreSysteme
from apps.core.pagination import PaginatedListMixin
from apps.evaluation.models import InscriptionOlympiade
from apps.formation.models import Departement
from apps.paiement.models import (
    Paiement,
    AbonnementPremium,
    YekiWallet,
    WalletTransaction,
    CinetPayTransaction,
    DemandePaiementManuelle,
    DemandeRetrait,
    calculer_frais,
)

from drf_spectacular.utils import extend_schema, extend_schema_view
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
        data = request.data

        # Vérifier la signature (recommandé)
        # signature = request.headers.get('X-CinetPay-Signature')

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

        # Vérifier le statut
        if status_ in ["00", "ACCEPTED", "SUCCESS", "success"]:
            transaction.status = "success"
            transaction.save()

            # ── Créditer le wallet ou activer l'abonnement ──────
            metadata = json.loads(data.get("metadata", "{}")) if data.get("metadata") else {}
            type_paiement = metadata.get("type_paiement", "wallet_recharge")

            if type_paiement == "wallet_recharge":
                wallet = YekiWallet.get_or_create_wallet(transaction.user)
                wallet.crediter(
                    montant=transaction.amount,
                    description=f"Recharge CinetPay - {transaction.reference}",
                    reference=transaction.reference,
                )
            elif type_paiement in ["abonnement_mensuel", "abonnement_annuel"]:
                jours = 30 if type_paiement == "abonnement_mensuel" else 365
                try:
                    abo = transaction.user.abonnement
                    abo.renouveler("mensuel" if jours == 30 else "annuel")
                except AbonnementPremium.DoesNotExist:
                    AbonnementPremium.objects.create(
                        utilisateur=transaction.user,
                        type_abonnement="mensuel" if jours == 30 else "annuel",
                        actif=True,
                        fin=timezone.now() + timedelta(days=jours),
                    )
            elif type_paiement == "olympiade":
                olympiade_id = metadata.get("olympiade_id")
                if olympiade_id:
                    InscriptionOlympiade.objects.get_or_create(
                        olympiade_id=olympiade_id,
                        apprenant=transaction.user,
                        defaults={"statut": "confirme"},
                    )

            # Créer l'enregistrement de paiement
            Paiement.objects.create(
                utilisateur=transaction.user,
                type_paiement=type_paiement,
                moyen="cinetpay",
                montant=transaction.amount,
                statut="succes",
                transaction_id=transaction.transaction_id,
                reference=transaction.reference,
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

        # Optionnel: Vérifier auprès de CinetPay
        try:
            site_id = settings.CINETPAY_SITE_ID
            api_key = settings.CINETPAY_API_KEY

            response = requests.post(
                "https://api-checkout.cinetpay.com/v2/payment/check",
                json={
                    "site_id": site_id,
                    "apikey": api_key,
                    "transaction_id": transaction.transaction_id or reference,
                },
                timeout=15,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("code") == 200:
                    cinetpay_status = data.get("data", {}).get("status")
                    if cinetpay_status == "ACCEPTED" and transaction.status != "success":
                        # Mettre à jour (normalement déjà fait par webhook)
                        pass
        except requests.exceptions.RequestException:
            # Volontairement large : cette vérification est un simple
            # rafraîchissement optionnel, le statut déjà en base (mis à jour
            # par le webhook) reste la source de vérité en cas d'échec ici.
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
        summary="Statut de l'abonnement premium",
        description=(
            "Retourne le statut de l'abonnement premium de l'utilisateur connecté : "
            "`actif, type_abonnement, debut, fin, jours_restants`. Si aucun "
            "abonnement n'existe, retourne un statut inactif par défaut "
            "(`actif=False`, autres champs à `None`/`0`) plutôt qu'une erreur 404."
        ),
        tags=["paiement"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class StatutAbonnementView(APIView):
    """
    GET /api/abonnement/statut/
    Retourne le statut de l'abonnement premium de l'apprenant.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            abo = request.user.abonnement
            return Response(
                {
                    "actif": abo.est_actif,
                    "type_abonnement": abo.type_abonnement,
                    "debut": abo.debut,
                    "fin": abo.fin,
                    "jours_restants": max(0, (abo.fin - timezone.now()).days),
                }
            )
        except AbonnementPremium.DoesNotExist:
            return Response(
                {
                    "actif": False,
                    "type_abonnement": None,
                    "debut": None,
                    "fin": None,
                    "jours_restants": 0,
                }
            )


# Prix IA
TARIF_IA_FCFA_PAR_1K_TOKENS = 2  # 2 FCFA par 1000 tokens
COMMISSION_YEKI_IA_FCFA = 5  # 5 FCFA commission fixe par requête
TARIF_IA_MIN = 10  # minimum 10 FCFA par requête


def _calculer_cout_ia(tokens: int) -> int:
    """Calcule le coût d'une requête IA en FCFA."""
    cout_tokens = max(1, round(tokens * TARIF_IA_FCFA_PAR_1K_TOKENS / 1000))
    return max(TARIF_IA_MIN, cout_tokens + COMMISSION_YEKI_IA_FCFA)


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
                abo = request.user.abonnement
                abo.renouveler(type_abo)
                abo.paiement = paiement
                abo.save()
            except AbonnementPremium.DoesNotExist:
                AbonnementPremium.objects.create(
                    utilisateur=request.user,
                    type_abonnement=type_abo,
                    actif=True,
                    fin=timezone.now() + timedelta(days=jours),
                    paiement=paiement,
                )
            return Response(
                {
                    "statut": "succes",
                    "detail": f"Abonnement {type_abo} activé.",
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


@extend_schema_view(
    post=extend_schema(
        summary="Demander un retrait",
        description=(
            "Demande de retrait du portefeuille Yéki vers Mobile Money (CDC §5.6). "
            "Le montant doit être ≥ `ParametreSysteme['retrait_minimum']` et ≤ au "
            "solde disponible. Les frais opérateur (`FraisOperateur`) sont calculés "
            "et le solde est **immédiatement débité** (gelé) à la création — "
            "aucune vue de décision (validation/refus/envoi par le Service Client) "
            "n'existe encore dans cette tâche (P2.4) pour le libérer ou le "
            "finaliser, à traiter séparément. Limité par `throttle_scope='paiement'`."
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
