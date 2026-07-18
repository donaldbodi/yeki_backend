"""
Settings pour l'exécution des tests (pytest-django, CI).

Base SQLite en mémoire (rapide, pas de dépendance à un service Postgres en
CI) et envoi d'e-mails désactivé (les tests ne doivent jamais envoyer de
vrais e-mails). Throttling identique à la production : les tests de
throttling (429 sur /api/auth/login/) ont besoin des vrais taux CDC.
"""

from .base import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
