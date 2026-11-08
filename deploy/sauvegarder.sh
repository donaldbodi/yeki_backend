#!/bin/sh
# Sauvegarde quotidienne de la base et des médias (cron posé par
# preparer-vps.sh), 14 jours conservés. Ces fichiers restent sur le VPS : les
# copier ailleurs régulièrement (voir docs/DEPLOIEMENT_OVH.md), sinon une perte
# du disque emporte tout.
set -eu

cd /opt/yeki
COMPOSE="docker compose -f docker-compose.prod.yml"
HORODATAGE="$(date +%Y%m%d-%H%M%S)"
FICHIER="backups/yeki-$HORODATAGE.dump"
MEDIAS="backups/medias-$HORODATAGE.tar.gz"

$COMPOSE exec -T db pg_dump -U yeki -d yeki -Fc >"$FICHIER.tmp"
mv "$FICHIER.tmp" "$FICHIER"

$COMPOSE exec -T web tar -czf - -C /app media >"$MEDIAS.tmp"
mv "$MEDIAS.tmp" "$MEDIAS"

find backups \( -name 'yeki-*.dump' -o -name 'medias-*.tar.gz' \) -mtime +14 -delete
echo "$(date -Iseconds) OK $FICHIER $MEDIAS"
