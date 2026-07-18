from rest_framework.authtoken.models import Token
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.accounts.models import Profile
from apps.accounts.serializers import ProfilDetailSerializer
from apps.formation.models import Cours, Lecon, Departement
from apps.evaluation.models import SoumissionDevoir, EvaluationExercice

from drf_spectacular.utils import extend_schema, extend_schema_view
from drf_spectacular.types import OpenApiTypes
from apps.core.schema_examples import ERREURS_COURANTES, ERREURS_ECRITURE


@extend_schema_view(
    get=extend_schema(
        summary="Consulter son propre profil",
        description="Retourne le profil détaillé de l'utilisateur actuellement connecté.",
        tags=["accounts"],
        responses={200: ProfilDetailSerializer},
        examples=[*ERREURS_COURANTES],
    ),
)
class ProfilMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        serializer = ProfilDetailSerializer(profile, context={"request": request})
        return Response(serializer.data, status=200)


@extend_schema_view(
    patch=extend_schema(
        summary="Mettre à jour son propre profil",
        description=(
            "Met à jour les champs modifiables du profil de l'utilisateur "
            "connecté : `first_name`, `last_name`, `email` (sur le compte "
            "utilisateur), ainsi que `phone`, `bio`, `cursus`, `sub_cursus`, "
            "`niveau`, `filiere`, `licence` et `avatar` (fichier image, sur le "
            "profil). Accepte multipart/form-data ou JSON. Tous les champs "
            "sont optionnels."
        ),
        tags=["accounts"],
        request=OpenApiTypes.OBJECT,
        responses={200: ProfilDetailSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class ProfilUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def patch(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        data = request.data

        # Champs User Django
        user = request.user
        if "first_name" in data:
            user.first_name = data["first_name"]
        if "last_name" in data:
            user.last_name = data["last_name"]
        if "email" in data:
            user.email = data["email"]
        user.save()

        # Champs Profile
        for field in ["phone", "bio", "cursus", "sub_cursus", "niveau", "filiere", "licence"]:
            if field in data:
                setattr(profile, field, data[field])

        # Avatar (fichier image)
        if "avatar" in request.FILES:
            profile.avatar = request.FILES["avatar"]

        profile.save()

        serializer = ProfilDetailSerializer(profile, context={"request": request})
        return Response(serializer.data, status=200)


@extend_schema_view(
    delete=extend_schema(
        summary="Supprimer son propre compte",
        description=(
            "Supprime définitivement le compte de l'utilisateur connecté "
            "(utilisateur Django et profil associé) après suppression de son "
            "token d'authentification. Action irréversible."
        ),
        tags=["accounts"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class ProfilDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user
        try:
            user.auth_token.delete()
        except Token.DoesNotExist:
            pass
        user.delete()
        return Response({"detail": "Compte supprimé avec succès."}, status=200)


@extend_schema_view(
    get=extend_schema(
        summary="Statistiques personnelles selon le rôle",
        description=(
            "Retourne des statistiques adaptées au rôle du profil connecté : "
            "pour un apprenant — `nb_cours`, `nb_devoirs`, `moyenne` ; pour un "
            "enseignant principal ou secondaire — `nb_cours`, `nb_lecons`, "
            "`nb_devoirs` ; pour un enseignant cadre — `nb_departements`, "
            "`nb_cours`, `nb_devoirs` ; pour les autres rôles — valeurs par "
            "défaut à zéro."
        ),
        tags=["accounts"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class ProfilStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        role = profile.user_type
        stats = {}

        if role == "apprenant":
            # Nombre de cours disponibles dans son cursus
            nb_cours = (
                Cours.objects.filter(departement__parcours__nom=profile.cursus).count()
                if profile.cursus
                else 0
            )
            # Devoirs : tous les devoirs (on peut filtrer plus tard)
            nb_devoirs = SoumissionDevoir.objects.filter(utilisateur=request.user).count()
            # Évaluations : score moyen
            evals = EvaluationExercice.objects.filter(user=request.user)
            if evals.exists():
                moyenne = (
                    sum((e.score / e.total * 20) for e in evals if e.total > 0) / evals.count()
                )
            else:
                moyenne = 0.0
            stats = {
                "nb_cours": nb_cours,
                "nb_devoirs": nb_devoirs,
                "moyenne": round(moyenne, 1),
            }

        elif role in ["enseignant_principal", "enseignant"]:
            if role == "enseignant_principal":
                nb_cours = Cours.objects.filter(enseignant_principal=profile).count()
            else:
                nb_cours = profile.cours_secondaires.count()
            nb_lecons = Lecon.objects.filter(created_by=profile).count()
            stats = {
                "nb_cours": nb_cours,
                "nb_lecons": nb_lecons,
                "nb_devoirs": 0,
            }

        elif role == "enseignant_cadre":
            nb_departements = Departement.objects.filter(cadre=profile).count()
            nb_cours = Cours.objects.filter(departement__cadre=profile).count()
            stats = {
                "nb_departements": nb_departements,
                "nb_cours": nb_cours,
                "nb_devoirs": 0,
            }

        else:
            stats = {"nb_cours": 0, "nb_devoirs": 0, "moyenne": 0.0}

        return Response(stats, status=200)
