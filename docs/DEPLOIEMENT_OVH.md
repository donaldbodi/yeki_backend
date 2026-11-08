# Déploiement du backend sur le VPS OVH

Le backend tourne sur un VPS OVH ; le frontend web reste sur Firebase Hosting.
Les médias vont dans le volume Docker `media_data`, ou sur Firebase Storage si
`FIREBASE_CREDENTIALS_JSON` est rempli.

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

## Mise en place

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
nano /opt/yeki/.env    # renseigner DOMAIN, POSTGRES_PASSWORD et les secrets
```

### 4. Premier déploiement

Remplacer `IP-DU-VPS` dans `lib/core/constants/api_constants.dart` (dépôt
frontend). Côté backend, commiter (le déploiement envoie le dernier commit), puis :

```bash
sh deploy/deployer.sh ubuntu@IP
ssh ubuntu@IP "cd /opt/yeki && docker compose -f docker-compose.prod.yml ps"
```

Les quatre services doivent être `running`, `web` et `db` en `healthy`.

### 5. Vérifier

```bash
curl -I https://IP-EN-TIRETS.sslip.io/          # 200, certificat valide
curl -i -N --http1.1 --max-time 5 \
  -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Sec-WebSocket-Protocol: yeki" \
  https://IP-EN-TIRETS.sslip.io/ws/forum/       # 101 Switching Protocols
```

Le `101` prouve que le WebSocket traverse Caddy jusqu'à Daphne. Le serveur ferme
ensuite aussitôt la connexion (code 4401) : aucun jeton n'a été fourni.

### 6. Premier administrateur et tâches planifiées

La base démarre vide. Créer le compte administrateur (le mot de passe se tape au
clavier) :

```bash
ssh -t ubuntu@IP "cd /opt/yeki && docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser"
```

Puis, depuis `https://IP-EN-TIRETS.sslip.io/admin/`, créer les parcours et les
départements : le formulaire d'inscription de l'app en a besoin.

Activer les tâches planifiées (rappels, réinitialisation des classements) :

```bash
sudo install -m 644 /opt/yeki/deploy/taches.cron /etc/cron.d/yeki-taches
```

Vérifier ensuite : un upload (image toujours visible après un redéploiement), un
paiement test CinetPay, et le forum sur deux appareils (une question postée sur
l'un apparaît sur l'autre en 1 à 2 secondes).

### 7. Publier l'app

Dans le dépôt frontend :

```bash
flutter pub get
flutter build web && firebase deploy --only hosting
flutter build apk --release
```

Les APK installés avant ce changement visent l'ancien serveur et ne peuvent pas
être prévenus : leurs utilisateurs doivent installer le nouvel APK eux-mêmes.
CinetPay : rien à faire, `notify_url` est envoyée par le backend à chaque paiement.

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
déployé.

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
