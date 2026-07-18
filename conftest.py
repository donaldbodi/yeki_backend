"""
Fixtures pytest partagées par toute la suite (P1.6, voir docs/API_FOUNDATIONS.md).

Placé à la racine du projet (à côté de manage.py) car pytest ne propage un
conftest.py qu'à son propre sous-arbre : pour être visible par
apps/accounts/tests/, apps/formation/tests/, etc. simultanément, il doit
vivre au-dessus de tous ces répertoires.
"""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.accounts.models import Profile
from apps.evaluation.models import Devoir, Exercice
from apps.formation.models import Cours, Departement, Parcours


@pytest.fixture(autouse=True)
def _cache_vide():
    """
    Le throttling DRF (AnonRateThrottle/ScopedRateThrottle) stocke ses
    compteurs dans le cache Django, pas dans la base de données : il ne
    serait donc PAS réinitialisé par le rollback transactionnel habituel
    entre tests. Sans ce nettoyage, un test de throttling pourrait déclencher
    un 429 à cause d'appels faits par un test précédent.
    """
    cache.clear()
    yield
    cache.clear()


# ── Données métier minimales (parcours → département → cours → …) ──────────


@pytest.fixture
def parcours(db):
    return Parcours.objects.create(nom="Cursus Test", type_parcours="cursus")


@pytest.fixture
def departement(db, parcours):
    return Departement.objects.create(nom="Département Test", parcours=parcours)


@pytest.fixture
def cours(db, departement):
    return Cours.objects.create(titre="Cours Test", niveau="Terminale", departement=departement)


@pytest.fixture
def exercice(db, cours):
    return Exercice.objects.create(
        cours=cours,
        titre="Exercice Test",
        enonce="Énoncé de test.",
        etoiles=1,
    )


@pytest.fixture
def devoir(db, cours):
    return Devoir.objects.create(
        titre="Devoir Test",
        enonce="Énoncé du devoir de test.",
        date_limite=timezone.now() + timedelta(days=7),
        cours_lie=cours,
        est_publie=True,
    )


# ── Utilisateurs, un par rôle (Profile.USER_TYPES) ──────────────────────────


def _creer_utilisateur(username, user_type, departement=None):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@yeki.test",
        password="Test1234!",
    )
    Profile.objects.create(
        user=user,
        user_type=user_type,
        departement=departement,
        niveau="Terminale",
        is_active=True,
    )
    return user


@pytest.fixture
def user_apprenant(db, departement):
    return _creer_utilisateur("apprenant_test", "apprenant", departement=departement)


@pytest.fixture
def user_enseignant(db):
    return _creer_utilisateur("enseignant_test", "enseignant")


@pytest.fixture
def user_enseignant_principal(db):
    return _creer_utilisateur("enseignant_principal_test", "enseignant_principal")


@pytest.fixture
def user_enseignant_cadre(db):
    return _creer_utilisateur("enseignant_cadre_test", "enseignant_cadre")


@pytest.fixture
def user_enseignant_admin(db):
    return _creer_utilisateur("enseignant_admin_test", "enseignant_admin")


@pytest.fixture
def user_admin(db):
    return _creer_utilisateur("admin_test", "admin")


@pytest.fixture
def user_service_client(db):
    return _creer_utilisateur("service_client_test", "service_client")


# ── Clients API (token DRF, un par rôle) ────────────────────────────────────


@pytest.fixture
def api_client():
    return APIClient()


def _client_authentifie(user):
    token, _ = Token.objects.get_or_create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client


@pytest.fixture
def client_apprenant(user_apprenant):
    return _client_authentifie(user_apprenant)


@pytest.fixture
def client_enseignant(user_enseignant):
    return _client_authentifie(user_enseignant)


@pytest.fixture
def client_enseignant_principal(user_enseignant_principal):
    return _client_authentifie(user_enseignant_principal)


@pytest.fixture
def client_enseignant_cadre(user_enseignant_cadre):
    return _client_authentifie(user_enseignant_cadre)


@pytest.fixture
def client_enseignant_admin(user_enseignant_admin):
    return _client_authentifie(user_enseignant_admin)


@pytest.fixture
def client_admin(user_admin):
    return _client_authentifie(user_admin)


@pytest.fixture
def client_service_client(user_service_client):
    return _client_authentifie(user_service_client)
