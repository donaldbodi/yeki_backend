import logging

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from apps.accounts.models import Profile
from apps.accounts.serializers import EnseignantSerializer, EnseignantCadreLightSerializer
from apps.accounts.services import (
    _nom_profil,
    _envoyer_email_desactivation_enseignant,
    _envoyer_email_activation_enseignant,
    _envoyer_email_changement_type,
)
from apps.core.models import enregistrer_activite
from apps.core.pagination import PaginatedListMixin, YekiPageNumberPagination
from apps.formation.models import Parcours, Departement, Cours

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
)

logger = logging.getLogger(__name__)


@extend_schema_view(
    get=extend_schema(
        summary="Lister tous les enseignants avec filtres (admin général)",
        description=(
            "Retourne la liste paginée de tous les profils enseignants "
            "(enseignant, enseignant_principal, enseignant_cadre, enseignant_admin) "
            "avec leurs parcours, départements et cours associés. Réservé au "
            "profil `admin`. Chaque élément contient : id, username, email, nom, "
            "user_type, user_type_label, is_active, date_joined, last_login, bio, "
            "phone, avatar, parcours, departements, cours."
        ),
        tags=["accounts"],
        parameters=[
            *PARAMS_PAGINATION,
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Recherche par nom, email ou username.",
            ),
            OpenApiParameter(
                "user_type",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par type d'enseignant.",
            ),
            OpenApiParameter(
                "parcours_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par parcours.",
            ),
            OpenApiParameter(
                "departement_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par département.",
            ),
            OpenApiParameter(
                "cours_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par cours.",
            ),
            OpenApiParameter(
                "is_active",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description='Filtre par état d\'activation ("true"/"false").',
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class AdminGeneralEnseignantsListView(PaginatedListMixin, APIView):
    """
    GET /api/admin-general/enseignants/
    Retourne la liste complète des enseignants avec filtres.

    Query params:
    - search: recherche par nom, email, username
    - user_type: filtre par type d'enseignant
    - parcours_id: filtre par parcours
    - departement_id: filtre par département
    - cours_id: filtre par cours
    - is_active: true/false
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "admin":
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Base queryset - tous les enseignants
        enseignants = (
            Profile.objects.filter(
                user_type__in=[
                    "enseignant",
                    "enseignant_principal",
                    "enseignant_cadre",
                    "enseignant_admin",
                ]
            )
            .select_related("user")
            .order_by("-user__date_joined")
        )

        # ── Filtres ──────────────────────────────────────────────
        search = request.query_params.get("search", "").strip()
        if search:
            enseignants = enseignants.filter(
                Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__username__icontains=search)
                | Q(user__email__icontains=search)
            )

        user_type = request.query_params.get("user_type", "")
        if user_type and user_type in [
            "enseignant",
            "enseignant_principal",
            "enseignant_cadre",
            "enseignant_admin",
        ]:
            enseignants = enseignants.filter(user_type=user_type)

        is_active = request.query_params.get("is_active")
        if is_active is not None:
            if is_active.lower() == "true":
                enseignants = enseignants.filter(is_active=True)
            elif is_active.lower() == "false":
                enseignants = enseignants.filter(is_active=False)

        # Filtres par parcours, département, cours
        parcours_id = request.query_params.get("parcours_id")
        if parcours_id:
            enseignants = enseignants.filter(
                Q(parcours_admin__id=parcours_id)
                | Q(departements_cadre__parcours__id=parcours_id)
                | Q(cours_principal__departement__parcours__id=parcours_id)
                | Q(cours_secondaires__departement__parcours__id=parcours_id)
            ).distinct()

        departement_id = request.query_params.get("departement_id")
        if departement_id:
            enseignants = enseignants.filter(
                Q(departements_cadre__id=departement_id)
                | Q(cours_principal__departement__id=departement_id)
                | Q(cours_secondaires__departement__id=departement_id)
            ).distinct()

        cours_id = request.query_params.get("cours_id")
        if cours_id:
            enseignants = enseignants.filter(
                Q(cours_principal__id=cours_id) | Q(cours_secondaires__id=cours_id)
            ).distinct()

        # ── Construction de la réponse ──────────────────────────
        page = self.paginate_queryset(enseignants)
        data = []
        for e in page:
            # Récupérer les parcours, départements, cours de l'enseignant
            parcours_list = []
            departements_list = []
            cours_list = []

            # Parcours où il est admin
            for p in Parcours.objects.filter(admin=e):
                parcours_list.append({"id": p.id, "nom": p.nom})

            # Départements où il est cadre
            for d in Departement.objects.filter(cadre=e):
                departements_list.append({"id": d.id, "nom": d.nom})
                if d.parcours:
                    parcours_list.append({"id": d.parcours.id, "nom": d.parcours.nom})

            # Cours où il est principal
            for c in Cours.objects.filter(enseignant_principal=e):
                cours_list.append({"id": c.id, "titre": c.titre, "niveau": c.niveau})
                if c.departement:
                    departements_list.append({"id": c.departement.id, "nom": c.departement.nom})
                    if c.departement.parcours:
                        parcours_list.append(
                            {"id": c.departement.parcours.id, "nom": c.departement.parcours.nom}
                        )

            # Cours où il est secondaire
            for c in e.cours_secondaires.all():
                cours_list.append({"id": c.id, "titre": c.titre, "niveau": c.niveau})
                if c.departement:
                    departements_list.append({"id": c.departement.id, "nom": c.departement.nom})
                    if c.departement.parcours:
                        parcours_list.append(
                            {"id": c.departement.parcours.id, "nom": c.departement.parcours.nom}
                        )

            # Éliminer les doublons
            parcours_unique = {p["id"]: p for p in parcours_list}.values()
            departements_unique = {d["id"]: d for d in departements_list}.values()
            cours_unique = {c["id"]: c for c in cours_list}.values()

            data.append(
                {
                    "id": e.id,
                    "username": e.user.username,
                    "email": e.user.email,
                    "nom": _nom_profil(e),
                    "user_type": e.user_type,
                    "user_type_label": dict(Profile.USER_TYPES).get(e.user_type, e.user_type),
                    "is_active": e.is_active,
                    "date_joined": e.user.date_joined.isoformat(),
                    "last_login": e.user.last_login.isoformat() if e.user.last_login else None,
                    "bio": e.bio or "",
                    "phone": e.phone or "",
                    "avatar": request.build_absolute_uri(e.avatar.url) if e.avatar else None,
                    "parcours": list(parcours_unique),
                    "departements": list(departements_unique),
                    "cours": list(cours_unique),
                }
            )

        return self.get_paginated_response(data)


@extend_schema_view(
    post=extend_schema(
        summary="Désactiver un compte enseignant",
        description=(
            "Désactive le compte d'un enseignant (`is_active=False`) et lui envoie "
            "un email de notification (l'échec d'envoi n'annule pas la désactivation). "
            "Réservé au profil `admin`. Renvoie 400 si l'utilisateur n'est pas un "
            "enseignant ou si son compte est déjà désactivé."
        ),
        tags=["accounts"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AdminGeneralDesactiverEnseignantView(APIView):
    """
    Désactive un compte enseignant (is_active=False).
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, profile_id):
        try:
            profile_admin = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile_admin.user_type != "admin":
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN,
            )

        enseignant = get_object_or_404(Profile, pk=profile_id)

        if enseignant.user_type not in [
            "enseignant",
            "enseignant_principal",
            "enseignant_cadre",
            "enseignant_admin",
        ]:
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not enseignant.is_active:
            return Response(
                {"detail": "Ce compte est déjà désactivé."}, status=status.HTTP_400_BAD_REQUEST
            )

        enseignant.is_active = False
        enseignant.save(update_fields=["is_active"])

        # Envoyer un email de notification
        try:
            _envoyer_email_desactivation_enseignant(enseignant)
        except Exception:
            # Volontairement large : l'envoi d'email peut échouer pour de
            # nombreuses raisons (SMTP, réseau...) qui ne doivent jamais
            # bloquer la désactivation elle-même déjà appliquée en base.
            logger.exception("Erreur envoi email désactivation enseignant")

        enregistrer_activite(
            user=request.user,
            action="teacher_deactivated",
            description=f"Compte enseignant « {_nom_profil(enseignant)} » désactivé",
            data={
                "enseignant_id": enseignant.id,
                "enseignant_nom": _nom_profil(enseignant),
                "enseignant_email": enseignant.user.email,
                "user_type": enseignant.user_type,
            },
            objet_id=enseignant.id,
            objet_type="Profile",
        )

        return Response(
            {
                "detail": "Compte enseignant désactivé avec succès.",
                "enseignant_id": enseignant.id,
                "nom": _nom_profil(enseignant),
                "is_active": False,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    get=extend_schema(
        summary="Lister les enseignants en attente d'activation",
        description=(
            "Retourne la liste paginée des profils enseignants (tous types "
            "confondus) dont le compte est en attente d'activation "
            "(`is_active=False`). Réservé au profil `admin`. Chaque élément "
            "contient : id, username, email, nom, user_type, date_joined, bio, phone."
        ),
        tags=["accounts"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class AdminGeneralEnseignantsAttenteView(PaginatedListMixin, APIView):
    """
    Retourne la liste des enseignants (tous types confondus) dont le compte
    est en attente d'activation (is_active=False).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "admin":
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Récupérer tous les profils enseignants inactifs (is_active=False)
        enseignants = (
            Profile.objects.filter(
                user_type__in=[
                    "enseignant",
                    "enseignant_principal",
                    "enseignant_cadre",
                    "enseignant_admin",
                ],
                is_active=False,
            )
            .select_related("user")
            .order_by("-user__date_joined")
        )

        page = self.paginate_queryset(enseignants)
        data = []
        for e in page:
            data.append(
                {
                    "id": e.id,
                    "username": e.user.username,
                    "email": e.user.email,
                    "nom": f"{e.user.first_name} {e.user.last_name}".strip() or e.user.username,
                    "user_type": e.user_type,
                    "date_joined": e.user.date_joined.isoformat(),
                    "bio": e.bio or "",
                    "phone": e.phone or "",
                }
            )

        return self.get_paginated_response(data)


@extend_schema_view(
    post=extend_schema(
        summary="Activer un compte enseignant",
        description=(
            "Active le compte d'un enseignant (`is_active=True`) et lui envoie un "
            "email de confirmation avec ses identifiants. Réservé au profil "
            "`admin`. Renvoie 400 si l'utilisateur n'est pas un enseignant ou si "
            "son compte est déjà actif."
        ),
        tags=["accounts"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AdminGeneralActiverEnseignantView(APIView):
    """
    Active un compte enseignant (is_active=True) et envoie un email de confirmation.
    L'enseignant reçoit un email avec son mot de passe (si disponible) et ses identifiants.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, profile_id):
        try:
            profile_admin = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile_admin.user_type != "admin":
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN,
            )

        enseignant = get_object_or_404(Profile, pk=profile_id)

        # Vérifier que c'est bien un enseignant
        if enseignant.user_type not in [
            "enseignant",
            "enseignant_principal",
            "enseignant_cadre",
            "enseignant_admin",
        ]:
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if enseignant.is_active:
            return Response(
                {"detail": "Ce compte est déjà actif."}, status=status.HTTP_400_BAD_REQUEST
            )

        # Activer le compte
        enseignant.is_active = True
        enseignant.save(update_fields=["is_active"])

        # Envoyer l'email de confirmation
        try:
            _envoyer_email_activation_enseignant(enseignant)
        except Exception:
            # Volontairement large (idem ci-dessus) : ne jamais bloquer
            # l'activation, déjà appliquée en base, pour un aléa d'envoi.
            logger.exception("Erreur envoi email activation enseignant")

        # Enregistrer dans l'historique
        enregistrer_activite(
            user=request.user,
            action="teacher_activated",
            description=f"Compte enseignant « {_nom_profil(enseignant)} » activé ({enseignant.user_type})",
            data={
                "enseignant_id": enseignant.id,
                "enseignant_nom": _nom_profil(enseignant),
                "enseignant_email": enseignant.user.email,
                "user_type": enseignant.user_type,
            },
            objet_id=enseignant.id,
            objet_type="Profile",
        )

        return Response(
            {
                "detail": "Compte enseignant activé avec succès. Un email de confirmation a été envoyé.",
                "enseignant_id": enseignant.id,
                "nom": _nom_profil(enseignant),
                "email": enseignant.user.email,
                "user_type": enseignant.user_type,
            },
            status=status.HTTP_200_OK,
        )


# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Changer le type d'un enseignant
# PATCH /api/admin-general/enseignants/<profile_id>/changer-type/
# Body: { "user_type": "enseignant_principal" }
#
# TODO(correction): cette vue était définie DEUX FOIS dans yeki/views.py
# (L356-443 et L745-822 avant l'éclatement) — la première définition était
# du code mort (écrasée silencieusement par la seconde dans le namespace du
# module, jamais exécutée). Seule cette seconde version (routée, réellement
# active) est conservée ici. La version morte supprimée contenait un
# garde-fou anti no-op (refus si ancien_type == nouveau_type) et envoyait un
# email de notification via _envoyer_email_changement_type_enseignant
# (conservée dans services.py) — ces deux comportements sont PERDUS par
# rapport à la version morte. Décision produit non tranchée ici : à
# réintégrer ou non dans une tâche de correction ultérieure (voir
# docs/AUDIT_BACKEND.md §2.1 et docs/SPLIT_VIEWS.md).
# ───────────────────────────────────────────────────────────────────────────
@extend_schema_view(
    patch=extend_schema(
        summary="Changer le type d'un enseignant",
        description=(
            "Change le type d'un enseignant (ex : enseignant → "
            'enseignant_principal). Corps attendu : `{"user_type": '
            '"enseignant_principal"}`. Le compte doit d\'abord être actif '
            "(`is_active=True`). Réservé au profil `admin`."
        ),
        tags=["accounts"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AdminGeneralChangerTypeEnseignantView(APIView):
    """
    Change le type d'un enseignant (enseignant → enseignant_principal, etc.)
    Valide que le compte est actif (is_active=True).
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, profile_id):
        try:
            profile_admin = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile_admin.user_type != "admin":
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN,
            )

        enseignant = get_object_or_404(Profile, pk=profile_id)

        # Vérifier que c'est bien un enseignant
        if enseignant.user_type not in [
            "enseignant",
            "enseignant_principal",
            "enseignant_cadre",
            "enseignant_admin",
        ]:
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not enseignant.is_active:
            return Response(
                {"detail": "Le compte enseignant doit d'abord être activé."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        nouveau_type = request.data.get("user_type", "").strip()
        types_valides = [
            "enseignant",
            "enseignant_principal",
            "enseignant_cadre",
            "enseignant_admin",
        ]

        if nouveau_type not in types_valides:
            return Response(
                {"detail": f"Type invalide. Valeurs: {types_valides}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ancien_type = enseignant.user_type
        enseignant.user_type = nouveau_type
        enseignant.save(update_fields=["user_type"])

        # Enregistrer dans l'historique
        enregistrer_activite(
            user=request.user,
            action="teacher_type_changed",
            description=f"Type enseignant modifié : {ancien_type} → {nouveau_type} pour {_nom_profil(enseignant)}",
            data={
                "enseignant_id": enseignant.id,
                "enseignant_nom": _nom_profil(enseignant),
                "ancien_type": ancien_type,
                "nouveau_type": nouveau_type,
                "email": enseignant.user.email,
            },
            objet_id=enseignant.id,
            objet_type="Profile",
        )

        return Response(
            {
                "detail": "Type enseignant modifié avec succès.",
                "enseignant_id": enseignant.id,
                "nom": _nom_profil(enseignant),
                "ancien_type": ancien_type,
                "nouveau_type": nouveau_type,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    summary="Lister les enseignants cadres",
    description="Retourne la liste paginée des profils de type `enseignant_cadre`.",
    tags=["accounts"],
    parameters=[*PARAMS_PAGINATION],
    responses={200: EnseignantCadreLightSerializer(many=True)},
    examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def liste_enseignants_cadres(request):
    qs = Profile.objects.filter(user_type="enseignant_cadre")
    paginator = YekiPageNumberPagination()
    page = paginator.paginate_queryset(qs, request)
    data = EnseignantCadreLightSerializer(page, many=True).data
    return paginator.get_paginated_response(data)


@extend_schema(
    summary="Lister les enseignants secondaires",
    description="Retourne la liste paginée des profils de type `enseignant` (enseignants secondaires).",
    tags=["accounts"],
    parameters=[*PARAMS_PAGINATION],
    responses={200: EnseignantSerializer(many=True)},
    examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def liste_enseignants_secondaires(request):
    qs = Profile.objects.filter(user_type="enseignant")
    paginator = YekiPageNumberPagination()
    page = paginator.paginate_queryset(qs, request)
    data = EnseignantSerializer(page, many=True).data
    return paginator.get_paginated_response(data)


@extend_schema(
    summary="Lister tous les enseignants (tous types)",
    description=(
        "Retourne la liste paginée de tous les profils enseignants "
        "(enseignant, enseignant_principal, enseignant_admin, enseignant_cadre)."
    ),
    tags=["accounts"],
    parameters=[*PARAMS_PAGINATION],
    responses={200: EnseignantSerializer(many=True)},
    examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def liste_enseignants(request):
    qs = Profile.objects.filter(
        user_type__in=["enseignant", "enseignant_principal", "enseignant_admin", "enseignant_cadre"]
    )
    paginator = YekiPageNumberPagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = EnseignantSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


@extend_schema_view(
    patch=extend_schema(
        summary="Modifier le type et/ou l'activation d'un enseignant",
        description=(
            "Modifie le `user_type` et/ou l'état `is_active` d'un enseignant en "
            "une seule requête. Corps attendu (au moins un champ) : "
            '`{"user_type": "enseignant_principal", "is_active": true}`. '
            "Envoie un email de confirmation en cas de changement de type ou "
            "d'activation. Réservé au profil `admin`."
        ),
        tags=["accounts"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AdminGeneralModifierEnseignantView(APIView):
    """
    PATCH /api/admin-general/enseignants/<profile_id>/modifier/
    Body: { "user_type": "enseignant_principal", "is_active": true/false }

    Modifie le type et/ou l'état d'activation d'un enseignant.
    Envoie un email de confirmation en cas de changement de type.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, profile_id):
        try:
            profile_admin = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile_admin.user_type != "admin":
            return Response({"detail": "Accès réservé à l'administrateur général."}, status=403)

        enseignant = get_object_or_404(Profile, pk=profile_id)

        # Vérifier que c'est bien un enseignant
        if enseignant.user_type not in [
            "enseignant",
            "enseignant_principal",
            "enseignant_cadre",
            "enseignant_admin",
        ]:
            return Response({"detail": "Cet utilisateur n'est pas un enseignant."}, status=400)

        data = request.data
        ancien_type = enseignant.user_type
        ancien_actif = enseignant.is_active
        modifications = []

        # ── Changer le type ─────────────────────────────────────
        if "user_type" in data:
            nouveau_type = data["user_type"].strip()
            types_valides = [
                "enseignant",
                "enseignant_principal",
                "enseignant_cadre",
                "enseignant_admin",
            ]
            if nouveau_type not in types_valides:
                return Response({"detail": f"Type invalide. Valeurs: {types_valides}"}, status=400)
            if nouveau_type != ancien_type:
                enseignant.user_type = nouveau_type
                modifications.append(f"Type: {ancien_type} → {nouveau_type}")

                # Envoyer un email de confirmation pour le changement de type
                try:
                    _envoyer_email_changement_type(enseignant, ancien_type, nouveau_type)
                except Exception:
                    # Volontairement large (idem ci-dessus).
                    logger.exception("Erreur envoi email changement type enseignant")

        # ── Activer/Désactiver ─────────────────────────────────
        if "is_active" in data:
            nouvel_actif = bool(data["is_active"])
            if nouvel_actif != ancien_actif:
                enseignant.is_active = nouvel_actif
                if nouvel_actif:
                    modifications.append("Compte activé")
                    try:
                        _envoyer_email_activation_enseignant(enseignant)
                    except Exception:
                        # Volontairement large (idem ci-dessus).
                        logger.exception("Erreur envoi email activation enseignant")
                else:
                    modifications.append("Compte désactivé")

        if not modifications:
            return Response({"detail": "Aucune modification spécifiée."}, status=400)

        enseignant.save(update_fields=["user_type", "is_active"])

        # Enregistrer dans l'historique
        enregistrer_activite(
            user=request.user,
            action="teacher_modified",
            description=f"Enseignant {_nom_profil(enseignant)} modifié : {', '.join(modifications)}",
            data={
                "enseignant_id": enseignant.id,
                "enseignant_nom": _nom_profil(enseignant),
                "modifications": modifications,
                "ancien_type": ancien_type,
                "nouveau_type": enseignant.user_type,
                "ancien_actif": ancien_actif,
                "nouveau_actif": enseignant.is_active,
            },
            objet_id=enseignant.id,
            objet_type="Profile",
        )

        return Response(
            {
                "detail": "Enseignant modifié avec succès.",
                "enseignant_id": enseignant.id,
                "nom": _nom_profil(enseignant),
                "user_type": enseignant.user_type,
                "is_active": enseignant.is_active,
                "modifications": modifications,
            },
            status=200,
        )


@extend_schema_view(
    get=extend_schema(
        summary="Rechercher des enseignants (filtres avancés)",
        description=(
            "Recherche paginée des profils enseignants par texte libre, type, "
            "état d'activation, parcours, département, cours et plage de dates "
            "de création. Réservé au profil `admin`. Chaque élément contient : "
            "id, username, email, nom, user_type, is_active, date_joined, bio, "
            "phone, avatar."
        ),
        tags=["accounts"],
        parameters=[
            *PARAMS_PAGINATION,
            OpenApiParameter(
                "q",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Texte de recherche (nom, email, username, bio).",
            ),
            OpenApiParameter(
                "user_type",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par type d'enseignant.",
            ),
            OpenApiParameter(
                "is_active",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description='Filtre par état d\'activation ("true"/"false").',
            ),
            OpenApiParameter(
                "parcours_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par parcours (admin du parcours).",
            ),
            OpenApiParameter(
                "departement_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par département (cadre).",
            ),
            OpenApiParameter(
                "cours_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par cours (enseignant principal ou secondaire).",
            ),
            OpenApiParameter(
                "date_from",
                OpenApiTypes.DATE,
                OpenApiParameter.QUERY,
                required=False,
                description="Date de création minimale (YYYY-MM-DD).",
            ),
            OpenApiParameter(
                "date_to",
                OpenApiTypes.DATE,
                OpenApiParameter.QUERY,
                required=False,
                description="Date de création maximale (YYYY-MM-DD).",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class AdminGeneralSearchEnseignantsView(PaginatedListMixin, APIView):
    """
    GET /api/admin-general/enseignants/search/
    Paramètres query :
    - q: texte de recherche (nom, email, username)
    - user_type: enseignant, enseignant_principal, enseignant_cadre, enseignant_admin
    - is_active: true/false
    - parcours_id: filtrer par parcours (admin du parcours)
    - departement_id: filtrer par département (cadre)
    - cours_id: filtrer par cours (enseignant principal)
    - date_from, date_to: filtrer par date de création

    Retourne la liste des enseignants filtrés.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "admin":
            return Response({"detail": "Accès réservé à l'administrateur général."}, status=403)

        # Base queryset
        qs = (
            Profile.objects.filter(
                user_type__in=[
                    "enseignant",
                    "enseignant_principal",
                    "enseignant_cadre",
                    "enseignant_admin",
                ]
            )
            .select_related("user")
            .order_by("-user__date_joined")
        )

        # ── Filtres ──────────────────────────────────────────────
        q = request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(user__username__icontains=q)
                | Q(user__email__icontains=q)
                | Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
                | Q(bio__icontains=q)
            )

        user_type = request.query_params.get("user_type", "").strip()
        if user_type and user_type in [
            "enseignant",
            "enseignant_principal",
            "enseignant_cadre",
            "enseignant_admin",
        ]:
            qs = qs.filter(user_type=user_type)

        is_active = request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")

        parcours_id = request.query_params.get("parcours_id")
        if parcours_id:
            qs = qs.filter(parcours_admin__id=parcours_id)

        departement_id = request.query_params.get("departement_id")
        if departement_id:
            qs = qs.filter(departements_cadre__id=departement_id)

        cours_id = request.query_params.get("cours_id")
        if cours_id:
            qs = qs.filter(Q(cours_principal__id=cours_id) | Q(cours_secondaires__id=cours_id))

        date_from = request.query_params.get("date_from")
        if date_from:
            try:
                from datetime import datetime

                qs = qs.filter(
                    user__date_joined__date__gte=datetime.strptime(date_from, "%Y-%m-%d").date()
                )
            except ValueError:
                pass

        date_to = request.query_params.get("date_to")
        if date_to:
            try:
                from datetime import datetime

                qs = qs.filter(
                    user__date_joined__date__lte=datetime.strptime(date_to, "%Y-%m-%d").date()
                )
            except ValueError:
                pass

        page = self.paginate_queryset(qs)

        data = []
        for e in page:
            data.append(
                {
                    "id": e.id,
                    "username": e.user.username,
                    "email": e.user.email,
                    "nom": _nom_profil(e),
                    "user_type": e.user_type,
                    "is_active": e.is_active,
                    "date_joined": e.user.date_joined.isoformat(),
                    "bio": e.bio or "",
                    "phone": e.phone or "",
                    "avatar": request.build_absolute_uri(e.avatar.url) if e.avatar else None,
                }
            )

        return self.get_paginated_response(data)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les enseignants actifs par rôle",
        description=(
            "Retourne la liste paginée des profils enseignants actifs "
            "(`is_active=True`) pour un rôle donné, via le paramètre `role` "
            "mappé sur le `user_type` correspondant (admin → enseignant_admin, "
            "cadre → enseignant_cadre, principal → enseignant_principal, "
            "enseignant → enseignant)."
        ),
        tags=["accounts"],
        parameters=[
            *PARAMS_PAGINATION,
            OpenApiParameter(
                "role",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=True,
                description="Rôle recherché : admin, cadre, principal ou enseignant.",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class ListeEnseignantsParRoleView(PaginatedListMixin, APIView):
    permission_classes = [IsAuthenticated]

    ROLE_MAP = {
        "admin": "enseignant_admin",
        "cadre": "enseignant_cadre",
        "principal": "enseignant_principal",
        "enseignant": "enseignant",
    }

    def get(self, request):
        role_param = request.query_params.get("role", "")
        user_type = self.ROLE_MAP.get(role_param)

        if not user_type:
            return Response(
                {"detail": f"Rôle invalide. Valeurs acceptées : {list(self.ROLE_MAP.keys())}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profiles = Profile.objects.filter(user_type=user_type, is_active=True).select_related(
            "user"
        )

        page = self.paginate_queryset(profiles)
        data = [
            {
                "id": p.id,
                "nom": f"{p.user.first_name} {p.user.last_name}".strip() or p.user.username,
                "username": p.user.username,
                "email": p.user.email,
                "user_type": p.user_type,
            }
            for p in page
        ]
        return self.get_paginated_response(data)


@extend_schema(
    summary="Lister les enseignants principaux",
    description="Retourne la liste paginée des profils de type `enseignant_principal`.",
    tags=["accounts"],
    parameters=[*PARAMS_PAGINATION],
    responses={200: EnseignantSerializer(many=True)},
    examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def liste_enseignants_principaux(request):
    qs = Profile.objects.filter(user_type="enseignant_principal")
    paginator = YekiPageNumberPagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = EnseignantSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)
