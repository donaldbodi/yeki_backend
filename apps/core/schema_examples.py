"""
Exemples OpenAPI partagés pour les annotations @extend_schema (P1.6).

Centralise les exemples de réponses communes (enveloppe d'erreur, pagination)
pour éviter de dupliquer les mêmes exemples littéraux dans ~160 vues — voir
docs/API_FOUNDATIONS.md pour la description complète de ces deux contrats.
"""

from drf_spectacular.utils import OpenApiExample, OpenApiParameter
from drf_spectacular.types import OpenApiTypes


def erreur_exemple(code, message, fields=None, status_code=400):
    """
    Construit un OpenApiExample pour un code d'erreur donné, au format de
    l'enveloppe unique produite par `apps.core.exceptions.custom_exception_handler`.
    """
    return OpenApiExample(
        name=f"Erreur {code}",
        summary=f"Réponse {status_code} — {code}",
        value={
            "error": {
                "code": code,
                "message": message,
                "fields": fields or {},
                "request_id": "a3f1c9e2",
            }
        },
        response_only=True,
        status_codes=[str(status_code)],
    )


EXEMPLE_VALIDATION_ERROR = erreur_exemple(
    "VALIDATION_ERROR",
    "Le formulaire contient des erreurs.",
    fields={"champ": ["Ce champ est obligatoire."]},
    status_code=400,
)

EXEMPLE_NOT_FOUND = erreur_exemple(
    "NOT_FOUND",
    "Ressource introuvable.",
    status_code=404,
)

EXEMPLE_PERMISSION_DENIED = erreur_exemple(
    "PERMISSION_DENIED",
    "Vous n'avez pas la permission d'effectuer cette action.",
    status_code=403,
)

EXEMPLE_NOT_AUTHENTICATED = erreur_exemple(
    "NOT_AUTHENTICATED",
    "Authentification requise.",
    status_code=401,
)

EXEMPLE_THROTTLED = erreur_exemple(
    "THROTTLED",
    "Trop de requêtes. Réessayez plus tard.",
    fields={"retry_after": 42},
    status_code=429,
)

EXEMPLE_CONFLICT = erreur_exemple(
    "CONFLICT",
    "Cette action a déjà été effectuée.",
    status_code=409,
)

EXEMPLE_PAYMENT_REQUIRED = erreur_exemple(
    "PAYMENT_REQUIRED",
    "Un paiement est requis pour effectuer cette action.",
    status_code=402,
)

EXEMPLE_INSUFFICIENT_BALANCE = erreur_exemple(
    "INSUFFICIENT_BALANCE",
    "Solde insuffisant. Rechargez votre portefeuille Yéki.",
    status_code=402,
)

# Sous-ensemble courant à passer à `examples=` pour une vue de lecture/liste
# standard authentifiée (401/404 génériques).
ERREURS_COURANTES = [
    EXEMPLE_NOT_AUTHENTICATED,
    EXEMPLE_PERMISSION_DENIED,
    EXEMPLE_NOT_FOUND,
]

# Sous-ensemble courant pour une vue d'écriture (POST/PUT/PATCH) avec
# validation de formulaire.
ERREURS_ECRITURE = [
    EXEMPLE_VALIDATION_ERROR,
    EXEMPLE_NOT_AUTHENTICATED,
    EXEMPLE_PERMISSION_DENIED,
]

# Paramètres de requête communs à toute vue paginée (YekiPageNumberPagination) :
# à passer à `parameters=[*PARAMS_PAGINATION, ...]` sur les vues de liste.
PARAMS_PAGINATION = [
    OpenApiParameter(
        "page",
        OpenApiTypes.INT,
        OpenApiParameter.QUERY,
        required=False,
        description="Numéro de page (défaut : 1).",
    ),
    OpenApiParameter(
        "page_size",
        OpenApiTypes.INT,
        OpenApiParameter.QUERY,
        required=False,
        description="Taille de page (défaut : 20, maximum : 100).",
    ),
]

EXEMPLE_PAGINATION = OpenApiExample(
    name="Réponse paginée",
    summary="Enveloppe de pagination standard (YekiPageNumberPagination)",
    value={
        "count": 57,
        "next": "http://api.yeki.cm/api/cours/?page=2",
        "previous": None,
        "results": ["... voir le schéma de l'élément de la liste ..."],
    },
    response_only=True,
    status_codes=["200"],
)
