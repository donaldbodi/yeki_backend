#!/bin/sh
# Déploie le dernier commit sur le VPS, depuis un poste de développement ou la CI :
#   sh deploy/deployer.sh ubuntu@IP_DU_VPS
# Seuls .env et les sauvegardes survivent : les fichiers supprimés du dépôt ne
# restent pas sur le serveur, où ils finiraient dans l'image Docker.
set -eu

CIBLE="${1:?Usage : sh deploy/deployer.sh utilisateur@hote}"

git archive --format=tar HEAD | ssh "$CIBLE" '
    set -eu
    cd /opt/yeki
    find . -mindepth 1 -maxdepth 1 ! -name .env ! -name backups -exec rm -rf {} +
    tar -xf -
    docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
    docker image prune -f
'
