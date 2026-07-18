# Forum en « temps réel » — constat et arbitrage

## Constat (2026-07-16)

Le client Flutter visait `wss://yeki.pythonanywhere.com/ws/forum/{room}/?token=…`
avec reconnexion automatique. Vérification côté serveur : **ce endpoint n'a
jamais existé et ne peut pas exister sur l'hébergement actuel**.

- `channels` n'est ni dans `INSTALLED_APPS`, ni dans `requirements.txt`, ni
  installé dans le venv du projet.
- `yeki/consumers.py` (un `ForumConsumer` complet, gérant `new_question`,
  `new_reponse`, `like`, `join_cours`, `ping`) et `yeki/routing.py`
  (`ws/forum/`, `ws/forum/cours/<cours_id>/`) existent et sont **du code
  mort** : `import channels...` y échouerait immédiatement si le module
  était chargé.
- `yeki_backend/asgi.py` construit bien un `ProtocolTypeRouter` avec ces
  routes WebSocket, mais **PythonAnywhere (offre standard) ne sert que du
  WSGI** (`WSGI_APPLICATION` dans `settings.py`, pas d'`ASGI_APPLICATION`).
  `asgi.py` n'est donc jamais exécuté en production, quelle que soit la
  configuration réseau.
- Quelqu'un avait commencé cette fonctionnalité côté serveur sans jamais la
  finir ni l'installer.

**Côté client, le constat initial était en partie erroné** : ni
`lib/services/websocket_service.dart` ni `lib/widgets/websocket_service.dart`
(deux fichiers quasi-doublons du même service) n'étaient importés ou
instanciés nulle part dans l'app — vérifié par grep et par un agent
d'exploration indépendant, deux fois. Aucun écran n'appelait `.connect()`.
Le WebSocket n'était donc **pas** actif en production. Ces deux fichiers ont
été supprimés (voir plus bas).

Le **vrai bug actif**, de même nature (batterie/data gaspillées) : dans
`lib/views/pages/apprenants/forum_page.dart`, un `Timer.periodic` sondait déjà
`GET /api/forum/questions/` toutes les 30 secondes, **sans jamais se mettre
en pause quand l'app passe en arrière-plan**. C'est ce mécanisme qui a été
corrigé.

## Ce qui a changé

- **Supprimés** : `lib/services/websocket_service.dart`,
  `lib/widgets/websocket_service.dart` (code mort, dupliqué, inatteignable —
  aucun appelant, et de toute façon inopérant côté serveur) ; la dépendance
  `web_socket_channel` retirée de `pubspec.yaml`.
- **Conservés sans modification** : `yeki/consumers.py`, `yeki/routing.py`,
  `yeki_backend/asgi.py` — scaffolding Channels non fonctionnel, gardé
  comme fondation possible pour une vraie implémentation future (règle
  « ne rien perdre »). Ne pas les brancher sans avoir d'abord réglé
  l'hébergement (voir Voie A ci-dessous).
- **Ajouté** : `ApiConstants.forumRealtimeEnabled = false` — drapeau
  documentaire (aucun code ne le lit aujourd'hui, rien n'appelle plus de
  WebSocket) : garde-fou pour dissuader une réintroduction de connexion
  temps réel brute sans relire ce document.
- **Corrigé** : `forum_page.dart` sonde désormais `GET /api/forum/<room>/messages/?since=<ts>`
  toutes les 8 secondes, uniquement quand l'écran est visible (`WidgetsBindingObserver`,
  pause sur `paused`/`inactive`/`detached`, reprise + sondage immédiat sur
  `resumed`). Chaque sondage silencieux est léger (JSON vide la plupart du
  temps) ; la liste complète (`GET /api/forum/questions/`) n'est
  redemandée que si une vraie activité est détectée depuis le dernier
  passage.
- **Ajouté côté backend** : `GET /api/forum/<room>/messages/?since=<ts>`
  (`ForumMessagesPollingView`, `yeki/views.py`) — `room` = `cours_id`
  numérique ou le littéral `global` (même convention que l'ancien
  consumer). Réutilise le filtrage déjà en place dans `ListeQuestionsView`
  plutôt que de le dupliquer, et comble un trou identifié pendant l'audit :
  le filtre `since` existant (`ListeQuestionsView`) ne détectait que les
  nouvelles questions, jamais les nouvelles réponses à une question
  existante — le nouvel endpoint renvoie aussi `reponses_recentes_ids`.

## Deux voies pour du vrai temps réel plus tard

### A. Migration d'hébergement (push réel, WebSocket fonctionnel)

Nécessite un hébergeur supportant ASGI (Railway, Render, Fly.io, VPS avec
Daphne ou Uvicorn derrière Nginx).

- **Coût argent** : au-delà d'un palier gratuit selon le trafic — à
  chiffrer au moment venu selon le fournisseur retenu.
- **Coût effort** : installer `channels` (+ `channels-redis` ou une couche
  mémoire pour le layer de canaux), brancher `ASGI_APPLICATION` dans
  `settings.py`, réactiver `yeki/consumers.py`/`routing.py` (déjà écrits),
  tester la montée en charge, migrer le déploiement de production.
- **Risque** : migration d'hébergement en production, fenêtre de
  coupure à planifier.
- **Bénéfice** : latence quasi nulle, vraie diffusion serveur→client, plus
  besoin de sondage périodique.
- **Exigence non négociable si cette voie est retenue** : toute
  reconnexion WebSocket doit être **bornée** — 3 tentatives maximum,
  backoff exponentiel, puis **arrêt définitif** avec un log unique. Ne
  jamais reproduire la boucle infinie (`Timer` de 5s sans limite) trouvée
  dans l'ancien `lib/services/websocket_service.dart`, supprimé lors de
  cette intervention.

### B. Sondage HTTP (solution retenue aujourd'hui)

- **Coût** : latence perçue jusqu'à 8 secondes ; charge serveur
  proportionnelle au nombre d'utilisateurs ayant le forum ouvert
  simultanément — à surveiller si l'audience grossit significativement
  (chaque appareil fait un `GET` toutes les 8s, mais seulement pendant que
  l'écran forum est au premier plan).
- **Bénéfice** : zéro dépendance d'hébergement, fonctionne tel quel sur
  PythonAnywhere standard, déjà implémenté et fonctionnel.

**Arbitrage laissé ouvert** : rester en voie B tant que le volume
d'utilisateurs simultanés sur le forum reste modéré ; ré-évaluer la voie A
si une migration d'hébergement est de toute façon envisagée pour d'autres
raisons (le travail de la voie A n'est alors qu'un branchement, pas une
réécriture — `consumers.py`/`routing.py` existent déjà).
