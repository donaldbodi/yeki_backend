# Configuration Firebase Storage — persistance des médias (YÉKI backend)

Ce document décrit les actions à effectuer dans la console Firebase/Google
Cloud (aucune ne peut être faite depuis ce dépôt ni par un agent sans accès
à ces consoles) pour que la migration du stockage média
(`django-storages[google]`, `config/settings/production.py`) fonctionne
réellement en production sur Railway.

**Pourquoi cette migration existe** : Railway ne fournit aucun volume
persistant — chaque redéploiement recrée le conteneur avec un système de
fichiers vierge. Tout média uploadé (avatars, images de département, PDF de
leçon, etc.) sur `FileSystemStorage` (le défaut) est donc perdu au
redéploiement suivant. Le code bascule désormais sur Firebase Storage (un
bucket Google Cloud Storage standard) via `django-storages`, en réutilisant
le même compte de service déjà utilisé pour Firebase Cloud Messaging
(`FIREBASE_CREDENTIALS_JSON`, voir `apps/notifications/fcm.py`) — aucun
nouveau compte/projet Firebase à créer.

Projet Firebase concerné : **`yeki-84b1a`** (même projet que Firebase
Hosting — confirmé dans `docs/FIREBASE_SETUP.md` côté frontend).

## Étape 1 — Activer Cloud Storage for Firebase (si pas déjà fait)

1. Ouvrir [console.firebase.google.com](https://console.firebase.google.com/)
   → projet **yeki** (`yeki-84b1a`).
2. Menu latéral → **Build** → **Storage**.
3. Si un écran « Commencer » s'affiche : cliquer dessus, accepter les
   règles de sécurité par défaut proposées (mode production), choisir
   l'emplacement du bucket (garder la valeur par défaut si aucune
   contrainte de localisation particulière).
4. Si Storage affiche déjà une liste de fichiers (même vide) sans écran
   « Commencer » : c'est déjà activé, passer à l'étape 2.

## Étape 2 — Relever le nom réel du bucket

1. Toujours dans l'onglet **Storage → Fichiers**, le nom du bucket est
   affiché en haut de la page, sous la forme `gs://<nom-du-bucket>`.
2. Deux conventions possibles selon la date de création du projet
   (Google a changé sa convention par défaut en 2024) :
   - Ancienne : `yeki-84b1a.appspot.com`
   - Nouvelle : `yeki-84b1a.firebasestorage.app`
3. Le code (`config/settings/production.py`) utilise **par défaut**
   `yeki-84b1a.appspot.com` (`GS_BUCKET_NAME`). Comparer avec ce qui est
   réellement affiché dans la console.

## Étape 3 — Si le nom diffère : définir `FIREBASE_STORAGE_BUCKET`

Seulement si le nom relevé à l'étape 2 est différent de
`yeki-84b1a.appspot.com` :

1. Dashboard Railway → service backend → onglet **Variables**.
2. Ajouter une nouvelle variable : `FIREBASE_STORAGE_BUCKET` = le nom
   exact relevé (ex. `yeki-84b1a.firebasestorage.app`), **sans**
   `gs://` devant.
3. Si le nom correspond déjà à la valeur par défaut : rien à faire,
   passer à l'étape 4.

## Étape 4 — Rendre le bucket public en lecture (obligatoire)

**Point de confusion fréquent, à éviter** : les « Règles » de l'onglet
Storage de la console **Firebase** (`storage.rules`) ne s'appliquent
QU'AUX accès faits via un SDK Firebase authentifié (client mobile/web
Firebase) — **jamais** aux URLs directes générées par `django-storages`
(`https://storage.googleapis.com/<bucket>/<chemin>`). Modifier ces
règles ne changera rien ici. Le contrôle d'accès pertinent est l'**IAM du
bucket Google Cloud Storage**, une console différente.

1. Ouvrir [console.cloud.google.com/storage/browser](https://console.cloud.google.com/storage/browser)
   (bien vérifier que le projet sélectionné en haut est `yeki-84b1a`).
2. Cliquer sur le bucket (nom relevé à l'étape 2).
3. Onglet **Permissions** (ou « Autorisations »).
4. Bouton **Accorder l'accès** (« Grant access »).
5. Champ « Nouveaux principaux » : saisir `allUsers`.
6. Rôle à attribuer : **Storage Object Viewer** (« Lecteur des objets
   Storage »).
7. Enregistrer — un avertissement Google confirmant que « cela rendra
   les données publiquement accessibles » apparaît : c'est attendu et
   voulu (même modèle de confiance qu'avant cette migration, quand les
   médias étaient déjà servis sans authentification sous `/media/...`).

## Étape 5 — Vérifier les droits d'écriture du compte de service (seulement en cas d'erreur)

À faire uniquement si la commande de vérification (étape 6 ci-dessous)
signale une erreur de permission à l'**écriture** :

1. [console.cloud.google.com/iam-admin/iam](https://console.cloud.google.com/iam-admin/iam)
   (projet `yeki-84b1a`).
2. Repérer le compte de service dont l'adresse ressemble à
   `firebase-adminsdk-xxxxx@yeki-84b1a.iam.gserviceaccount.com` — c'est
   le même compte que celui dont la clé JSON est déjà utilisée dans la
   variable d'environnement `FIREBASE_CREDENTIALS_JSON` de Railway
   (utilisée aussi pour les notifications push).
3. Si son rôle actuel ne couvre pas l'écriture sur Storage : cliquer sur
   le crayon d'édition → **Ajouter un autre rôle** → **Storage Object
   Admin** → Enregistrer.

## Étape 6 — Redéployer puis vérifier

1. Un changement de variable d'environnement sur Railway déclenche
   normalement un redéploiement automatique du service. Sinon : bouton
   **Redeploy** du service depuis le dashboard Railway.
2. Une fois le déploiement terminé, exécuter la commande de vérification
   dédiée (voir ci-dessous) — elle confirme en un seul passage l'écriture,
   la lecture publique ET nettoie après elle, sans dépendre d'un upload
   manuel dans l'app :

   ```bash
   python manage.py verifier_stockage_medias
   ```

   - Depuis le dashboard Railway, si l'option d'exécuter une commande
     ponctuelle est disponible pour votre plan.
   - Sinon, en local, temporairement, avec les vraies variables
     d'environnement de production (`DJANGO_SETTINGS_MODULE=config.
     settings.production`, et les mêmes `FIREBASE_CREDENTIALS_JSON`/
     `FIREBASE_STORAGE_BUCKET` que Railway) — ne jamais committer ces
     valeurs, les retirer de l'environnement local une fois le test fait.

   La commande indique clairement, à chaque échec, à quelle étape de ce
   guide revenir (403 à l'écriture → étape 5 ; 403 à la lecture de
   l'URL publique → étape 4).

3. Test de non-régression final, dans l'app elle-même : uploader une
   vraie image (photo de profil ou image de département), noter l'URL
   renvoyée (doit commencer par `https://storage.googleapis.com/...`,
   plus par le domaine de l'API), puis déclencher un nouveau
   déploiement Railway (n'importe quel prochain push suffit) et
   recharger cette même image : elle doit toujours s'afficher — la
   preuve concrète que les médias ne sont plus perdus au déploiement.
