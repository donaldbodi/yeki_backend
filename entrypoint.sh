#!/bin/sh
# Point d'entrée du conteneur backend (migration hébergement VPS+Coolify).
# `set -e` : tout échec (migration ratée, collectstatic cassé) arrête le
# démarrage plutôt que de laisser Daphne servir une app à moitié en état —
# mieux vaut un conteneur qui ne démarre pas qu'un serveur qui répond avec un
# schéma de base de données périmé.
set -e

echo "→ Migrations..."
python manage.py migrate --noinput

echo "→ Fichiers statiques..."
python manage.py collectstatic --noinput

echo "→ Démarrage Daphne (HTTP + WebSocket)..."
exec daphne -b 0.0.0.0 -p 8000 config.asgi:application
