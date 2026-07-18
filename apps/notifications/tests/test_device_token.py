"""
Test P2.4 : DeviceToken — contrainte d'unicité sur `token` (CDC §8.2).
"""

import pytest
from django.db import IntegrityError

from apps.notifications.models import DeviceToken


@pytest.mark.django_db
def test_token_unique(user_apprenant, user_enseignant):
    DeviceToken.objects.create(user=user_apprenant, token="ABC123", plateforme="android")

    with pytest.raises(IntegrityError):
        DeviceToken.objects.create(user=user_enseignant, token="ABC123", plateforme="ios")


@pytest.mark.django_db
def test_creation_normale(user_apprenant):
    token = DeviceToken.objects.create(user=user_apprenant, token="XYZ789", plateforme="android")
    assert token.actif is True
    assert token.derniere_utilisation is not None
