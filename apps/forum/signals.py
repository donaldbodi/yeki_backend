"""
Signaux forum (P10.3) — déclencheur du catalogue CDC_BACKEND §9.1.1
« Réponse à ma question au forum ». Nouveau : aucun appel manuel
n'existait auparavant (apps/forum/views.py ne créait aucune notification).

« Mention au forum » (même catalogue) est VOLONTAIREMENT NON IMPLÉMENTÉE :
aucun mécanisme de détection de mention (`@username`) n'existe dans le
contenu des réponses/questions — l'ajouter exigerait un parsing de texte
et une résolution de username non demandés ailleurs dans le code, une
extension de périmètre non couverte par ce ticket.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.forum.models import ReponseQuestion
from apps.notifications.models import creer_notification


@receiver(post_save, sender=ReponseQuestion)
def _notifier_reponse_question(sender, instance, created, **kwargs):
    if not created:
        return
    question = instance.question
    # Ne pas se notifier soi-même (l'auteur répond à sa propre question).
    if question.auteur_id == instance.auteur_id:
        return
    creer_notification(
        utilisateur=question.auteur,
        type_notif="forum",
        titre="Nouvelle réponse à votre question",
        contenu=f"{instance.auteur.username} a répondu à votre question sur le forum.",
        objet_id=question.id,
        objet_type="QuestionForum",
        # Chemin réel confirmé (route_paths.dart) : `/forum/questions/:id`
        # (pluriel) — pas `/forum/question/<id>` (singulier) tel qu'écrit
        # dans le catalogue CDC, qui ne correspond à aucune route go_router.
        action_route=f"/forum/questions/{question.id}",
    )
