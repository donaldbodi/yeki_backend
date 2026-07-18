"""
Tests du format d'erreur unique (P1.6) : {"error": {code, message, fields,
request_id}} sur tous les codes définis dans apps/core/exceptions.py — voir
docs/API_FOUNDATIONS.md.

Les codes sont testés directement contre `custom_exception_handler` (plutôt
que via une vue précise) : c'est un contrat transversal indépendant de
n'importe quelle vue particulière, et ça évite de coupler ce test à
l'implémentation interne d'une vue donnée.
"""

import pytest
from django.urls import reverse
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.core.exceptions import (
    ConflictError,
    InsufficientBalanceError,
    PaymentRequiredError,
    custom_exception_handler,
)

factory = APIRequestFactory()


def _appeler_handler(exc):
    request = factory.get("/api/quelconque/")
    return custom_exception_handler(exc, {"view": None, "request": request})


@pytest.mark.parametrize(
    "exc,code_attendu,status_attendu",
    [
        (
            drf_exceptions.ValidationError({"champ": ["Ce champ est obligatoire."]}),
            "VALIDATION_ERROR",
            400,
        ),
        (drf_exceptions.NotFound(), "NOT_FOUND", 404),
        (drf_exceptions.PermissionDenied(), "PERMISSION_DENIED", 403),
        (drf_exceptions.NotAuthenticated(), "NOT_AUTHENTICATED", 401),
        (ConflictError("Déjà inscrit."), "CONFLICT", 409),
        (PaymentRequiredError("Paiement requis."), "PAYMENT_REQUIRED", 402),
        (InsufficientBalanceError("Solde insuffisant."), "INSUFFICIENT_BALANCE", 402),
    ],
)
def test_enveloppe_erreur_par_code(exc, code_attendu, status_attendu):
    response = _appeler_handler(exc)

    assert response.status_code == status_attendu
    error = response.data["error"]
    assert error["code"] == code_attendu
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["fields"], dict)
    assert isinstance(error["request_id"], str) and error["request_id"]


def test_enveloppe_erreur_validation_peuple_fields():
    exc = drf_exceptions.ValidationError({"enonce": ["Ce champ est obligatoire."]})
    response = _appeler_handler(exc)
    assert "enonce" in response.data["error"]["fields"]


def test_enveloppe_erreur_serveur_pour_exception_non_reconnue():
    response = _appeler_handler(ValueError("boum"))
    assert response.status_code == 500
    assert response.data["error"]["code"] == "SERVER_ERROR"


@pytest.mark.django_db
def test_not_authenticated_bout_en_bout_sur_vue_reelle():
    """Un appel sans token à une vue IsAuthenticated renvoie bien l'enveloppe."""
    from rest_framework.test import APIClient

    client = APIClient()
    response = client.get(reverse("liste-parcours"))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.data["error"]["code"] == "NOT_AUTHENTICATED"
