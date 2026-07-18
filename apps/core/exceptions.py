import logging
import uuid

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404

from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


# ── Exceptions métier sans équivalent natif DRF ─────────────────────────────


class YekiAPIException(drf_exceptions.APIException):
    """
    Base commune : permet d'attacher un `fields` structuré (ex :
    `prix_participation`, `olympiade_id`) en plus du message, pour les cas où
    le frontend a besoin de données précises (déclencher un écran de
    paiement, etc.) et pas seulement d'un message d'erreur.
    """

    def __init__(self, detail=None, fields=None, code=None):
        super().__init__(detail=detail, code=code)
        self.fields = fields or {}


class ConflictError(YekiAPIException):
    """
    409 — l'action demandée entre en conflit avec un état déjà existant
    (ex : déjà inscrit à cette olympiade, demande d'accès déjà en attente).
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Cette action a déjà été effectuée."
    default_code = "conflict"


class PaymentRequiredError(YekiAPIException):
    """402 — l'action nécessite un paiement préalable non encore effectué."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_detail = "Un paiement est requis pour effectuer cette action."
    default_code = "payment_required"


class InsufficientBalanceError(YekiAPIException):
    """402 — le portefeuille Yéki de l'utilisateur n'a pas le solde requis."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_detail = "Solde insuffisant. Rechargez votre portefeuille Yéki."
    default_code = "insufficient_balance"


_DEFAULT_MESSAGES = {
    "NOT_FOUND": "Ressource introuvable.",
    "PERMISSION_DENIED": "Vous n'avez pas la permission d'effectuer cette action.",
    "NOT_AUTHENTICATED": "Authentification requise.",
    "THROTTLED": "Trop de requêtes. Réessayez plus tard.",
    "SERVER_ERROR": "Une erreur inattendue est survenue.",
}


def _make_request_id():
    return uuid.uuid4().hex[:8]


def _code_for(exc):
    if isinstance(exc, ConflictError):
        return "CONFLICT"
    if isinstance(exc, InsufficientBalanceError):
        return "INSUFFICIENT_BALANCE"
    if isinstance(exc, PaymentRequiredError):
        return "PAYMENT_REQUIRED"
    if isinstance(exc, drf_exceptions.Throttled):
        return "THROTTLED"
    if isinstance(exc, (drf_exceptions.NotAuthenticated, drf_exceptions.AuthenticationFailed)):
        return "NOT_AUTHENTICATED"
    if isinstance(exc, drf_exceptions.PermissionDenied):
        return "PERMISSION_DENIED"
    if isinstance(exc, drf_exceptions.NotFound):
        return "NOT_FOUND"
    if isinstance(exc, drf_exceptions.ValidationError):
        return "VALIDATION_ERROR"
    return "SERVER_ERROR"


def _fields_for(exc):
    """
    Extrait un dict {champ: [messages]} exploitable par YkForm (frontend)
    pour afficher l'erreur SOUS LE BON CHAMP plutôt qu'un SnackBar générique.

    `exc.detail` est un dict {champ: [ErrorDetail, ...]} quand l'exception
    vient d'un serializer (`serializer.is_valid(raise_exception=True)`) ;
    sinon (detail = chaîne ou liste simple) il n'y a pas de champ précis.

    Priorité au `fields` structuré explicite (`YekiAPIException.fields`,
    ex : `PaymentRequiredError(..., fields={"prix_participation": 100})`).
    """
    custom_fields = getattr(exc, "fields", None)
    if custom_fields:
        return custom_fields

    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        return {
            key: [str(d) for d in (val if isinstance(val, list) else [val])]
            for key, val in detail.items()
        }
    return {}


def _message_for(exc, code):
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        # Pas de message global naturel pour une erreur par champ : le détail
        # exploitable est `fields`, pas `message`.
        return "Le formulaire contient des erreurs."
    if isinstance(detail, list) and detail:
        return str(detail[0])
    if detail is not None:
        return str(detail)
    return _DEFAULT_MESSAGES.get(code, "Une erreur est survenue.")


def custom_exception_handler(exc, context):
    """
    EXCEPTION_HANDLER DRF unique pour toute l'API YÉKI (voir
    docs/API_FOUNDATIONS.md). Produit TOUJOURS :

        {"error": {"code", "message", "fields", "request_id"}}

    Toute exception non reconnue par DRF (bug inattendu, appel externe en
    échec, etc.) est journalisée ici avec traceback et request_id, puis
    remontée comme SERVER_ERROR — source unique de vérité plutôt qu'un
    `raise ServerError(...)` dupliqué à chaque site d'appel.
    """
    request_id = _make_request_id()

    # Http404 / PermissionDenied (Django, pas DRF) doivent être converties en
    # équivalents DRF pour que exception_handler() natif les reconnaisse
    # (comportement standard documenté par DRF).
    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)

    if response is None:
        view = context.get("view")
        view_name = view.__class__.__name__ if view else "?"
        logger.exception("[%s] Exception non gérée dans %s", request_id, view_name)

        code = "SERVER_ERROR"
        fields = {}
        message = _message_for(exc, code)
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    else:
        code = _code_for(exc)
        fields = _fields_for(exc)
        message = _message_for(exc, code)
        status_code = response.status_code

        if isinstance(exc, drf_exceptions.Throttled) and exc.wait:
            fields = {**fields, "retry_after": exc.wait}
            message = f"Trop de requêtes. Réessayez dans {int(exc.wait)} secondes."

    return Response(
        {
            "error": {
                "code": code,
                "message": message,
                "fields": fields,
                "request_id": request_id,
            }
        },
        status=status_code,
    )
