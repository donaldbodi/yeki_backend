#!/bin/sh
# Remplace la base du VPS par une copie de la base source.
# À lancer sur le VPS ; l'URL est lue au clavier pour rester hors de l'historique :
#   sh /opt/yeki/deploy/importer-base.sh
# pg_dump tourne dans le conteneur Postgres 17 : rien à installer, et la version
# reste compatible avec un serveur source en version 17 ou inférieure.
set -eu

cd /opt/yeki
COMPOSE="docker compose -f docker-compose.prod.yml"
FICHIER="backups/import-$(date +%Y%m%d-%H%M%S).dump"

printf 'URL publique de la base source (postgresql://...) : '
stty -echo
read -r SOURCE
stty echo
echo

printf 'La base du VPS va être ÉCRASÉE. Écrire "oui" pour continuer : '
read -r REPONSE
[ "$REPONSE" = "oui" ] || { echo "Annulé."; exit 1; }

$COMPOSE up -d db
$COMPOSE stop web

echo "→ Export de la base source..."
$COMPOSE exec -T -e SOURCE="$SOURCE" db sh -c 'pg_dump --no-owner --no-acl -Fc "$SOURCE"' >"$FICHIER.tmp"
mv "$FICHIER.tmp" "$FICHIER"

echo "→ Restauration..."
$COMPOSE exec -T db dropdb -U yeki --if-exists --force yeki
$COMPOSE exec -T db createdb -U yeki yeki
$COMPOSE exec -T db pg_restore -U yeki -d yeki --no-owner --no-acl --exit-on-error <"$FICHIER"

$COMPOSE up -d web
echo "Terminé. Copie conservée : $FICHIER"
