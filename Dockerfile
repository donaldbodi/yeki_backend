# Migration hébergement VPS+Coolify (voir plan de migration, ticket
# "Migration hébergement backend : PythonAnywhere → VPS Hetzner + Coolify").
# Image de production : sert HTTP + WebSocket dans le même process via
# Daphne (serveur ASGI officiel de Channels) — PythonAnywhere ne servait que
# du WSGI, ce qui empêchait tout WebSocket (voir docs/FORUM_TEMPS_REEL.md).

FROM python:3.13-slim

# Pas de .pyc/.pyo persistés dans l'image (inutiles, alourdissent) ; sortie
# non bufferisée pour que les logs apparaissent immédiatement dans Coolify.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# psycopg2-binary et Pillow embarquent déjà leurs dépendances C (libpq,
# libjpeg/zlib) sous forme de wheels manylinux — aucun paquet système
# supplémentaire nécessaire pour l'instant. À revoir si un futur ajout à
# requirements.txt en réclame un (ex. WeasyPrint pour des PDF générés).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

# `migrate`/`collectstatic` tournent à chaque démarrage de conteneur (pas au
# build) — nécessitent les variables d'environnement réelles (SECRET_KEY,
# DB_*...), qui n'existent qu'à l'exécution côté Coolify, pas au moment du
# build de l'image.
ENTRYPOINT ["./entrypoint.sh"]
