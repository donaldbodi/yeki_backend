# Forum en temps réel

Daphne sert le WebSocket derrière Caddy (voir `MIGRATION_OVH.md`). Quatre défauts
indépendants de l'hébergement l'empêchaient de fonctionner avant 2026-11.

- **Aucun client** : le code WebSocket Flutter avait été supprimé,
  et `forumRealtimeEnabled` à `false` coupait aussi le sondage. Le forum ne
  se rafraîchissait donc plus du tout.
- **Authentification** : `AuthMiddlewareStack` lit le cookie de session, or
  l'app utilise un `Token` DRF. Toute connexion était anonyme, donc fermée.
- **Consumer cassé** : `yeki/consumers.py` importait les modèles depuis
  `yeki.models`, où ils ne sont plus depuis l'éclatement en `apps/`. Il écrivait
  aussi en base sans passer par la matrice Gratuit/Premium.
- **Aucune diffusion** : seul le consumer publiait. Une question créée par
  l'API REST, seul chemin d'écriture réel, n'était jamais signalée.

### Principe

Le WebSocket **signale**, l'API REST **fait foi**.

1. Une écriture passe par l'API REST, sans changement.
2. Un signal Django (`apps/forum/signals.py`) publie après le commit un événement
   sans contenu (`apps/forum/realtime.py`), par exemple
   `{"evenement": "reponse_creee", "question_id": 12, "reponse_id": 40, "cours_id": 3}`.
3. Le client recharge par REST, 1 seconde après le dernier événement d'une
   rafale. La matrice d'accès s'applique donc comme d'habitude, et aucun contenu
   Premium ne circule sur le socket.

| Salle | URL | Reçoit |
|---|---|---|
| Globale | `/ws/forum/` | toutes les questions (comme la liste non filtrée) |
| Cours | `/ws/forum/cours/<id>/` | les questions de ce cours |

Événements : `question_creee`, `question_modifiee`, `question_supprimee`,
`reponse_creee`, `reponse_modifiee`, `like_modifie`.

### Authentification

Le jeton passe dans le sous-protocole : `["yeki", "token.<jeton>"]`. C'est le seul
canal disponible aussi depuis un navigateur, et il reste hors des journaux
d'accès, contrairement à `?token=`. Ne pas activer de journal d'accès Caddy : il
enregistrerait cet en-tête.

| Code de fermeture | Sens | Client |
|---|---|---|
| 4401 | jeton absent, invalide ou compte inactif | abandon, sondage coupé |
| 4403 | pas d'accès au forum (apprenant gratuit) | abandon, sondage coupé |
| autre | coupure réseau, redéploiement | reconnexion bornée |

Aucune validation d'origine : sans cookie, un site tiers ne peut pas ouvrir de
connexion au nom d'un visiteur (voir `config/asgi.py`).

### Reconnexion et repli

**Exigence non négociable** : toute reconnexion est bornée. 3 tentatives (2, 4 et
8 secondes), puis arrêt avec un log unique, jusqu'à la prochaine ouverture de
l'écran ou le retour de l'app au premier plan. Le compteur ne repart à zéro
qu'après 30 secondes de connexion stable. Ne jamais reproduire la boucle infinie
de l'ancien `websocket_service.dart`.

Le sondage `GET /api/forum/<room>/messages/?since=` reste actif sur l'écran de
liste : toutes les 8 secondes sans WebSocket, toutes les 60 secondes avec, en filet
contre les coupures silencieuses. Il repasse aussi une fois à chaque ouverture du
socket, pour rattraper ce qui a été manqué. Rien ne tourne en arrière-plan.

Un redéploiement coupe les sockets plus longtemps que les 14 secondes de
tentatives : les clients ouverts passent alors au sondage jusqu'à leur prochain
retour sur l'écran. Le forum reste à jour, avec jusqu'à 8 secondes de latence.

Redis indisponible ne bloque aucune écriture : l'erreur est journalisée et les
clients se rattrapent par sondage.
