"""Settings de production — PostgreSQL, HTTPS strict, HSTS, cookies sécurisés."""

from .base import *  # noqa: F401,F403

DEBUG = False

# Liste extensible par variable d'environnement (`env.list`, django-environ) —
# permet d'ajouter le domaine du nouvel hébergement VPS+Coolify sans nouveau
# déploiement de code, juste une variable d'env côté Coolify. Les 2 valeurs
# historiques restent le défaut (compatibilité PythonAnywhere le temps de la
# bascule).
ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS", default=["yeki.pythonanywhere.com", "http://localhost:64940"]
)

# PythonAnywhere termine le HTTPS sur SON propre reverse proxy et transmet
# ensuite la requête à ce process WSGI en HTTP interne (`X-Forwarded-Proto`
# porte le protocole d'origine) — sans cette ligne, Django ne sait pas s'y
# fier et `request.is_secure()`/`request.scheme` retombent sur l'interne
# (`http`). Conséquence concrète, root cause probable des médias forum/PDF
# de leçon qui ne s'affichent jamais côté client (Firebase Hosting, servi en
# HTTPS) : `request.build_absolute_uri()` (utilisé par tous les champs
# `*_url` des serializers forum/leçon) génère des URLs `http://...` — le
# navigateur les bloque comme contenu mixte (HTTPS→HTTP), un blocage
# similaire au CORS déjà corrigé mais avec une cause différente et non
# résolue par ce correctif-là. Fix standard documenté par PythonAnywhere
# lui-même pour les apps Django derrière leur proxy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ── Channels (WebSocket) — migration hébergement VPS+Coolify ────────────────
# `config/asgi.py` construit déjà le `ProtocolTypeRouter` (http+websocket) —
# ces 2 réglages sont ce qui manquait pour qu'il soit RÉELLEMENT chargé (un
# serveur ASGI, Daphne, au lieu du WSGI PythonAnywhere) et pour que le
# `channel_layer` utilisé par `yeki/consumers.py` (`ForumConsumer`,
# `group_send`/`group_add`) ait un backend partagé entre process — le layer
# mémoire par défaut de Channels ne fonctionne qu'en single-process, jamais
# fiable dès qu'il y a plusieurs workers/replicas.
ASGI_APPLICATION = "config.asgi.application"
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env("REDIS_URL")],
        },
    }
}

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
