"""
Test P2.2 : ChoixReponse.ordre garantit un ordre déterministe de lecture
(auparavant : ordre non déterministe, cause probable du bug « l'ajout
consécutif de questions avec plus de 2 choix ne fonctionne pas »).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.evaluation.models import ChoixReponse, Devoir, QuestionDevoir


@pytest.mark.django_db
def test_choixreponse_respecte_ordre_a_la_lecture():
    devoir = Devoir.objects.create(
        titre="D", enonce="E", date_limite=timezone.now() + timedelta(days=1)
    )
    question = QuestionDevoir.objects.create(devoir=devoir, enonce="Q", type_question="qcm")

    ChoixReponse.objects.create(question=question, texte="C", ordre=3)
    ChoixReponse.objects.create(question=question, texte="A", ordre=1)
    ChoixReponse.objects.create(question=question, texte="B", ordre=2)

    textes = list(question.choix.all().values_list("texte", flat=True))
    assert textes == ["A", "B", "C"]
