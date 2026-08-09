"""
Vérifie que le stockage des médias (Firebase Storage en production, voir
docs/FIREBASE_STORAGE_SETUP.md) est réellement opérationnel de bout en
bout : écriture, lecture publique, puis nettoyage — en un seul passage,
sans dépendre d'un upload manuel dans l'app ni d'un navigateur.

À exécuter après chaque changement de configuration du stockage
(bucket, permissions IAM) pour confirmer que la modification a pris
effet, avant de considérer la migration terminée.
"""

import uuid

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Vérifie l'écriture + la lecture publique du stockage des médias "
        "configuré (voir docs/FIREBASE_STORAGE_SETUP.md)."
    )

    def handle(self, *args, **options):
        backend = settings.STORAGES["default"]["BACKEND"]

        if backend == "django.core.files.storage.FileSystemStorage":
            self.stdout.write(
                "Stockage local (FileSystemStorage) actif — aucune vérification "
                "cloud à faire ici. Ceci est normal en dev/tests ; en production, "
                "confirmer que FIREBASE_CREDENTIALS_JSON est bien défini pour que "
                "config/settings/production.py bascule sur Firebase Storage."
            )
            return

        nom_fichier = f"_verification_stockage/{uuid.uuid4().hex}.txt"
        contenu = b"verification stockage medias yeki"

        self.stdout.write(f"Backend actif : {backend}")
        self.stdout.write(f"Ecriture d'un fichier de test ({nom_fichier})...")
        try:
            chemin_enregistre = default_storage.save(nom_fichier, ContentFile(contenu))
        except Exception as exc:
            raise CommandError(
                "Echec a l'ECRITURE — vérifier les droits du compte de service "
                "(docs/FIREBASE_STORAGE_SETUP.md, étape 5). "
                f"Erreur d'origine : {exc}"
            ) from exc
        self.stdout.write(self.style.SUCCESS("Ecriture OK."))

        try:
            url = default_storage.url(chemin_enregistre)
            self.stdout.write(f"URL publique générée : {url}")

            self.stdout.write("Lecture de cette URL en HTTP (sans authentification)...")
            try:
                reponse = requests.get(url, timeout=15)
            except Exception as exc:
                raise CommandError(
                    "Echec de la requête HTTP vers l'URL générée — vérifier la "
                    f"connectivité réseau. Erreur d'origine : {exc}"
                ) from exc

            if reponse.status_code != 200:
                raise CommandError(
                    f"Echec à la LECTURE PUBLIQUE (HTTP {reponse.status_code}) — le "
                    "bucket n'est probablement pas encore public en lecture "
                    "(docs/FIREBASE_STORAGE_SETUP.md, étape 4)."
                )
            if reponse.content != contenu:
                raise CommandError(
                    "Le contenu lu à l'URL publique ne correspond pas au fichier "
                    "écrit — configuration de cache/CDN inattendue à investiguer."
                )
            self.stdout.write(self.style.SUCCESS("Lecture publique OK."))
        finally:
            self.stdout.write("Suppression du fichier de test...")
            default_storage.delete(chemin_enregistre)

        self.stdout.write(
            self.style.SUCCESS(
                "Stockage des médias opérationnel : écriture et lecture publique "
                "confirmées."
            )
        )
