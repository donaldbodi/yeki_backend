from django.shortcuts import render

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiExample,
)
from drf_spectacular.types import OpenApiTypes

from apps.core.models import HistoriqueActivite, AppVersion
from apps.core.pagination import PaginatedListMixin
from apps.core.serializers import (
    HistoriqueActiviteSerializer,
    AppVersionSerializer,
    AppVersionCreateSerializer,
)
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
)


def landing(request):
    return render(request, "landing-page.html")


@extend_schema_view(
    get=extend_schema(
        summary="Historique d'activité de l'utilisateur connecté",
        description=(
            "Liste paginée des événements d'activité (créations, modifications, "
            "corrections, etc.) enregistrés pour l'utilisateur connecté, du plus "
            "récent au plus ancien. Peut être filtrée par code d'action précis, "
            "par catégorie fonctionnelle (cours, modules, lecons, devoirs, "
            "exercices, olympiades, enseignants, departements, corrections) ou "
            "depuis une date donnée."
        ),
        tags=["core"],
        parameters=[
            *PARAMS_PAGINATION,
            OpenApiParameter(
                "action",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre sur un code d'action exact (ex : 'course_created').",
            ),
            OpenApiParameter(
                "category",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Filtre par catégorie fonctionnelle : cours, modules, lecons, "
                    "devoirs, exercices, olympiades, enseignants, departements, corrections."
                ),
            ),
            OpenApiParameter(
                "depuis",
                OpenApiTypes.DATE,
                OpenApiParameter.QUERY,
                required=False,
                description="Ne retourne que les activités depuis cette date (format AAAA-MM-JJ).",
            ),
        ],
        responses={200: HistoriqueActiviteSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class HistoriqueActiviteView(PaginatedListMixin, APIView):
    permission_classes = [IsAuthenticated]

    CATEGORIES = {
        "cours": ["course_created", "course_modified", "course_deleted"],
        "modules": ["module_created", "module_modified", "module_deleted"],
        "lecons": ["lesson_created", "lesson_modified", "lesson_deleted"],
        "devoirs": ["homework_created", "homework_modified", "homework_graded"],
        "exercices": ["exercise_created", "question_added"],
        "olympiades": ["olympiad_created", "olympiad_closed", "ranking_computed"],
        "enseignants": [
            "teacher_assigned",
            "teacher_changed",
            "secondary_added",
            "secondary_removed",
        ],
        "departements": ["department_created", "cadre_assigned"],
        "corrections": ["submission_graded", "homework_graded"],
    }

    def get(self, request):
        qs = HistoriqueActivite.objects.filter(user=request.user).order_by("-timestamp")

        action_param = request.query_params.get("action")
        if action_param:
            qs = qs.filter(action=action_param)

        category_param = request.query_params.get("category", "").lower()
        if category_param and category_param in self.CATEGORIES:
            from django.db.models import Q

            q = Q()
            for a in self.CATEGORIES[category_param]:
                q |= Q(action=a)
            qs = qs.filter(q)

        depuis_param = request.query_params.get("depuis")
        if depuis_param:
            try:
                from datetime import datetime

                depuis_dt = datetime.strptime(depuis_param, "%Y-%m-%d")
                qs = qs.filter(timestamp__date__gte=depuis_dt.date())
            except ValueError:
                pass

        page = self.paginate_queryset(qs)
        serializer = HistoriqueActiviteSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


@extend_schema_view(
    get=extend_schema(
        summary="Statistiques d'activité de l'utilisateur connecté",
        description=(
            "Retourne des compteurs agrégés sur l'historique d'activité de "
            "l'utilisateur connecté : total, activité de la semaine et du mois "
            "en cours, répartition par catégorie fonctionnelle et date de la "
            "dernière activité enregistrée."
        ),
        tags=["core"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                name="Statistiques",
                summary="Réponse 200",
                value={
                    "total": 42,
                    "cette_semaine": 5,
                    "ce_mois": 12,
                    "categories": {
                        "cours": 3,
                        "modules": 1,
                        "lecons": 2,
                        "devoirs": 4,
                        "exercices": 1,
                        "olympiades": 0,
                        "enseignants": 0,
                        "corrections": 1,
                    },
                    "derniere_activite": "2026-07-16T10:00:00Z",
                },
                response_only=True,
                status_codes=["200"],
            ),
            *ERREURS_COURANTES,
        ],
    ),
)
class HistoriqueStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        total = HistoriqueActivite.objects.filter(user=request.user).count()

        semaine_debut = now - timedelta(days=7)
        cette_semaine = HistoriqueActivite.objects.filter(
            user=request.user, timestamp__gte=semaine_debut
        ).count()

        mois_debut = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ce_mois = HistoriqueActivite.objects.filter(
            user=request.user, timestamp__gte=mois_debut
        ).count()

        category_map = {
            "cours": ["course_created", "course_modified", "course_deleted"],
            "modules": ["module_created", "module_modified", "module_deleted"],
            "lecons": ["lesson_created", "lesson_modified", "lesson_deleted"],
            "devoirs": ["homework_created", "homework_modified", "homework_graded"],
            "exercices": ["exercise_created", "question_added"],
            "olympiades": ["olympiad_created", "olympiad_closed", "ranking_computed"],
            "enseignants": [
                "teacher_assigned",
                "teacher_changed",
                "secondary_added",
                "secondary_removed",
            ],
            "corrections": ["submission_graded", "homework_graded"],
        }
        categories_count = {}
        for cat, actions in category_map.items():
            categories_count[cat] = HistoriqueActivite.objects.filter(
                user=request.user, action__in=actions
            ).count()

        derniere = (
            HistoriqueActivite.objects.filter(user=request.user).order_by("-timestamp").first()
        )

        return Response(
            {
                "total": total,
                "cette_semaine": cette_semaine,
                "ce_mois": ce_mois,
                "categories": categories_count,
                "derniere_activite": derniere.timestamp.isoformat() if derniere else None,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    get=extend_schema(
        summary="Dernière version disponible de l'application",
        description=(
            "Retourne la dernière version active publiée pour une plateforme "
            "donnée (android/ios/web), avec indication (`is_update_available`) si "
            "une mise à jour est disponible par rapport à `current_version`. Si "
            "aucune version n'est enregistrée en base, une version par défaut "
            "(v1.0.0) est renvoyée. Accessible sans authentification (vérification "
            "au démarrage de l'application)."
        ),
        tags=["core"],
        parameters=[
            OpenApiParameter(
                "platform",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Plateforme cible : 'android' (défaut), 'ios' ou 'web'.",
            ),
            OpenApiParameter(
                "current_version",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Code de version actuellement installé, pour calculer is_update_available.",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                name="Version enregistrée",
                summary="Réponse 200 — version trouvée en base",
                value={
                    "id": 3,
                    "platform": "android",
                    "version_code": 12,
                    "version_name": "v1.2.0",
                    "download_url": "https://cdn.yeki.cm/app.apk",
                    "changelog": "Corrections de bugs.",
                    "min_version_code": 10,
                    "force_update": False,
                    "is_active": True,
                    "file_size": 15000000,
                    "release_date": "2026-06-01",
                    "created_at": "2026-06-01T08:00:00Z",
                    "is_update_available": True,
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                name="Version par défaut",
                summary="Réponse 200 — aucune version en base",
                value={
                    "platform": "android",
                    "version_code": 1,
                    "version_name": "v1.0.0",
                    "download_url": "",
                    "changelog": "Version initiale",
                    "min_version_code": 1,
                    "force_update": False,
                    "is_active": True,
                    "is_update_available": False,
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    ),
)
class LatestVersionView(APIView):
    """
    GET /api/latest-version/
    Retourne la dernière version disponible pour une plateforme.

    Paramètres query:
    - platform: 'android' | 'ios' | 'web' (défaut: 'android')
    - current_version: int (optionnel, pour vérifier si une mise à jour est disponible)
    """

    permission_classes = [AllowAny]

    def get(self, request):
        platform = request.query_params.get("platform", "android")
        current_version = request.query_params.get("current_version")

        try:
            # Récupérer la dernière version active
            version = AppVersion.objects.filter(platform=platform, is_active=True).latest(
                "version_code"
            )

            # Si current_version est fourni, vérifier si une mise à jour est nécessaire
            is_update_available = False
            if current_version:
                try:
                    current = int(current_version)
                    is_update_available = version.version_code > current
                except (ValueError, TypeError):
                    is_update_available = True

            data = AppVersionSerializer(version).data
            data["is_update_available"] = is_update_available

            return Response(data, status=status.HTTP_200_OK)

        except AppVersion.DoesNotExist:
            # Version par défaut si rien n'existe
            return Response(
                {
                    "platform": platform,
                    "version_code": 1,
                    "version_name": "v1.0.0",
                    "download_url": "",
                    "changelog": "Version initiale",
                    "min_version_code": 1,
                    "force_update": False,
                    "is_active": True,
                    "is_update_available": False,
                },
                status=status.HTTP_200_OK,
            )


@extend_schema_view(
    post=extend_schema(
        summary="Créer une nouvelle version d'application (admin)",
        description=(
            "Enregistre une nouvelle version pour une plateforme donnée et "
            "désactive automatiquement les anciennes versions actives de la "
            "même plateforme. Réservé aux utilisateurs staff (`is_staff=True`) ; "
            "les autres utilisateurs reçoivent une erreur 403."
        ),
        tags=["core"],
        request=AppVersionCreateSerializer,
        responses={201: AppVersionSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AdminVersionCreateView(APIView):
    """
    POST /api/admin/versions/
    Crée une nouvelle version (réservé admin)
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Vérifier que l'utilisateur est admin
        if not request.user.is_staff:
            return Response(
                {"detail": "Permission refusée. Admin requis."}, status=status.HTTP_403_FORBIDDEN
            )

        serializer = AppVersionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Désactiver les anciennes versions de la même plateforme
        platform = serializer.validated_data["platform"]
        AppVersion.objects.filter(platform=platform, is_active=True).update(is_active=False)

        version = serializer.save()
        return Response(AppVersionSerializer(version).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(
        summary="Lister toutes les versions d'application (admin)",
        description=(
            "Liste paginée de toutes les versions enregistrées, triées par code "
            "de version décroissant. Réservé aux utilisateurs staff "
            "(`is_staff=True`) ; les autres utilisateurs reçoivent une erreur 403."
        ),
        tags=["core"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: AppVersionSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class AdminVersionListView(PaginatedListMixin, APIView):
    """
    GET /api/admin/versions/
    Liste toutes les versions (réservé admin)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response(
                {"detail": "Permission refusée. Admin requis."}, status=status.HTTP_403_FORBIDDEN
            )

        versions = AppVersion.objects.all().order_by("-version_code")
        page = self.paginate_queryset(versions)
        serializer = AppVersionSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


@extend_schema_view(
    get=extend_schema(
        summary="Vérifier la disponibilité d'une mise à jour",
        description=(
            "Compare `current_version` (obligatoire) à la dernière version "
            "active de la plateforme et indique si une mise à jour est "
            "disponible. Accessible sans authentification."
        ),
        tags=["core"],
        parameters=[
            OpenApiParameter(
                "platform",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Plateforme cible : 'android' (défaut), 'ios' ou 'web'.",
            ),
            OpenApiParameter(
                "current_version",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=True,
                description="Code de version actuellement installé.",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                name="Mise à jour disponible",
                summary="Réponse 200 — mise à jour disponible",
                value={
                    "update_available": True,
                    "version": {
                        "id": 3,
                        "platform": "android",
                        "version_code": 12,
                        "version_name": "v1.2.0",
                        "download_url": "https://cdn.yeki.cm/app.apk",
                        "changelog": "Corrections de bugs.",
                        "min_version_code": 10,
                        "force_update": False,
                        "is_active": True,
                    },
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                name="À jour",
                summary="Réponse 200 — déjà à jour",
                value={
                    "update_available": False,
                    "message": "Vous utilisez déjà la dernière version.",
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                name="Paramètre manquant",
                summary="Réponse 400 — current_version absent ou invalide",
                value={"detail": "current_version est requis"},
                response_only=True,
                status_codes=["400"],
            ),
        ],
    ),
)
class CheckUpdateView(APIView):
    """
    GET /api/check-update/
    Vérifie si une mise à jour est disponible pour la version actuelle.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        platform = request.query_params.get("platform", "android")
        current_version = request.query_params.get("current_version")

        if not current_version:
            return Response(
                {"detail": "current_version est requis"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            current = int(current_version)
            version = AppVersion.objects.filter(platform=platform, is_active=True).latest(
                "version_code"
            )

            if version.version_code > current:
                return Response(
                    {
                        "update_available": True,
                        "version": AppVersionSerializer(version).data,
                    },
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {
                        "update_available": False,
                        "message": "Vous utilisez déjà la dernière version.",
                    },
                    status=status.HTTP_200_OK,
                )

        except AppVersion.DoesNotExist:
            return Response(
                {"update_available": False, "message": "Version non trouvée."},
                status=status.HTTP_200_OK,
            )
        except ValueError:
            return Response(
                {"detail": "current_version doit être un entier"},
                status=status.HTTP_400_BAD_REQUEST,
            )
