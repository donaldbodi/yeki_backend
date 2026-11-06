#!/bin/sh
# Point d'entrée du conteneur backend (voir docs/MIGRATION_OVH.md).
# `set -e` : tout échec (migration ratée, collectstatic cassé) arrête le
# démarrage plutôt que de laisser Daphne servir une app à moitié en état —
# mieux vaut un conteneur qui ne démarre pas qu'un serveur qui répond avec un
# schéma de base de données périmé.
set -e

# Commande explicite (ex. `docker compose run --rm web python manage.py ...`) :
# on l'exécute telle quelle, sans démarrer Daphne.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "→ Migrations..."
python manage.py migrate --noinput

echo "→ Fichiers statiques..."
python manage.py collectstatic --noinput

echo "→ Démarrage Daphne (HTTP + WebSocket)..."
exec daphne -b 0.0.0.0 -p 8000 config.asgi:application
