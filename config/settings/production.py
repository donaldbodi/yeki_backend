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

# ── Stockage des médias — Firebase Storage ───────────────────────────────
# Railway ne fournit aucun volume persistant (confirmé : aucun
# `railway.json`/volume configuré) — chaque redéploiement recrée un
# conteneur avec un système de fichiers vierge, ce qui efface tout média
# uploadé (`FileSystemStorage`, le défaut hérité de `base.py`). Firebase
# Storage est un bucket Google Cloud Storage standard : `django-storages`
# sait déjà s'y connecter nativement (backend `gcloud`), et le même compte
# de service déjà utilisé pour FCM (`FIREBASE_CREDENTIALS_JSON`, voir
# apps/notifications/fcm.py) fonctionne tel quel — aucun nouveau
# compte/projet Firebase à créer.
#
# Uniquement défini ICI (pas dans `base.py`) : `config/settings/test.py`
# importe seulement `base.py` et reste donc, volontairement, toujours sur
# `FileSystemStorage` — aucun risque qu'un test touche le vrai stockage
# cloud, aucun credential requis pour faire tourner la suite de tests.
_firebase_credentials_json = env("FIREBASE_CREDENTIALS_JSON", default="")
if _firebase_credentials_json:
    import json as _json

    from google.oauth2 import service_account as _service_account

    _firebase_credentials_dict = _json.loads(_firebase_credentials_json)
    GS_CREDENTIALS = _service_account.Credentials.from_service_account_info(
        _firebase_credentials_dict
    )
    GS_PROJECT_ID = _firebase_credentials_dict.get("project_id")
    # Convention historique des buckets Firebase Storage — surchargeable
    # via `FIREBASE_STORAGE_BUCKET` si le bucket réel diverge (ex. projets
    # créés après la bascule de convention de Google vers
    # `<project_id>.firebasestorage.app`).
    GS_BUCKET_NAME = env(
        "FIREBASE_STORAGE_BUCKET", default=f"{GS_PROJECT_ID}.appspot.com"
    )
    GS_DEFAULT_ACL = None  # géré par l'IAM du bucket, pas par des ACL objet par objet
    GS_QUERYSTRING_AUTH = False  # URLs publiques stables, pas de jeton signé expirant

    STORAGES["default"]["BACKEND"] = "storages.backends.gcloud.GoogleCloudStorage"
