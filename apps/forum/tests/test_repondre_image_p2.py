"""
Régression : `RepondreQuestionView.post()` ignorait `request.FILES`,
perdant silencieusement toute image jointe à une réponse forum
(`ReponseImage` existait déjà comme modèle mais n'était jamais utilisé).
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.forum.models import QuestionForum, ReponseImage


@pytest.fixture
def question(db, user_apprenant_premium):
    return QuestionForum.objects.create(
        auteur=user_apprenant_premium, contenu="Une question", source="libre"
    )


@pytest.mark.django_db
def test_repondre_avec_image_est_persistee(client_apprenant_premium, question):
    image = SimpleUploadedFile("reponse.jpg", b"contenu image", content_type="image/jpeg")
    response = client_apprenant_premium.post(
        f"/api/forum/questions/{question.id}/repondre/",
        {"contenu": "Voici ma réponse", "image": image},
        format="multipart",
    )
    assert response.status_code == 201
    reponse_id = response.data["id"]
    assert ReponseImage.objects.filter(reponse_id=reponse_id).exists()
    assert response.data["image_url"] is not None


@pytest.mark.django_db
def test_repondre_sans_image_image_url_absente(client_apprenant_premium, question):
    response = client_apprenant_premium.post(
        f"/api/forum/questions/{question.id}/repondre/",
        {"contenu": "Réponse sans image"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["image_url"] is None
