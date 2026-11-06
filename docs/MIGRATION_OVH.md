# Migration hébergement backend : Railway → VPS OVH

**Ce qui ne change pas** : l'image Docker (Daphne, HTTP + WebSocket), les
médias (Firebase Storage), le frontend web (Firebase Hosting, CORS inchangé).

## Architecture

```
Internet ──443──▶ Caddy (certificat HTTPS auto) ──▶ Daphne (HTTP + WebSocket)
                                                     ├─▶ PostgreSQL 17
                                                     └─▶ Redis (WebSocket)
```

Tout tourne sur le VPS avec Docker Compose (`docker-compose.prod.yml`). Seul
Caddy est joignable depuis Internet. L'adresse publique est
`<ip-en-tirets>.sslip.io` : ce service gratuit fait pointer ce nom vers l'IP, ce
qui permet d'obtenir un vrai certificat sans acheter de domaine.

> **À savoir** : cette URL est figée dans les APK. Si l'IP change ou si sslip.io
> tombe, les applications installées perdent le serveur. Un domaine à soi (une
> dizaine d'euros par an) supprime ce risque : à prévoir avant une vraie montée
> en charge, en changeant `DOMAIN` et `apiHost`.

Dans les commandes ci-dessous, remplacer `IP` par l'IP du VPS (e-mail de
livraison OVH). Les commandes « sur le PC » se lancent dans Git Bash, depuis
`yeki_backend/yeki_backend/`.

## Procédure de bascule

### 1. Clé SSH (sur le PC)

```bash
ssh-keygen -t ed25519
cat ~/.ssh/id_ed25519.pub | ssh ubuntu@IP "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
ssh ubuntu@IP   # doit se connecter sans demander le mot de passe
```

### 2. Préparer le VPS

Le script installe Docker, le pare-feu (22, 80, 443), fail2ban et la sauvegarde
quotidienne, et désactive la connexion SSH par mot de passe.

```bash
scp deploy/preparer-vps.sh ubuntu@IP:
ssh ubuntu@IP "sudo sh preparer-vps.sh"
```

### 3. Créer `/opt/yeki/.env`

```bash
scp deploy/env.production.example ubuntu@IP:/opt/yeki/.env
scp chemin/vers/firebase-service-account.json ubuntu@IP:firebase.json
ssh ubuntu@IP
```

Puis sur le VPS :

```bash
sudo apt-get install -y jq
sed -i '/^FIREBASE_CREDENTIALS_JSON=/d' /opt/yeki/.env
printf "FIREBASE_CREDENTIALS_JSON='%s'\n" "$(jq -c . ~/firebase.json)" >> /opt/yeki/.env
rm ~/firebase.json
chmod 600 /opt/yeki/.env
openssl rand -hex 32   # valeur de POSTGRES_PASSWORD
nano /opt/yeki/.env    # renseigner DOMAIN, POSTGRES_PASSWORD et les valeurs Railway
```

Garder le même `SECRET_KEY` que sur Railway. Les jetons de connexion, eux, sont
en base et survivent à l'import : les utilisateurs restent connectés.

### 4. Premier déploiement

Remplacer `IP-DU-VPS` dans `lib/core/constants/api_constants.dart` (dépôt
frontend). Côté backend, commiter (le déploiement envoie le dernier commit), puis :

```bash
sh deploy/deployer.sh ubuntu@IP
ssh ubuntu@IP "cd /opt/yeki && docker compose -f docker-compose.prod.yml ps"
```

Les quatre services doivent être `running`, `web` et `db` en `healthy`.

### 5. Vérifier avant de toucher aux données

```bash
curl -I https://IP-EN-TIRETS.sslip.io/          # 200, certificat valide
curl -i -N --http1.1 --max-time 5 \
  -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: SGVsbG8sIHdvcmxkIQ==" \
  -H "Sec-WebSocket-Protocol: yeki" \
  https://IP-EN-TIRETS.sslip.io/ws/forum/       # 101 Switching Protocols
```

Le `101` prouve que le WebSocket traverse Caddy jusqu'à Daphne. Le serveur ferme
ensuite aussitôt la connexion (code 4401) : aucun jeton n'a été fourni.

### 6. Importer les données (fenêtre de maintenance)

Préparer d'abord l'APK et le build web de l'étape 7 : la coupure sera plus courte.

1. Railway : mettre en pause le service **backend** (pas la base), pour figer les
   écritures. Tout ce qui serait écrit après l'export serait perdu.
