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

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.forum.models import LikeReponse, QuestionForum, ReponseImage, ReponseQuestion
from apps.forum.realtime import diffuser
from apps.notifications.models import creer_notification


@receiver(post_save, sender=QuestionForum)
def _diffuser_question(sender, instance, created, **kwargs):
    diffuser(
        "question_creee" if created else "question_modifiee",
        question_id=instance.id,
        cours_id=instance.cours_id,
    )


@receiver(post_delete, sender=QuestionForum)
def _diffuser_question_supprimee(sender, instance, **kwargs):
    diffuser("question_supprimee", question_id=instance.id, cours_id=instance.cours_id)


def _diffuser_reponse(evenement, reponse):
    diffuser(
        evenement,
        question_id=reponse.question_id,
        cours_id=reponse.question.cours_id,
        reponse_id=reponse.id,
    )


@receiver(post_save, sender=ReponseQuestion)
def _diffuser_reponse_enregistree(sender, instance, created, **kwargs):
    _diffuser_reponse("reponse_creee" if created else "reponse_modifiee", instance)


# L'image d'une réponse est créée APRÈS la réponse (RepondreQuestionView) : sans
# ce signal, les clients rechargeraient une réponse encore sans son image.
@receiver(post_save, sender=ReponseImage)
def _diffuser_image_reponse(sender, instance, created, **kwargs):
    if created:
        _diffuser_reponse("reponse_modifiee", instance.reponse)


@receiver(post_save, sender=LikeReponse)
@receiver(post_delete, sender=LikeReponse)
def _diffuser_like(sender, instance, **kwargs):
    # La réponse peut déjà avoir disparu lors d'une suppression en cascade.
    reponses = ReponseQuestion.objects.select_related("question")
    reponse = reponses.filter(pk=instance.reponse_id).first()
    if reponse:
        _diffuser_reponse("like_modifie", reponse)


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
