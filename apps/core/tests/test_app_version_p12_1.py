"""
Tests P12.1 : GET /api/app/version/ (AppVersionCheckView) — vérification
de version obligatoire + informations pour mise à jour sécurisée
(canal de diffusion, checksum SHA-256). Aucun test n'existait avant ce
ticket pour AppVersion/latest-version/check-update — couverture créée
de zéro, plus quelques tests de non-régression sur les 2 vues sœurs
existantes (ajout du filtre `canal`).
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import AppVersion


@pytest.mark.django_db
def test_app_version_a_jour():
    AppVersion.objects.create(
        platform="android", canal="stable", version_code=5, version_name="v1.0.5",
        download_url="https://cdn.yeki.cm/app.apk", min_version_code=3, is_active=True,
    )
    client = APIClient()
    response = client.get(reverse("app-version-check"), {"plateforme": "android", "build": 5})
    assert response.status_code == 200
    assert response.data["obligatoire"] is False
    assert response.data["mise_a_jour_disponible"] is False


@pytest.mark.django_db
def test_app_version_mise_a_jour_disponible_non_obligatoire():
    AppVersion.objects.create(
        platform="android", canal="stable", version_code=5, version_name="v1.0.5",
        download_url="https://cdn.yeki.cm/app.apk", min_version_code=3, is_active=True,
    )
    client = APIClient()
    response = client.get(reverse("app-version-check"), {"plateforme": "android", "build": 4})
    assert response.status_code == 200
    assert response.data["obligatoire"] is False
    assert response.data["mise_a_jour_disponible"] is True


@pytest.mark.django_db
def test_app_version_mise_a_jour_obligatoire():
    AppVersion.objects.create(
        platform="android", canal="stable", version_code=5, version_name="v1.0.5",
        download_url="https://cdn.yeki.cm/app.apk", checksum_sha256="a" * 64,
        min_version_code=3, is_active=True,
    )
    client = APIClient()
    response = client.get(reverse("app-version-check"), {"plateforme": "android", "build": 2})
    assert response.status_code == 200
    assert response.data["obligatoire"] is True
    assert response.data["checksum_sha256"] == "a" * 64
    assert response.data["download_url"] == "https://cdn.yeki.cm/app.apk"


@pytest.mark.django_db
def test_app_version_filtre_par_canal_beta_non_proposee_a_un_client_stable():
    AppVersion.objects.create(
        platform="android", canal="stable", version_code=5, version_name="v1.0.5",
        download_url="https://cdn.yeki.cm/stable.apk", min_version_code=1, is_active=True,
    )
    AppVersion.objects.create(
        platform="android", canal="beta", version_code=9, version_name="v1.1.0-beta",
        download_url="https://cdn.yeki.cm/beta.apk", min_version_code=1, is_active=True,
    )
    client = APIClient()
    # Sans paramètre canal — défaut 'stable', ne doit voir que la version 5.
    response = client.get(reverse("app-version-check"), {"plateforme": "android", "build": 5})
    assert response.data["mise_a_jour_disponible"] is False

    response_beta = client.get(
        reverse("app-version-check"), {"plateforme": "android", "canal": "beta", "build": 5}
    )
    assert response_beta.data["version_code"] == 9
    assert response_beta.data["mise_a_jour_disponible"] is True


@pytest.mark.django_db
def test_app_version_aucune_version_configuree_reponse_gracieuse():
    client = APIClient()
    response = client.get(reverse("app-version-check"), {"plateforme": "ios", "build": 1})
    assert response.status_code == 200
    assert response.data["obligatoire"] is False
    assert response.data["mise_a_jour_disponible"] is False


@pytest.mark.django_db
def test_app_version_build_manquant_400():
    client = APIClient()
    response = client.get(reverse("app-version-check"), {"plateforme": "android"})
    assert response.status_code == 400


@pytest.mark.django_db
def test_app_version_serializer_expose_canal_et_checksum():
    from apps.core.serializers import AppVersionSerializer

    version = AppVersion.objects.create(
        platform="android", canal="beta", version_code=1, version_name="v1.0.0",
        download_url="https://cdn.yeki.cm/app.apk", checksum_sha256="b" * 64,
    )
    data = AppVersionSerializer(version).data
    assert data["canal"] == "beta"
    assert data["checksum_sha256"] == "b" * 64


@pytest.mark.django_db
def test_latest_version_sans_parametre_canal_reste_stable_par_defaut():
    """Non-régression : l'ajout du filtre canal ne casse pas les appels existants."""
    AppVersion.objects.create(
        platform="android", canal="stable", version_code=3, version_name="v1.0.3",
        download_url="https://cdn.yeki.cm/app.apk", is_active=True,
    )
    AppVersion.objects.create(
        platform="android", canal="beta", version_code=7, version_name="v1.1.0-beta",
        download_url="https://cdn.yeki.cm/beta.apk", is_active=True,
    )
    client = APIClient()
    response = client.get(reverse("latest-version"), {"platform": "android"})
    assert response.status_code == 200
    assert response.data["version_code"] == 3


@pytest.mark.django_db
def test_check_update_sans_parametre_canal_reste_stable_par_defaut():
    AppVersion.objects.create(
        platform="android", canal="stable", version_code=3, version_name="v1.0.3",
        download_url="https://cdn.yeki.cm/app.apk", is_active=True,
    )
    AppVersion.objects.create(
        platform="android", canal="beta", version_code=7, version_name="v1.1.0-beta",
        download_url="https://cdn.yeki.cm/beta.apk", is_active=True,
    )
    client = APIClient()
    response = client.get(
        reverse("check-update"), {"platform": "android", "current_version": 3}
    )
    assert response.status_code == 200
    assert response.data["update_available"] is False
