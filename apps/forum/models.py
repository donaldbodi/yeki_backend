from django.db import models
from django.contrib.auth.models import User


# ─────────────────────────────────────────────────────────────────
# QUESTION FORUM
# Peut être liée à une leçon, un exercice ou un devoir
# ─────────────────────────────────────────────────────────────────


class QuestionForum(models.Model):
    SOURCE_CHOICES = [
        ("lecon", "Leçon"),
        ("exercice", "Exercice"),
        ("devoir", "Devoir"),
        ("libre", "Question libre"),
    ]

    auteur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="questions_forum")
    contenu = models.TextField(
        null=True,
        blank=True,
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="libre")
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    # Liens optionnels
    lecon_id = models.IntegerField(null=True, blank=True)
    lecon_titre = models.CharField(max_length=255, blank=True)
    cours_id = models.IntegerField(null=True, blank=True)
    cours_titre = models.CharField(max_length=255, blank=True)
    exercice_id = models.IntegerField(null=True, blank=True)
    exercice_titre = models.CharField(max_length=255, blank=True)
    devoir_id = models.IntegerField(null=True, blank=True)
    devoir_titre = models.CharField(max_length=255, blank=True)

    est_resolue = models.BooleanField(default=False)
    nb_vues = models.IntegerField(default=0)

    # ⚠️ NOUVEAUX CHAMPS ⚠️
    image = models.ImageField(
        upload_to="forum/questions/images/",
        null=True,
        blank=True,
        help_text="Image jointe à la question",
    )
    audio = models.FileField(
        upload_to="forum/questions/audios/",
        null=True,
        blank=True,
        help_text="Fichier audio joint à la question",
    )

    class Meta:
        db_table = "yeki_questionforum"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"[{self.source}] {self.auteur.username} — {self.contenu[:60]}"


# ─────────────────────────────────────────────────────────────────
# RÉPONSE À UNE QUESTION
# ─────────────────────────────────────────────────────────────────


class ReponseQuestion(models.Model):
    question = models.ForeignKey(QuestionForum, on_delete=models.CASCADE, related_name="reponses")
    auteur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reponses_forum")
    contenu = models.TextField()
    cree_le = models.DateTimeField(auto_now_add=True)
    est_solution = models.BooleanField(default=False)

    class Meta:
        db_table = "yeki_reponsequestion"
        ordering = ["cree_le"]

    def __str__(self):
        return f"Réponse de {self.auteur.username} à Q{self.question.id}"


# ─────────────────────────────────────────────────────────────────
# LIKE sur une réponse
# ─────────────────────────────────────────────────────────────────


class LikeReponse(models.Model):
    reponse = models.ForeignKey(ReponseQuestion, on_delete=models.CASCADE, related_name="likes")
    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        db_table = "yeki_likereponse"
        unique_together = ("reponse", "utilisateur")


class ReponseImage(models.Model):
    """Image jointe à une réponse du forum"""

    reponse = models.ForeignKey(ReponseQuestion, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="forum/reponses/images/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "yeki_reponseimage"

    def __str__(self):
        return f"Image de réponse {self.reponse.id}"
