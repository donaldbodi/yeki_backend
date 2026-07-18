"""Settings de production — PostgreSQL, HTTPS strict, HSTS, cookies sécurisés."""

from .base import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = ["yeki.pythonanywhere.com"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST"),
        "PORT": env("DB_PORT", default="5432"),
    }
}

# ── HTTPS strict / HSTS / cookies sécurisés ─────────────────────────────────
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# 1 semaine pour démarrer, à augmenter progressivement une fois validé en
# production (pratique recommandée Django : un HSTS mal réglé bloque l'accès
# HTTP pendant toute sa durée, mieux vaut monter en confiance graduellement).
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
