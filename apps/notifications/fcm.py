"""
Envoi des notifications push via Firebase Cloud Messaging (P10.3,
CDC_BACKEND §9.2). Aucune file de tâches (Celery/huey) n'existe dans ce
projet et en installer une est un projet d'infra à part entière hors du
périmètre "code" de ce ticket — l'envoi se fait donc dans un thread démon
(`threading.Thread`), suffisant pour ne jamais bloquer le cycle
requête/réponse (exigence explicite : "jamais dans le cycle de requête,
un envoi FCM lent bloquerait la réponse HTTP de publication d'un devoir").

Configuration requise (voir docs/SECURITE_ROTATION.md) :
- Variable d'environnement `FIREBASE_CREDENTIALS_JSON` : contenu JSON du
  compte de service Firebase (Paramètres → Comptes de service → Générer
  une clé privée) — jamais commité, jamais un fichier versionné.
"""

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

FIREBASE_CREDENTIALS_JSON = os.environ.get("FIREBASE_CREDENTIALS_JSON", "")

_firebase_app = None
_firebase_lock = threading.Lock()


def _app_firebase():
    """Initialise paresseusement l'app firebase_admin (une seule fois par
    processus). Retourne `None` si firebase-admin n'est pas installé ou si
    les credentials ne sont pas configurés — l'envoi push est alors
    silencieusement ignoré (l'in-app reste la source de vérité, jamais
    bloquant)."""
    global _firebase_app

    if _firebase_app is not None:
        return _firebase_app

    if not FIREBASE_CREDENTIALS_JSON:
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        logger.warning("firebase-admin non installé — envoi push ignoré.")
        return None

    with _firebase_lock:
        if _firebase_app is not None:
            return _firebase_app
        try:
            cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
            _firebase_app = firebase_admin.initialize_app(cred)
        except Exception:
            logger.exception("Échec d'initialisation de firebase_admin")
            return None
    return _firebase_app


def _envoyer_push_sync(notification) -> None:
    """Envoie la notification push à TOUS les appareils actifs de
    l'utilisateur — exécuté dans un thread séparé, jamais dans le thread
    de la requête HTTP appelante."""
    from apps.notifications.models import DeviceToken

    app = _app_firebase()
    if app is None:
        return

    try:
        from firebase_admin import messaging
    except ImportError:
        return

    tokens = list(
        DeviceToken.objects.filter(user=notification.utilisateur, actif=True).values_list(
            "token", flat=True
        )
    )
    if not tokens:
        return

    for token in tokens:
        message = messaging.Message(
            notification=messaging.Notification(
                title=notification.titre,
                body=notification.contenu,
            ),
            data={
                "action_route": notification.action_route or "",
                "notification_id": str(notification.id),
                "type": notification.type,
            },
            token=token,
        )
        try:
            messaging.send(message, app=app)
        except Exception as exc:
            # Token invalide (UNREGISTERED ou équivalent) — désactivé
            # automatiquement, JAMAIS supprimé (règle 5, CDC §9.2).
            if "UNREGISTERED" in str(exc) or "NotRegisteredError" in type(exc).__name__:
                DeviceToken.objects.filter(token=token).update(actif=False)
            else:
                logger.exception("Échec envoi push FCM (token=%s...)", token[:12])


def envoyer_push_async(notification) -> None:
    """Point d'entrée public — lance l'envoi dans un thread démon, ne
    bloque jamais l'appelant."""
    threading.Thread(target=_envoyer_push_sync, args=(notification,), daemon=True).start()