2. Copier l'URL publique : service Postgres → Variables → `DATABASE_PUBLIC_URL`.
3. Sur le VPS :

```bash
sh /opt/yeki/deploy/importer-base.sh
```

Si `pg_dump` refuse à cause d'une version de serveur plus récente, passer l'image
`db` à cette version dans `docker-compose.prod.yml` avant de relancer.

Vérifier ensuite : connexion à `/admin/` avec un compte existant, `/api/docs/`,
un upload (Firebase Storage), un paiement test CinetPay, et le forum sur deux
appareils (une question postée sur l'un apparaît sur l'autre en 1 à 2 secondes).

Activer ensuite les tâches planifiées (rappels, réinitialisation des classements) :

```bash
sudo install -m 644 /opt/yeki/deploy/taches.cron /etc/cron.d/yeki-taches
```

Attention : la première exécution de `reinitialiser_periodes_echues` archive et
remet à zéro le classement de tous les départements dont la période est échue.
Pour voir la liste avant, utiliser son option de simulation
(`docker compose -f docker-compose.prod.yml exec web python manage.py reinitialiser_periodes_echues --dry-run`).

### 7. Basculer les clients

Dans le dépôt frontend :

```bash
flutter pub get
flutter build web && firebase deploy --only hosting
flutter build apk --release
```

Les APK déjà installés gardent l'URL Railway et n'interrogent que Railway pour
connaître la dernière version. Publier donc la mise à jour **sur Railway aussi**
(réactiver le service le temps de le faire), sinon ces utilisateurs ne verront
jamais l'appel à mettre à jour. CinetPay : rien à faire, `notify_url` est envoyée
par le backend à chaque paiement.

### 8. Déploiement continu

Sur le PC, créer une clé dédiée et l'autoriser sur le VPS :

```bash
ssh-keygen -t ed25519 -f yeki_deploy -N ""
cat yeki_deploy.pub | ssh ubuntu@IP "cat >> ~/.ssh/authorized_keys"
ssh-keyscan IP
```

GitHub → Settings → Secrets and variables → Actions, créer : `VPS_HOST` (l'IP),
`VPS_USER` (`ubuntu`), `VPS_SSH_KEY` (contenu de `yeki_deploy`),
`VPS_KNOWN_HOSTS` (sortie de `ssh-keyscan`). Supprimer ensuite les deux fichiers
`yeki_deploy*` du PC. Chaque push sur `main` qui passe les tests est alors
déployé. Désactiver l'auto-déploiement Railway.

### 9. Décommissionner Railway

Après quelques jours sans trafic (vérifier les logs Railway), et une fois les
utilisateurs passés sur le nouvel APK : supprimer le backend, la base et le Redis
Railway. Le dump d'import reste dans `/opt/yeki/backups/`. Fermer aussi le compte
Fly.io s'il y reste quelque chose.

## Sauvegardes : à ne pas négliger

Il n'y a plus de base managée : **vous êtes seul responsable des sauvegardes**.
Le cron crée chaque nuit un dump dans `/opt/yeki/backups/` (14 jours conservés),
mais sur le même disque que la base. Copier régulièrement sur le PC :

```bash
scp "ubuntu@IP:/opt/yeki/backups/yeki-*.dump" ./sauvegardes/
```

Ou activer l'option de sauvegarde automatique dans l'espace client OVH.

Restaurer un dump (sur le VPS) :

```bash
cd /opt/yeki
docker compose -f docker-compose.prod.yml stop web
docker compose -f docker-compose.prod.yml exec -T db dropdb -U yeki --force yeki
docker compose -f docker-compose.prod.yml exec -T db createdb -U yeki yeki
docker compose -f docker-compose.prod.yml exec -T db pg_restore -U yeki -d yeki --no-owner --no-acl < backups/FICHIER.dump
docker compose -f docker-compose.prod.yml up -d web
```

## Exploitation courante

Sur le VPS, depuis `/opt/yeki` (avec `alias dc="docker compose -f docker-compose.prod.yml"`) :

```bash
dc ps                                        # état des services
dc logs -f web                               # logs Django/Daphne
dc logs caddy                                # problèmes de certificat
dc exec web python manage.py createsuperuser # commandes manage.py
dc restart web                               # après modification de .env : dc up -d
```

Mises à jour de sécurité Ubuntu : automatiques (`unattended-upgrades`). Un
redémarrage du VPS relance tous les conteneurs (`restart: unless-stopped`).
