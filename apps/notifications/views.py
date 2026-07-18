from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.core.pagination import PaginatedListMixin
from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer

from drf_spectacular.utils import extend_schema, extend_schema_view
from drf_spectacular.types import OpenApiTypes
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les notifications de l'utilisateur",
        description=(
            "Retourne la liste paginée des notifications de l'utilisateur "
            "connecté (plus récentes d'abord), sérialisées via "
            "`NotificationSerializer` : `id, type, titre, contenu, est_lue, "
            "cree_le, action_url`."
        ),
        tags=["notifications"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: NotificationSerializer},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class NotificationsView(PaginatedListMixin, APIView):
    """
    GET /api/notifications/
    Retourne les notifications de l'utilisateur connecté.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = Notification.objects.filter(utilisateur=request.user).order_by("-cree_le")
        page = self.paginate_queryset(notifications)
        serializer = NotificationSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


@extend_schema_view(
    patch=extend_schema(
        summary="Marquer une notification comme lue",
        description=(
            "Marque comme lue (`est_lue=True`) la notification `id` "
            "appartenant à l'utilisateur connecté. Réponse 200 : "
            "`{est_lue: true}`."
        ),
        tags=["notifications"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class MarquerNotificationLueView(APIView):
    """
    PATCH /api/notifications/<id>/lire/
    Marque une notification comme lue.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        notification = get_object_or_404(Notification, pk=id, utilisateur=request.user)
        notification.est_lue = True
        notification.save()
        return Response({"est_lue": True})


@extend_schema_view(
    post=extend_schema(
        summary="Marquer toutes les notifications comme lues",
        description=(
            "Marque comme lues (`est_lue=True`) toutes les notifications non "
            "lues de l'utilisateur connecté, en une seule opération. Réponse "
            "200 : `{detail: 'Toutes les notifications marquées comme lues'}`."
        ),
        tags=["notifications"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class MarquerToutesNotificationsLuesView(APIView):
    """
    POST /api/notifications/tout-lire/
    Marque toutes les notifications comme lues.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        Notification.objects.filter(utilisateur=request.user, est_lue=False).update(est_lue=True)
        return Response({"detail": "Toutes les notifications marquées comme lues"})


@extend_schema_view(
    get=extend_schema(
        summary="Nombre de notifications non lues",
        description=(
            "Retourne le nombre de notifications non lues de l'utilisateur "
            "connecté, typiquement utilisé pour afficher un badge de "
            "compteur dans l'interface. Réponse 200 : `{non_lues: <int>}`."
        ),
        tags=["notifications"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class NotificationsNonLuesView(APIView):
    """
    GET /api/notifications/non-lues/
    Retourne le nombre de notifications non lues.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(utilisateur=request.user, est_lue=False).count()
        return Response({"non_lues": count})
