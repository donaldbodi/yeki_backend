"""Settings de production — PostgreSQL, HTTPS strict, HSTS, cookies sécurisés."""

from .base import *  # noqa: F401,F403

DEBUG = False

# Liste extensible par variable d'environnement (`env.list`, django-environ).
# Sur le VPS, docker-compose.prod.yml la renseigne à partir de `DOMAIN`.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

# Admin Django en HTTPS derrière le proxy Caddy : l'origine doit être déclarée
# explicitement pour que le formulaire de connexion passe la vérification
# CSRF (Django ≥ 4). Dérivé d'ALLOWED_HOSTS pour n'avoir qu'une variable à
# maintenir.
CSRF_TRUSTED_ORIGINS = [
    f"https://*{host}" if host.startswith(".") else f"https://{host}"
    for host in ALLOWED_HOSTS
    if host != "*"
]

# Caddy termine le HTTPS et transmet la requête à Daphne en HTTP interne, le
# protocole d'origine étant porté par `X-Forwarded-Proto`. Sans cette ligne,
# `request.build_absolute_uri()` (champs `*_url` des serializers, URLs CinetPay)
# génère des URLs `http://...`, bloquées comme contenu mixte par le navigateur.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ── Channels (WebSocket) ────────────────────────────────────────────────────
# Redis partage les groupes du forum entre process : la couche mémoire de
# `base.py` ne fonctionne qu'en single-process.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env("REDIS_URL")],
        },
    }
}

# `DATABASE_URL` vient de docker-compose.prod.yml. Pas de `CONN_MAX_AGE` : Django
# exige des connexions non persistantes sous ASGI, où chaque requête tourne dans
# son propre thread — elles s'accumuleraient jusqu'à saturer `max_connections`.
DATABASES = {"default": env.db("DATABASE_URL")}

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
# Le disque du conteneur est effacé à chaque déploiement : les médias vivent
# donc hors du VPS (`FileSystemStorage`, le défaut de `base.py`, les perdrait). Firebase
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
