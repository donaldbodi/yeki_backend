"""
Publie/met à jour la ligne `AppVersion(platform="android")` réelle,
pointant vers l'APK déjà servi statiquement
(`yeki/static/app/yeki-v.1.0.3.apk`, confirmé présent sur le serveur)
mais jamais référencé par aucune ligne en base jusqu'ici — les endpoints
`GET /api/latest-version/`/`GET /api/app/version/` renvoyaient donc des
réponses vides pour la plateforme Android.

Valeurs dérivées de sources réelles, aucune inventée (règle 3) :
- `version_code`/`version_name` : `pubspec.yaml` du frontend (`1.0.3+2`),
  cohérent avec le nom du fichier APK.
- `file_size`/`checksum_sha256` : calculés directement sur le fichier
  réel présent sur le disque (`os.path.getsize`/`hashlib.sha256`), jamais
  une valeur en dur qui pourrait devenir fausse si le fichier change.

Idempotente (`update_or_create` sur `(platform, canal, version_code)`,
la contrainte `unique_together` du modèle) — peut être relancée sans
créer de doublon à chaque nouveau déploiement.

Usage : `python manage.py publier_version_android` (une fois après
déploiement backend). Aucune ligne iOS/Desktop créée — aucun binaire réel
n'existe pour ces plateformes (décision actée avec l'utilisateur), les
endpoints continueront de répondre vide pour elles jusqu'à ce qu'un vrai
binaire existe.
"""

import hashlib
import os

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import AppVersion

# Domaine de production réel (même valeur déjà utilisée par le frontend,
# `lib/core/constants/api_constants.dart`) — aucun `SITE_URL`/
# `BACKEND_BASE_URL` dédié n'existe dans les settings à ce jour.
BASE_URL_PRODUCTION = "https://yekibackend-production.up.railway.app"

APK_RELATIVE_PATH = "app/yeki-v.1.0.3.apk"
VERSION_NAME = "1.0.3"
VERSION_CODE = 2


class Command(BaseCommand):
    help = "Publie la ligne AppVersion réelle pour l'APK Android déjà servi statiquement."

    def handle(self, *args, **options):
        # `AppConfig.path` pointe déjà sur le package `yeki/` lui-même
        # (ex. `.../yeki_backend/yeki`), pas sur son parent — le dossier
        # `static/` de l'app vit directement dessous.
        yeki_static_dir = os.path.join(django_apps.get_app_config("yeki").path, "static")
        apk_path = os.path.join(yeki_static_dir, APK_RELATIVE_PATH)
        if not os.path.exists(apk_path):
            raise CommandError(
                f"APK introuvable à {apk_path} — rien à publier. "
                "Vérifiez que yeki/static/app/yeki-v.1.0.3.apk existe bien sur ce serveur."
            )

        file_size = os.path.getsize(apk_path)
        sha256 = hashlib.sha256()
        with open(apk_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                sha256.update(chunk)
        checksum = sha256.hexdigest()

        download_url = f"{BASE_URL_PRODUCTION}/static/{APK_RELATIVE_PATH}"

        version, created = AppVersion.objects.update_or_create(
            platform="android",
            canal="stable",
            version_code=VERSION_CODE,
            defaults={
                "version_name": VERSION_NAME,
                "download_url": download_url,
                "checksum_sha256": checksum,
                "file_size": file_size,
                "min_version_code": 1,
                "force_update": False,
                "is_active": True,
                "changelog": "Version initiale disponible au téléchargement.",
            },
        )

        verbe = "Créée" if created else "Mise à jour"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verbe} : {version} — {file_size:,} octets, sha256={checksum[:12]}…, "
                f"download_url={download_url}"
            )
        )
