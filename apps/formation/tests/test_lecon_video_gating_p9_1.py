"""
Tests P9.1 : LeconSerializer/LeconLightSerializer — GRATUIT = PDF
seulement, la vidéo est réservée aux abonnés Premium.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.formation.models import Lecon
from apps.formation.serializers import LeconLightSerializer, LeconSerializer


@pytest.fixture
def lecon_avec_video(db, cours):
    return Lecon.objects.create(
        titre="Leçon Test",
        description="…",
        cours=cours,
        fichier_pdf=SimpleUploadedFile("cours.pdf", b"contenu pdf"),
        video=SimpleUploadedFile("cours.mp4", b"contenu video"),
    )


def _drf_request(user):
    # `Request.user` a son propre getter/setter (authentification paresseuse
    # via les authenticators configurés) — l'affecter sur la requête Django
    # brute AVANT de l'envelopper dans `Request(...)` n'a aucun effet ; il
    # faut l'affecter sur l'objet `Request` lui-même.
    drf_request = Request(APIRequestFactory().get("/"))
    drf_request.user = user
    return drf_request


@pytest.mark.django_db
def test_lecon_serializer_masque_la_video_en_gratuit(lecon_avec_video, user_apprenant):
    data = LeconSerializer(lecon_avec_video, context={"request": _drf_request(user_apprenant)}).data
    assert data["video"] is None
    assert data["fichier_pdf"] is not None


@pytest.mark.django_db
def test_lecon_serializer_expose_la_video_en_premium(lecon_avec_video, user_apprenant_premium):
    data = LeconSerializer(
        lecon_avec_video, context={"request": _drf_request(user_apprenant_premium)}
    ).data
    assert data["video"] is not None
    assert data["fichier_pdf"] is not None


@pytest.mark.django_db
def test_lecon_light_serializer_masque_la_video_en_gratuit(lecon_avec_video, user_apprenant):
    data = LeconLightSerializer(
        lecon_avec_video, context={"request": _drf_request(user_apprenant)}
    ).data
    assert data["video"] is None
    assert data["fichier_pdf"] is not None


@pytest.mark.django_db
def test_lecon_light_serializer_expose_la_video_en_premium(lecon_avec_video, user_apprenant_premium):
    data = LeconLightSerializer(
        lecon_avec_video, context={"request": _drf_request(user_apprenant_premium)}
    ).data
    assert data["video"] is not None
