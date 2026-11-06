#!/bin/sh
# Sauvegarde PostgreSQL quotidienne (cron posé par preparer-vps.sh), 14 jours
# conservés. Ces fichiers restent sur le VPS : les copier ailleurs régulièrement
# (voir docs/MIGRATION_OVH.md), sinon une perte du disque emporte tout.
set -eu

cd /opt/yeki
FICHIER="backups/yeki-$(date +%Y%m%d-%H%M%S).dump"

docker compose -f docker-compose.prod.yml exec -T db \
    pg_dump -U yeki -d yeki -Fc >"$FICHIER.tmp"
mv "$FICHIER.tmp" "$FICHIER"

find backups -name 'yeki-*.dump' -mtime +14 -delete
echo "$(date -Iseconds) OK $FICHIER"
