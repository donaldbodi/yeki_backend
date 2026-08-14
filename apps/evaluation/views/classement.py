from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.core.schema_examples import ERREURS_COURANTES, ERREURS_ECRITURE
from apps.formation.models import Departement
from apps.evaluation.models import ClassementHistorique, RangApprenant
from apps.evaluation.services import ClassementService


@extend_schema_view(
    get=extend_schema(
        summary="Classement des apprenants d'un département",
        description=(
            "Retourne le classement (rang, score, progression) des apprenants "
            "d'un département donné, avec des statistiques agrégées (score min/max/moyen) "
            "et, si l'appelant est un apprenant, son propre rang dans `mon_rang`. "
            "Accès restreint : un apprenant ne voit que le classement de son propre "
            "cursus, un enseignant cadre celui de son département, admin/enseignant_admin "
            "voient tout."
        ),
        tags=["evaluation"],
        parameters=[
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Nombre maximum de résultats à retourner (défaut 100, max 200).",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class ClassementDepartementView(APIView):
    """
    GET /api/classement/departement/<departement_id>/
    Retourne le classement des apprenants d'un département.

    Query params:
    - limit: nombre de résultats (défaut 100, max 200)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        departement = get_object_or_404(Departement, pk=departement_id)

        # Vérifier que l'utilisateur a accès à ce département
        if profile.user_type == "apprenant":
            if profile.cursus != departement.parcours.nom:
                return Response({"detail": "Vous n'avez pas accès à ce classement."}, status=403)
        elif profile.user_type == "enseignant_cadre":
            if departement.cadre != profile:
                return Response({"detail": "Ce département ne vous appartient pas."}, status=403)
        elif profile.user_type not in ["admin", "enseignant_admin"]:
            return Response({"detail": "Accès non autorisé."}, status=403)

        try:
            limit = min(int(request.query_params.get("limit", 100)), 200)
        except (TypeError, ValueError):
            limit = 100

        classement = ClassementService.calculer_classement_departement(departement, limit)

        # Trouver le rang de l'utilisateur connecté (si apprenant)
        mon_rang = None
        if profile.user_type == "apprenant":
            for item in classement:
                if item["apprenant_id"] == request.user.id:
                    mon_rang = {
                        "rang": item["rang"],
                        "score": item["score"],
                        "progression": item["progression"],
                    }
                    break

        # Statistique de cohorte purement descriptive (score moyen des
        # apprenants DÉJÀ classés, pas "la note" d'un individu ni d'un
        # exercice) — décision actée, conservée telle quelle (P6.1).
        stats = {
            "total": len(classement),
            "moyenne": (
                round(sum(c["score"] for c in classement) / len(classement), 1) if classement else 0
            ),
            "meilleur": classement[0]["score"] if classement else 0,
        }

        return Response(
            {
                "departement": {
                    "id": departement.id,
                    "nom": departement.nom,
                },
                "mon_rang": mon_rang,
                "classement": classement,
                "stats": stats,
            }
        )


def _verifier_acces_classement(profile, departement):
    """Même règle d'accès que `ClassementDepartementView` — factorisée ici
    pour ne pas la retaper une 3e fois avec `ClassementPeriodesView`/
    `ClassementHistoriqueView` (P11.8, accès aux périodes archivées)."""
    if profile.user_type == "apprenant":
        if profile.cursus != departement.parcours.nom:
            return Response({"detail": "Vous n'avez pas accès à ce classement."}, status=403)
    elif profile.user_type == "enseignant_cadre":
        if departement.cadre != profile:
            return Response({"detail": "Ce département ne vous appartient pas."}, status=403)
    elif profile.user_type not in ["admin", "enseignant_admin"]:
        return Response({"detail": "Accès non autorisé."}, status=403)
    return None


@extend_schema_view(
    get=extend_schema(
        summary="Périodes de classement archivées d'un département",
        description=(
            "Retourne la liste des périodes de classement déjà archivées "
            "(voir `Departement.reinitialiser_periode()`) pour ce département, "
            "les plus récentes d'abord. Même règle d'accès que le classement "
            "en cours."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class ClassementPeriodesView(APIView):
    """
    GET /api/classement/departement/<departement_id>/periodes/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        departement = get_object_or_404(Departement, pk=departement_id)

        erreur = _verifier_acces_classement(profile, departement)
        if erreur is not None:
            return erreur

        periodes = (
            ClassementHistorique.objects.filter(departement=departement)
            .values("periode_debut", "periode_fin")
            .distinct()
            .order_by("-periode_debut")
        )

        return Response(list(periodes))


@extend_schema_view(
    get=extend_schema(
        summary="Classement archivé d'une période passée",
        description=(
            "Retourne le classement figé (`ClassementHistorique`) d'une période "
            "de classement déjà archivée, identifiée par `periode_debut` (format "
            "ISO 8601, doit correspondre exactement à une valeur retournée par "
            "`GET .../periodes/`)."
        ),
        tags=["evaluation"],
        parameters=[
            OpenApiParameter(
                "periode_debut",
                OpenApiTypes.DATETIME,
                OpenApiParameter.QUERY,
                required=True,
                description="Début de la période archivée à consulter (ISO 8601).",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class ClassementHistoriqueView(APIView):
    """
    GET /api/classement/departement/<departement_id>/historique/?periode_debut=<iso>
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        departement = get_object_or_404(Departement, pk=departement_id)

        erreur = _verifier_acces_classement(profile, departement)
        if erreur is not None:
            return erreur

        periode_debut = request.query_params.get("periode_debut")
        if not periode_debut:
            return Response({"detail": "Le paramètre periode_debut est requis."}, status=400)

        lignes = (
            ClassementHistorique.objects.filter(
                departement=departement, periode_debut=periode_debut
            )
            .select_related("apprenant")
            .order_by("rang")
        )
        if not lignes.exists():
            return Response({"detail": "Aucune période archivée à cette date."}, status=404)

        classement = [
            {
                "apprenant_id": ligne.apprenant_id,
                "nom": (
                    f"{ligne.apprenant.first_name} {ligne.apprenant.last_name}".strip()
                    or ligne.apprenant.username
                ),
                "username": ligne.apprenant.username,
                "rang": ligne.rang,
                "score": ligne.points,
                "detail": ligne.detail,
            }
            for ligne in lignes
        ]

        return Response(
            {
                "departement": {"id": departement.id, "nom": departement.nom},
                "periode_debut": lignes.first().periode_debut,
                "periode_fin": lignes.first().periode_fin,
                "classement": classement,
            }
        )


@extend_schema_view(
    get=extend_schema(
        summary="Mon score et mon rang",
        description=(
            "Retourne le score global, le rang et la progression hebdomadaire de "
            "l'apprenant connecté dans le département principal de son cursus, "
            "ainsi que le détail des scores par catégorie (devoirs, notes de devoirs, "
            "exercices, leçons, forum, régularité). Réservé aux apprenants."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class MonScoreGlobalView(APIView):
    """
    GET /api/classement/mon-score/
    Retourne le score et le rang de l'apprenant dans son département principal.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "apprenant":
            return Response({"detail": "Réservé aux apprenants."}, status=403)

        if not profile.cursus:
            return Response({"detail": "Aucun cursus assigné."}, status=404)

        # Récupérer le département principal du parcours de l'apprenant.
        # `.first()` renvoie déjà None si aucun résultat : pas de
        # try/except nécessaire (une vraie erreur DB doit remonter à
        # EXCEPTION_HANDLER, pas être masquée en "aucun département").
        parcours = Departement.objects.filter(
            parcours__nom=profile.cursus, parcours__type_parcours="cursus"
        ).first()

        if not parcours:
            return Response({"detail": "Aucun département trouvé pour votre cursus."}, status=404)

        # Récupérer le rang
        rang = RangApprenant.objects.filter(apprenant=request.user, departement=parcours).first()

        # Scores par catégorie
        scores_categorie = {}
        if rang:
            details = rang.details.all()
            scores_categorie = {d.categorie: round(d.score, 1) for d in details}

        return Response(
            {
                "score": round(rang.score, 1) if rang else 0,
                "rang": rang.rang if rang else None,
                "total_apprenants": RangApprenant.objects.filter(
                    departement=parcours, rang__isnull=False
                ).count(),
                "progression": round(rang.progression_semaine, 1) if rang else 0,
                "scores_categorie": scores_categorie,
                "departement": {
                    "id": parcours.id,
                    "nom": parcours.nom,
                },
            }
        )


@extend_schema_view(
    post=extend_schema(
        summary="Recalculer le classement",
        description=(
            "Force le recalcul des rangs des apprenants — soit pour un seul "
            "département (si `departement_id` est fourni dans le corps), soit pour "
            "l'ensemble des départements. Réservé aux administrateurs "
            "(admin, enseignant_admin)."
        ),
        tags=["evaluation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class RecalculerClassementView(APIView):
    """
    POST /api/classement/recalculer/
    Body: { "departement_id": 123 }  (optionnel)
    Force le recalcul des rangs. Réservé aux admins.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type not in ["admin", "enseignant_admin"]:
            return Response({"detail": "Accès réservé aux administrateurs."}, status=403)

        departement_id = request.data.get("departement_id")

        if departement_id:
            departement = get_object_or_404(Departement, pk=departement_id)
            count = ClassementService.mettre_a_jour_rangs_departement(departement)
            message = f"Classement recalculé pour {departement.nom}: {count} apprenants"
        else:
            count = ClassementService.mettre_a_jour_tous_les_rangs()
            message = f"Classement global recalculé: {count} apprenants"

        return Response(
            {
                "detail": message,
                "apprenants_traites": count,
            }
        )


@extend_schema(
    summary="Coefficient minimum d'un devoir",
    description=(
        "P17.14 : renvoie le plancher réel appliqué au coefficient d'un "
        "devoir à la création/modification (poids `ParametreClassement` "
        "de la source `etoile_3` — la valeur d'un exercice 3 étoiles) — "
        "pour que le frontend n'ait jamais à deviner/coder en dur cette "
        "valeur métier (règle 3)."
    ),
    tags=["evaluation"],
    responses={200: OpenApiTypes.OBJECT},
)
class CoefficientDevoirMinimumView(APIView):
    """GET /api/classement/coefficient-devoir-minimum/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.evaluation.models import ParametreClassement

        parametre = ParametreClassement.objects.filter(source="etoile_3").first()
        return Response({"coefficient_min": parametre.poids if parametre else 0.1})
