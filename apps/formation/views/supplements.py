# apps/formation/views/supplements.py
#
# P11.9 — CRUD des suppléments de cours (lien/pdf/powerpoint/autre).
# Rattachés au cours (obligatoire) + à une leçon (facultative) : si une
# leçon est renseignée, le supplément n'apparaît QUE sur cette leçon,
# sinon il est visible sur tout le cours. Ajout/retrait réservés à
# l'enseignant principal DU COURS (`IsPrincipalDuCours`, déjà existant —
# accepte tout objet portant un attribut `.cours`, dont `SupplementCours`
# directement).

from django.db.models import Q
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.core.schema_examples import ERREURS_COURANTES, ERREURS_ECRITURE
from apps.formation.models import Cours, Lecon, SupplementCours
from apps.formation.serializers import SupplementCoursSerializer
from yeki.permissions import IsPrincipalDuCours


@extend_schema_view(
    get=extend_schema(
        summary="Lister les suppléments d'un cours",
        description=(
            "Retourne les suppléments rattachés à ce cours. Sans `lecon_id`, "
            "renvoie uniquement les suppléments valables pour tout le cours "
            "(sans leçon spécifique). Avec `lecon_id`, renvoie ceux de cette "
            "leçon PLUS les suppléments de portée cours (visibles partout)."
        ),
        tags=["formation"],
        parameters=[
            OpenApiParameter(
                "lecon_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre sur les suppléments visibles pour cette leçon précise.",
            ),
        ],
        responses={200: SupplementCoursSerializer(many=True)},
        examples=[*ERREURS_COURANTES],
    ),
)
class ListerSupplementsCoursView(APIView):
    """GET /api/cours/<cours_id>/supplements/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        cours = get_object_or_404(Cours, id=cours_id)
        lecon_id = request.query_params.get("lecon_id")

        if lecon_id:
            lecon = get_object_or_404(Lecon, id=lecon_id)
            supplements = SupplementCours.objects.filter(cours=cours).filter(
                Q(lecon=lecon) | Q(lecon__isnull=True)
            )
        else:
            supplements = SupplementCours.objects.filter(cours=cours, lecon__isnull=True)

        serializer = SupplementCoursSerializer(
            supplements.order_by("ordre", "created_at"), many=True, context={"request": request}
        )
        return Response(serializer.data)


@extend_schema_view(
    post=extend_schema(
        summary="Ajouter un supplément à un cours",
        description=(
            "Crée un supplément (lien/pdf/powerpoint/autre) rattaché à ce "
            "cours, avec une leçon optionnelle. Réservé à l'enseignant "
            "principal du cours."
        ),
        tags=["formation"],
        request=SupplementCoursSerializer,
        responses={201: SupplementCoursSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class CreerSupplementCoursView(APIView):
    """POST /api/cours/<cours_id>/supplements/creer/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cours_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        cours = get_object_or_404(Cours, id=cours_id)

        if not IsPrincipalDuCours().has_object_permission(request, self, cours):
            return Response(
                {"detail": "Réservé à l'enseignant principal de ce cours."}, status=403
            )

        serializer = SupplementCoursSerializer(data=request.data, context={"request": request, "cours": cours})
        serializer.is_valid(raise_exception=True)
        supplement = serializer.save(cours=cours)

        return Response(
            SupplementCoursSerializer(supplement, context={"request": request}).data, status=201
        )


@extend_schema_view(
    delete=extend_schema(
        summary="Retirer un supplément",
        description="Supprime un supplément. Réservé à l'enseignant principal du cours concerné.",
        tags=["formation"],
        responses={204: OpenApiTypes.NONE},
        examples=[*ERREURS_ECRITURE],
    ),
)
class SupprimerSupplementCoursView(APIView):
    """DELETE /api/supplements/<supplement_id>/supprimer/"""

    permission_classes = [IsAuthenticated]

    def delete(self, request, supplement_id):
        supplement = get_object_or_404(SupplementCours, id=supplement_id)

        if not IsPrincipalDuCours().has_object_permission(request, self, supplement):
            return Response(
                {"detail": "Réservé à l'enseignant principal de ce cours."}, status=403
            )

        supplement.delete()
        return Response(status=204)
