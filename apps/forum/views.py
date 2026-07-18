from django.db.models import Count, F
from django.utils.dateparse import parse_datetime

from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiExample,
)
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.core.pagination import PaginatedListMixin
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
)
from apps.forum.models import QuestionForum, ReponseQuestion, LikeReponse
from apps.forum.serializers import (
    ReponseSerializer,
    QuestionForumDetailSerializer,
    QuestionForumListSerializer,
    QuestionForumCreateSerializer,
)


@extend_schema_view(
    get=extend_schema(
        summary="Détail d'une question du forum",
        description=(
            "Retourne une question du forum avec toutes ses réponses (triées de "
            "la plus récente à la plus ancienne) et incrémente son compteur de vues."
        ),
        tags=["forum"],
        responses={200: QuestionForumDetailSerializer},
        examples=[*ERREURS_COURANTES],
    ),
    delete=extend_schema(
        summary="Supprimer une question du forum",
        description="Supprime une question du forum. Seul l'auteur de la question peut la supprimer.",
        tags=["forum"],
        responses={204: None},
        examples=[*ERREURS_ECRITURE],
    ),
)
class DetailQuestionView(APIView):
    """
    GET /api/forum/questions/<pk>/ - Détail d'une question avec ses réponses
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            # Utiliser select_related et prefetch_related pour optimiser
            question = (
                QuestionForum.objects.select_related("auteur__profile")
                .prefetch_related("reponses__auteur__profile", "reponses__likes")
                .annotate(nb_reponses=Count("reponses"))
                .get(pk=pk)
            )
        except QuestionForum.DoesNotExist:
            return Response({"detail": "Question introuvable."}, status=404)

        # Incrémenter les vues de manière atomique
        QuestionForum.objects.filter(pk=pk).update(nb_vues=F("nb_vues") + 1)

        # Forcer le rafraîchissement pour obtenir le nouveau nb_vues
        question.refresh_from_db()

        # Sérialiser
        serializer = QuestionForumDetailSerializer(question, context={"request": request})

        # Vérifier que les réponses sont bien chargées
        data = serializer.data
        if "reponses" in data:
            # Trier les réponses par date (plus récentes en premier)
            data["reponses"] = sorted(
                data["reponses"], key=lambda r: r.get("cree_le", ""), reverse=True
            )

        return Response(data)

    def delete(self, request, pk):
        try:
            question = QuestionForum.objects.get(pk=pk, auteur=request.user)
        except QuestionForum.DoesNotExist:
            return Response({"detail": "Question introuvable ou non autorisée."}, status=404)
        question.delete()
        return Response(status=204)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les questions du forum",
        description=(
            "Liste paginée des questions du forum, triées des plus récentes aux "
            "plus anciennes, avec le nombre de réponses de chacune. Filtrable par "
            "origine (source), par identifiant de leçon/exercice/devoir/cours, "
            "par statut de résolution, et par date de création (`since`)."
        ),
        tags=["forum"],
        parameters=[
            *PARAMS_PAGINATION,
            OpenApiParameter(
                "source",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par origine de la question : 'lecon', 'exercice', 'devoir' ou 'cours'.",
            ),
            OpenApiParameter(
                "lecon_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par identifiant de leçon.",
            ),
            OpenApiParameter(
                "exercice_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par identifiant d'exercice.",
            ),
            OpenApiParameter(
                "devoir_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par identifiant de devoir.",
            ),
            OpenApiParameter(
                "cours_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par identifiant de cours.",
            ),
            OpenApiParameter(
                "resolue",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre sur le statut de résolution ('true' ou 'false').",
            ),
            OpenApiParameter(
                "since",
                OpenApiTypes.DATETIME,
                OpenApiParameter.QUERY,
                required=False,
                description="Ne retourne que les questions créées après cette date/heure.",
            ),
        ],
        responses={200: QuestionForumListSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
    post=extend_schema(
        summary="Créer une question sur le forum",
        description=(
            "Crée une nouvelle question sur le forum, avec possibilité de "
            "joindre une image et/ou un fichier audio (envoi en multipart/form-data). "
            "Peut être rattachée à une leçon, un cours, un exercice ou un devoir "
            "via les champs *_id / *_titre correspondants."
        ),
        tags=["forum"],
        request=QuestionForumCreateSerializer,
        responses={201: QuestionForumListSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class ListeQuestionsView(PaginatedListMixin, APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        qs = QuestionForum.objects.select_related("auteur__profile").all()

        # Filtres
        source = request.query_params.get("source")
        lecon_id = request.query_params.get("lecon_id")
        exercice_id = request.query_params.get("exercice_id")
        devoir_id = request.query_params.get("devoir_id")
        cours_id = request.query_params.get("cours_id")
        resolue = request.query_params.get("resolue")
        since = request.query_params.get("since")

        if source:
            qs = qs.filter(source=source)
        if lecon_id:
            qs = qs.filter(lecon_id=lecon_id)
        if exercice_id:
            qs = qs.filter(exercice_id=exercice_id)
        if devoir_id:
            qs = qs.filter(devoir_id=devoir_id)
        if cours_id:
            qs = qs.filter(cours_id=cours_id)
        if resolue is not None:
            qs = qs.filter(est_resolue=(resolue == "true"))
        if since:
            qs = qs.filter(cree_le__gt=since)

        qs = qs.annotate(nb_reponses=Count("reponses", distinct=True))
        qs = qs.order_by("-cree_le")

        page = self.paginate_queryset(qs)
        serializer = QuestionForumListSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    def post(self, request):
        # ⭐ CRITIQUE : Extraire les données du request.data (qui peut être QueryDict pour multipart)
        data = {}

        # Copier les champs texte
        for key in [
            "contenu",
            "source",
            "lecon_id",
            "lecon_titre",
            "cours_id",
            "cours_titre",
            "exercice_id",
            "exercice_titre",
            "devoir_id",
            "devoir_titre",
        ]:
            if key in request.data:
                data[key] = request.data[key]

        # Gérer les fichiers
        if "image" in request.FILES:
            data["image"] = request.FILES["image"]
        if "audio" in request.FILES:
            data["audio"] = request.FILES["audio"]

        serializer = QuestionForumCreateSerializer(data=data, context={"request": request})

        serializer.is_valid(raise_exception=True)
        question = serializer.save()

        # Recharger avec les annotations
        question = QuestionForum.objects.annotate(nb_reponses=Count("reponses")).get(pk=question.pk)

        return Response(
            QuestionForumListSerializer(question, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


# Sondage incrémental (repli WebSocket) suite à l'abandon du temps réel :
# PythonAnywhere ne supporte pas les WebSockets (voir docs/FORUM_TEMPS_REEL.md).
# `room` est soit un cours_id numérique, soit le littéral "global" (même
# convention que l'ancien yeki/consumers.py, jamais branché).
@extend_schema_view(
    get=extend_schema(
        summary="Sondage incrémental des nouveaux messages du forum",
        description=(
            "Mécanisme de repli au sondage (polling) remplaçant le temps réel "
            "WebSocket, non supporté par l'hébergeur PythonAnywhere (voir "
            "docs/FORUM_TEMPS_REEL.md). Le client interroge périodiquement cet "
            "endpoint en passant le paramètre `since` (date/heure ISO 8601 de la "
            "dernière synchronisation) pour récupérer uniquement les nouvelles "
            "questions et les identifiants des questions ayant reçu de nouvelles "
            "réponses depuis cette date. Sans `since`, retourne l'état complet de "
            "la room. `room` est soit l'identifiant numérique d'un cours, soit le "
            "littéral 'global'. Vue volontairement non paginée (usage en petits "
            "deltas incrémentaux, pas en listing)."
        ),
        tags=["forum"],
        parameters=[
            OpenApiParameter(
                "since",
                OpenApiTypes.DATETIME,
                OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Date/heure ISO 8601 depuis laquelle récupérer les nouveautés. "
                    "Absent = renvoie tout l'historique de la room."
                ),
            ),
        ],
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                name="Nouveautés depuis `since`",
                summary="Réponse 200",
                value={
                    "nouvelles_questions": ["... voir QuestionForumListSerializer ..."],
                    "reponses_recentes_ids": [12, 45],
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                name="Paramètre `since` invalide",
                summary="Réponse 400",
                value={"detail": "Paramètre 'since' invalide (attendu : datetime ISO 8601)."},
                response_only=True,
                status_codes=["400"],
            ),
            *ERREURS_COURANTES,
        ],
    ),
)
class ForumMessagesPollingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room):
        since_raw = request.query_params.get("since")
        since = None
        if since_raw:
            since = parse_datetime(since_raw)
            if since is None:
                return Response(
                    {"detail": "Paramètre 'since' invalide (attendu : datetime ISO 8601)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        questions_qs = QuestionForum.objects.select_related("auteur__profile")
        reponses_qs = ReponseQuestion.objects.all()
        if room == "global":
            questions_qs = questions_qs.filter(cours_id__isnull=True)
            reponses_qs = reponses_qs.filter(question__cours_id__isnull=True)
        else:
            questions_qs = questions_qs.filter(cours_id=room)
            reponses_qs = reponses_qs.filter(question__cours_id=room)

        if since is not None:
            questions_qs = questions_qs.filter(cree_le__gt=since)
            reponses_qs = reponses_qs.filter(cree_le__gt=since)

        questions_qs = questions_qs.annotate(nb_reponses=Count("reponses", distinct=True)).order_by(
            "-cree_le"
        )

        reponses_recentes_ids = list(reponses_qs.values_list("question_id", flat=True).distinct())

        return Response(
            {
                "nouvelles_questions": QuestionForumListSerializer(
                    questions_qs, many=True, context={"request": request}
                ).data,
                "reponses_recentes_ids": reponses_recentes_ids,
            }
        )


@extend_schema_view(
    patch=extend_schema(
        summary="Basculer le statut résolu d'une question",
        description=(
            "Inverse le statut de résolution (`est_resolue`) d'une question du "
            "forum. Réservé à l'auteur de la question."
        ),
        tags=["forum"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                name="Statut basculé",
                summary="Réponse 200",
                value={"est_resolue": True},
                response_only=True,
                status_codes=["200"],
            ),
            *ERREURS_ECRITURE,
        ],
    ),
)
class ResoudreQuestionView(APIView):
    """PATCH /api/forum/questions/<pk>/resoudre/ → marquer comme résolue"""

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            question = QuestionForum.objects.get(pk=pk, auteur=request.user)
        except QuestionForum.DoesNotExist:
            return Response(status=404)
        question.est_resolue = not question.est_resolue
        question.save()
        return Response({"est_resolue": question.est_resolue})


@extend_schema_view(
    post=extend_schema(
        summary="Répondre à une question du forum",
        description=(
            "Ajoute une réponse textuelle à une question existante du forum. "
            'Corps de requête attendu : `{"contenu": "<texte de la réponse>"}` '
            "(pas de serializer d'entrée dédié — le champ est lu directement "
            "depuis `request.data`)."
        ),
        tags=["forum"],
        request=OpenApiTypes.OBJECT,
        responses={201: ReponseSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class RepondreQuestionView(APIView):
    """POST /api/forum/questions/<pk>/repondre/ → ajouter une réponse"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            question = QuestionForum.objects.get(pk=pk)
        except QuestionForum.DoesNotExist:
            return Response({"detail": "Question introuvable."}, status=404)

        contenu = request.data.get("contenu", "").strip()
        if not contenu:
            return Response({"detail": "Le contenu de la réponse est requis."}, status=400)

        reponse = ReponseQuestion.objects.create(
            question=question,
            auteur=request.user,
            contenu=contenu,
            est_solution=False,
        )

        serializer = ReponseSerializer(reponse, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    post=extend_schema(
        summary="Liker / retirer son like sur une réponse",
        description=(
            "Bascule le like de l'utilisateur connecté sur une réponse : ajoute "
            "le like s'il n'existe pas encore, le retire sinon. Retourne le "
            "nouveau nombre total de likes de la réponse."
        ),
        tags=["forum"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                name="Like basculé",
                summary="Réponse 200",
                value={"liked": True, "nb_likes": 4},
                response_only=True,
                status_codes=["200"],
            ),
            *ERREURS_ECRITURE,
        ],
    ),
)
class LikerReponseView(APIView):
    """POST /api/forum/reponses/<pk>/liker/ → liker/unliker une réponse"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            reponse = ReponseQuestion.objects.get(pk=pk)
        except ReponseQuestion.DoesNotExist:
            return Response(status=404)

        like, created = LikeReponse.objects.get_or_create(reponse=reponse, utilisateur=request.user)
        if not created:
            like.delete()
            liked = False
        else:
            liked = True

        return Response({"liked": liked, "nb_likes": reponse.likes.count()})


@extend_schema_view(
    patch=extend_schema(
        summary="Marquer / démarquer une réponse comme solution",
        description=(
            "Bascule le statut solution d'une réponse. Réservé à l'auteur de la "
            "question concernée. Si la réponse devient la solution, la question "
            "est automatiquement marquée comme résolue."
        ),
        tags=["forum"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                name="Statut solution basculé",
                summary="Réponse 200",
                value={"est_solution": True},
                response_only=True,
                status_codes=["200"],
            ),
            *ERREURS_ECRITURE,
        ],
    ),
)
class MarquerSolutionView(APIView):
    """PATCH /api/forum/reponses/<pk>/solution/ → marquer comme solution"""

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            reponse = ReponseQuestion.objects.get(pk=pk)
            # Seul l'auteur de la question ou un enseignant peut marquer comme solution
            if reponse.question.auteur != request.user:
                # Vérifier si l'utilisateur est enseignant (adapter selon ton modèle)
                # Pour l'instant on vérifie juste l'auteur de la question
                return Response(status=403)
        except ReponseQuestion.DoesNotExist:
            return Response(status=404)

        reponse.est_solution = not reponse.est_solution
        reponse.save()

        # Résoudre la question automatiquement si une solution est marquée
        if reponse.est_solution:
            reponse.question.est_resolue = True
            reponse.question.save()

        return Response({"est_solution": reponse.est_solution})


@extend_schema_view(
    get=extend_schema(
        summary="Statistiques globales du forum",
        description=(
            "Retourne des compteurs globaux sur le forum : nombre total de "
            "questions, nombre de questions résolues, et répartition par "
            "origine (leçons, exercices, devoirs)."
        ),
        tags=["forum"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                name="Statistiques du forum",
                summary="Réponse 200",
                value={"total": 120, "resolues": 80, "lecons": 40, "exercices": 50, "devoirs": 30},
                response_only=True,
                status_codes=["200"],
            ),
            *ERREURS_COURANTES,
        ],
    ),
)
class StatsForumView(APIView):
    """GET /api/forum/stats/ → statistiques pour la page forum"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        total = QuestionForum.objects.count()
        resolues = QuestionForum.objects.filter(est_resolue=True).count()
        lecons = QuestionForum.objects.filter(source="lecon").count()
        exercices = QuestionForum.objects.filter(source="exercice").count()
        devoirs = QuestionForum.objects.filter(source="devoir").count()

        return Response(
            {
                "total": total,
                "resolues": resolues,
                "lecons": lecons,
                "exercices": exercices,
                "devoirs": devoirs,
            }
        )


def _nb_apprenants_pour_parcours(nom_parcours: str) -> int:
    """
    Calcule dynamiquement le nombre d'apprenants inscrits dans un parcours.
    Un apprenant est "dans" un parcours si profile.cursus == nom_parcours.
    Beaucoup plus fiable que le compteur nb_apprenants (jamais mis à jour).
    """
    return Profile.objects.filter(
        user_type="apprenant",
        cursus=nom_parcours,
        is_active=True,
    ).count()
