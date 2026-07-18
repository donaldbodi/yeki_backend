from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Sum
from django.shortcuts import get_object_or_404

from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from drf_spectacular.utils import extend_schema, extend_schema_view
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.accounts.services import _get_profile
from apps.core.models import enregistrer_activite
from apps.core.pagination import PaginatedListMixin, YekiPageNumberPagination
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
)
from apps.formation.models import Parcours, Departement, Cours
from apps.formation.serializers import ParcoursSerializer


class AdminGeneralModifierParcoursView(APIView):
    """
    Modifie un parcours (nom, description, type_parcours).
    Réservé à l'administrateur général.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Modifier un parcours (admin général)",
        description="Modifie le nom, la description et/ou le type d'un parcours existant.",
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    @transaction.atomic
    def patch(self, request, parcours_id):
        try:
            profile_admin = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile_admin.user_type != "admin":
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN,
            )

        parcours = get_object_or_404(Parcours, pk=parcours_id)

        data = request.data
        updates = {}
        message = []

        # Nom
        if "nom" in data:
            nouveau_nom = data["nom"].strip()
            if not nouveau_nom:
                return Response(
                    {"detail": "Le nom ne peut pas être vide."}, status=status.HTTP_400_BAD_REQUEST
                )
            if nouveau_nom != parcours.nom:
                updates["nom"] = nouveau_nom
                message.append(f"Nom: {parcours.nom} → {nouveau_nom}")

        # Description
        if "description" in data:
            nouvelle_desc = data["description"].strip()
            if nouvelle_desc != parcours.description:
                updates["description"] = nouvelle_desc
                message.append("Description modifiée")

        # Type de parcours
        if "type_parcours" in data:
            nouveau_type = data["type_parcours"].strip()
            types_valides = ["cursus", "prepa", "formation", "autre"]
            if nouveau_type not in types_valides:
                return Response(
                    {"detail": f"Type de parcours invalide. Valeurs: {types_valides}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if nouveau_type != parcours.type_parcours:
                updates["type_parcours"] = nouveau_type
                message.append(f"Type: {parcours.type_parcours} → {nouveau_type}")

        if not updates:
            return Response(
                {"detail": "Aucune modification spécifiée."}, status=status.HTTP_400_BAD_REQUEST
            )

        # Appliquer les modifications
        for key, value in updates.items():
            setattr(parcours, key, value)
        parcours.save()

        # Enregistrer dans l'historique
        enregistrer_activite(
            user=request.user,
            action="parcours_modified",
            description=f"Parcours « {parcours.nom} » modifié",
            data={
                "parcours_id": parcours.id,
                "parcours_nom": parcours.nom,
                "modifications": message,
            },
            objet_id=parcours.id,
            objet_type="Parcours",
        )

        return Response(
            {
                "detail": "Parcours modifié avec succès.",
                "parcours": {
                    "id": parcours.id,
                    "nom": parcours.nom,
                    "description": parcours.description,
                    "type_parcours": parcours.type_parcours,
                },
                "modifications": message,
            },
            status=status.HTTP_200_OK,
        )


class CreerParcoursView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Créer un parcours (admin général)",
        description="Crée un nouveau parcours de haut niveau (cursus, prépa concours, formations, etc.).",
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    def post(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "admin":
            return Response(
                {"detail": "Acces reserve a l'administrateur general."},
                status=status.HTTP_403_FORBIDDEN,
            )

        nom = request.data.get("nom", "").strip()
        if not nom:
            return Response(
                {"detail": "Le nom du parcours est obligatoire."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        type_parcours = request.data.get("type_parcours", "autre")
        valid_types = ["cursus", "prepa", "formation", "autre"]
        if type_parcours not in valid_types:
            type_parcours = "autre"

        parcours = Parcours.objects.create(
            nom=nom,
            type_parcours=type_parcours,
            description=request.data.get("description", "").strip(),
        )
        return Response(
            {
                "id": parcours.id,
                "nom": parcours.nom,
                "type_parcours": parcours.type_parcours,
                "description": parcours.description,
            },
            status=status.HTTP_201_CREATED,
        )


class NommerAdminParcoursView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Nommer l'enseignant admin d'un parcours",
        description="Assigne un enseignant_admin comme responsable d'un parcours.",
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    def patch(self, request, parcours_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "admin":
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN,
            )

        parcours = get_object_or_404(Parcours, pk=parcours_id)

        enseignant_id = request.data.get("enseignant_admin_id")
        if not enseignant_id:
            return Response(
                {"detail": "enseignant_admin_id est requis."}, status=status.HTTP_400_BAD_REQUEST
            )

        enseignant = get_object_or_404(Profile, pk=enseignant_id)
        if enseignant.user_type != "enseignant_admin":
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant administrateur."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parcours.admin = enseignant
        parcours.save()
        return Response(
            {"detail": "Enseignant administrateur mis à jour avec succès."},
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    get=extend_schema(
        summary="Lister/créer des parcours (générique)",
        description="Liste paginée des parcours.",
        tags=["formation"],
        parameters=[*PARAMS_PAGINATION],
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
    post=extend_schema(
        summary="Créer un parcours (générique)",
        description="Crée un parcours. Réservé à l'administrateur général.",
        tags=["formation"],
        examples=[*ERREURS_ECRITURE],
    ),
)
class ParcoursListCreateView(generics.ListCreateAPIView):
    queryset = Parcours.objects.all()
    serializer_class = ParcoursSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        user = self.request.user
        if getattr(user, "user_type", None) != "admin":
            raise PermissionDenied("Seul un administrateur général peut créer un parcours.")
        serializer.save()


class AssignAdminView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Assigner un enseignant admin à un parcours",
        description="Variante de nommer-admin utilisant la méthode PUT.",
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    def put(self, request, pk):
        from django.contrib.auth import get_user_model

        User = get_user_model()

        parcours = get_object_or_404(Parcours, pk=pk)
        admin_id = request.data.get("admin_id")
        if not admin_id:
            return Response({"error": "admin_id requis."}, status=status.HTTP_400_BAD_REQUEST)

        admin_user = get_object_or_404(User, pk=admin_id)
        if getattr(admin_user, "user_type", None) != "enseignant_admin":
            return Response(
                {"error": "Utilisateur n'est pas enseignant_admin."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parcours.admin = admin_user
        parcours.save()
        return Response(
            {"message": "Enseignant admin assigné avec succès."}, status=status.HTTP_200_OK
        )


@extend_schema(
    summary="Lister les parcours",
    description="Retourne la liste paginée de tous les parcours (Cursus, Prépa Concours, Formations, etc.).",
    tags=["formation"],
    parameters=[*PARAMS_PAGINATION],
    responses={200: ParcoursSerializer(many=True)},
    examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def liste_parcours(request):
    parcours = Parcours.objects.select_related("admin").all()
    paginator = YekiPageNumberPagination()
    page = paginator.paginate_queryset(parcours, request)
    serializer = ParcoursSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


@extend_schema(
    summary="Détail d'un parcours",
    description="Retourne les informations d'un parcours donné.",
    tags=["formation"],
    responses={200: ParcoursSerializer},
    examples=[*ERREURS_COURANTES],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def parcours_unique(request, parcours_id):
    parcours = Parcours.objects.get(id=parcours_id)
    serializer = ParcoursSerializer(parcours)
    return Response(serializer.data, status=status.HTTP_200_OK)


class ApprenantConcoursFormationsView(PaginatedListMixin, APIView):
    """
    GET /api/apprenant/prepa-concours/   → type='prepa' (concours)
    GET /api/apprenant/formations/       → type='formation' (formations)

    Retourne les concours ou formations accessibles selon le niveau de l'apprenant.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Concours/formations accessibles à l'apprenant",
        description="Liste paginée des départements de type prépa-concours ou formation accessibles selon le niveau de l'apprenant connecté (type déduit de l'URL appelée).",
        tags=["formation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    )
    def get(self, request):
        # Récupérer le type depuis l'URL ou query param
        # Le type est déterminé par l'URL appelée
        path = request.path
        if "prepa-concours" in path:
            type_parcours = "prepa"
        elif "formations" in path:
            type_parcours = "formation"
        else:
            type_parcours = request.query_params.get("type", "prepa")

        # Récupérer le profil de l'apprenant
        profile = _get_profile(request.user)
        if not profile or profile.user_type != "apprenant":
            return Response({"detail": "Accès réservé aux apprenants"}, status=403)

        niveau_apprenant = (profile.niveau or "").strip().lower()

        # Filtrer par type de parcours
        depts = Departement.objects.filter(
            parcours__type_parcours=type_parcours,
            est_actif=True,
        ).select_related("parcours", "cadre__user")

        resultats = []
        for dept in depts:
            # Filtrer par niveau
            if not dept.est_accessible_par_niveau(niveau_apprenant):
                continue

            # Récupérer les cours du département
            cours_qs = Cours.objects.filter(departement=dept)

            # Filtrer les cours par niveau
            if niveau_apprenant:
                cours_qs = cours_qs.filter(niveau__iexact=niveau_apprenant)

            cours_data = []
            for cours in cours_qs:
                cours_data.append(
                    {
                        "id": cours.id,
                        "titre": cours.titre,
                        "niveau": cours.niveau,
                        "description_brief": cours.description_brief or "",
                        "color_code": cours.color_code,
                        "icon_name": cours.icon_name,
                        "nb_lecons": cours.nb_lecons,
                        "nb_devoirs": cours.nb_devoirs,
                        "progression": 0.0,  # À calculer avec _progression_cours si besoin
                    }
                )

            resultats.append(self._serialiser_departement(dept, cours_data, request))

        # Filtrage par niveau fait en Python (méthode de modèle, pas un
        # filtre DB) : la pagination se fait sur la liste déjà filtrée.
        page = self.paginate_queryset(resultats)
        return self.get_paginated_response(page)

    def _serialiser_departement(self, dept, cours_data, request):
        """Sérialise un département avec ses cours selon son type."""
        image_url = None
        if dept.image:
            image_url = request.build_absolute_uri(dept.image.url)

        statut = "ACTIF" if dept.est_actif else "INACTIF"
        type_parcours = dept.parcours.type_parcours if dept.parcours else ""

        # Base commune
        result = {
            "id": dept.id,
            "nom": dept.nom,
            "description": dept.description,
            "image_url": image_url,
            "couleur": dept.couleur or "#135F74",
            "prix": dept.prix,
            "prix_presentiel": dept.prix_presentiel,
            "type": dept.type_departement,
            "statut": statut,
            "progression": 0.0,
            "progression_moyenne": 0.0,
            "cours": cours_data,
            "nb_cours": len(cours_data),
            "niveaux_accessibles": dept.get_niveaux_accessibles_list(),
            "acces_restreint": dept.acces_restreint,
            "type_parcours": type_parcours,
            "parcours_nom": dept.parcours.nom if dept.parcours else "",
        }

        # Champs spécifiques aux concours (prepa)
        if type_parcours == "prepa":
            result.update(
                {
                    "est_prepa_concours": True,
                    "est_formation_metier": False,
                    "est_formation_classique": False,
                    "nom_concours": dept.nom_concours or "",
                    "organisme_concours": dept.organisme_concours or "",
                    "date_limite_inscription": (
                        dept.date_limite_inscription.isoformat()
                        if dept.date_limite_inscription
                        else None
                    ),
                    "date_examen": dept.date_examen.isoformat() if dept.date_examen else None,
                    "arrete_ministeriel": dept.arrete_ministeriel or "",
                    "niveaux_cibles": dept.niveaux_cibles or "",
                    "places_disponibles": dept.places_disponibles,
                    "debouches": dept.debouches or "",
                    # TODO(bug pré-existant, non corrigé — "déplacer, ne pas
                    # réécrire") : 'date_examen' et 'date_limite_inscription'
                    # sont redéfinies ci-dessous (repéré en P1.6 via ruff F601) —
                    # ces 2 lignes écrasent silencieusement les versions
                    # `.isoformat()` définies plus haut par des `date`/`datetime`
                    # Python bruts, non sérialisables JSON tels quels.
                    "date_examen": dept.date_examen,  # noqa: F601
                    "mode": dept.mode or "",
                    "date_limite_inscription": dept.date_limite_inscription,  # noqa: F601
                }
            )
        # Champs spécifiques aux formations
        elif type_parcours == "formation":
            result.update(
                {
                    "est_prepa_concours": False,
                    "est_formation_metier": dept.est_formation_metier,
                    "est_formation_classique": dept.est_formation_classique,
                    "duree_formation": dept.duree_formation or "",
                    "mode": dept.mode or "",
                    "mode_label": {
                        "presentiel": "Présentiel",
                        "distance": "À distance",
                        "hybride": "Hybride",
                    }.get(dept.mode, ""),
                    "certificat_delivre": dept.certificat_delivre or "",
                    "prerequis": dept.prerequis or "",
                    "objectifs": dept.objectifs or "",
                    "domaine": dept.domaine or "",
                    "ville": dept.ville or "",
                    "est_certifiante": dept.est_certifiante,
                }
            )
        else:
            # Parcours autre (cursus) - champs par défaut
            result.update(
                {
                    "est_prepa_concours": False,
                    "est_formation_metier": False,
                    "est_formation_classique": False,
                }
            )

        return result


@extend_schema(
    summary="Statistiques globales des parcours",
    description="Retourne le total d'apprenants, de cours et la moyenne globale agrégés sur tous les parcours.",
    tags=["formation"],
    responses={200: OpenApiTypes.OBJECT},
    examples=[*ERREURS_COURANTES],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def statistiques_globales(request):
    total_apprenants = Parcours.objects.aggregate(Sum("apprenants"))["apprenants__sum"] or 0
    total_cours = Parcours.objects.aggregate(Sum("cours"))["cours__sum"] or 0
    moyenne_globale = Parcours.objects.aggregate(Avg("moyenne"))["moyenne__avg"] or 0.0

    return Response(
        {
            "total_apprenants": total_apprenants,
            "total_cours": total_cours,
            "moyenne_globale": round(moyenne_globale, 2),
        },
        status=status.HTTP_200_OK,
    )
