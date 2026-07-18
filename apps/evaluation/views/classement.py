from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.core.schema_examples import ERREURS_COURANTES, ERREURS_ECRITURE
from apps.formation.models import Departement, Cours
from apps.evaluation.models import EvaluationExercice, RangApprenant

# TODO(bloqué, pré-existant, ne pas corriger ici) : `yeki/ranking_service.py`
# a été vidé localement (hors de ce déplacement, chantier en cours de
# l'utilisateur) et ne contient plus du tout la classe `RankingService`.
# L'import direct `from yeki.ranking_service import RankingService` faisait
# planter le chargement de CE MODULE — et donc de tout `config/urls.py` (qui
# inclut `apps.evaluation.urls` → `apps.evaluation.views` → ce fichier),
# bloquant l'exécution de la moindre requête HTTP/test sur TOUTE l'API, pas
# seulement sur le classement. Import retiré (P1.6, validé avec
# l'utilisateur) ; la classe ci-dessous est un stub local minimal — elle ne
# reproduit qu'une partie de l'ancien service (`_calculer_score_exercices`)
# et n'a PAS `obtenir_classement_departement` (utilisée plus bas) : cette vue
# reste donc non fonctionnelle à l'exécution réelle (AttributeError), voir
# docs/API_FOUNDATIONS.md et docs/MIGRATIONS_APPS.md. Implémentation
# complète hors périmètre de cette tâche.


class RankingService:
    """
    Service de calcul des scores et rangs des apprenants.
    Poids par catégorie :
    - Devoirs rendus à temps : 1.0
    - Notes aux devoirs : 3.0 (le plus important)
    - Résultats exercices : 2.0 (poids de base)
    - Progression leçons : 1.0
    - Participation forum : 0.5
    - Régularité de connexion : 0.5
    """

    # Poids des catégories
    WEIGHTS = {
        "devoirs": 1.0,
        "notes_devoirs": 3.0,
        "exercices": 2.0,
        "lecons": 1.0,
        "forum": 0.5,
        "regularite": 0.5,
    }

    # Poids supplémentaires par étoiles pour les exercices
    EXERCISE_STAR_WEIGHTS = {
        1: 0.5,
        2: 1.0,
        3: 1.5,
        4: 2.0,
        5: 3.0,
    }

    # Score maximum par catégorie
    MAX_SCORES = {
        "devoirs": 100.0,
        "notes_devoirs": 100.0,
        "exercices": 100.0,
        "lecons": 100.0,
        "forum": 100.0,
        "regularite": 100.0,
    }

    @classmethod
    def _calculer_score_exercices(cls, apprenant: User, departement: Departement) -> float:
        """
        Score basé sur les résultats aux exercices avec pondération par étoiles.
        """
        cours_ids = Cours.objects.filter(departement=departement).values_list("id", flat=True)

        # Récupérer toutes les évaluations d'exercices avec les étoiles
        evaluations = (
            EvaluationExercice.objects.filter(user=apprenant, exercice__cours_id__in=cours_ids)
            .select_related("exercice")
            .order_by("-date")
        )

        # Grouper par exercice et prendre la dernière tentative
        latest_attempts = {}
        for eval in evaluations:
            if eval.exercice_id not in latest_attempts:
                latest_attempts[eval.exercice_id] = eval

        if not latest_attempts:
            return 0.0

        # Calculer le score pondéré par les étoiles
        total_score = 0.0
        total_weight = 0.0

        for eval in latest_attempts.values():
            if eval.total > 0:
                pourcentage = (eval.score / eval.total) * 100
                etoiles = eval.exercice.etoiles if hasattr(eval.exercice, "etoiles") else 3
                weight = cls.EXERCISE_STAR_WEIGHTS.get(etoiles, 1.0)

                total_score += pourcentage * weight
                total_weight += weight

        if total_weight == 0:
            return 0.0

        moyenne = total_score / total_weight
        return round(min(100, moyenne), 2)


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

    # TODO(correction): cette classe définit `get()` DEUX FOIS (doublon
    # nouvellement découvert lors de l'éclatement, non documenté dans
    # docs/AUDIT_BACKEND.md) — la seconde définition écrase silencieusement
    # la première dans le namespace de la classe (seule la seconde, qui
    # calcule `mon_rang`, est réellement exécutée). Conservées toutes les
    # deux telles quelles ("déplacer, ne pas réécrire") ; à nettoyer dans
    # une tâche de correction dédiée (voir docs/SPLIT_VIEWS.md).
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
            # Vérifier que l'apprenant appartient à ce département
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

        classement = RankingService.obtenir_classement_departement(departement, limit)

        # Ajouter des métadonnées
        stats = {
            "total_apprenants": len(classement),
            "score_min": classement[-1]["score"] if classement else 0,
            "score_max": classement[0]["score"] if classement else 0,
            "score_moyen": (
                round(sum(c["score"] for c in classement) / len(classement), 1) if classement else 0
            ),
        }

        return Response(
            {
                "departement": {
                    "id": departement.id,
                    "nom": departement.nom,
                },
                "mon_rang": None,  # Rempli plus bas si apprenant
                "classement": classement,
                "stats": stats,
            }
        )

    def get(self, request, departement_id):  # noqa: F811
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        departement = get_object_or_404(Departement, pk=departement_id)

        # Vérifications d'accès
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

        classement = RankingService.obtenir_classement_departement(departement, limit)

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
            count = RankingService.mettre_a_jour_rangs_departement(departement)
            message = f"Classement recalculé pour {departement.nom}: {count} apprenants"
        else:
            count = RankingService.mettre_a_jour_tous_les_rangs()
            message = f"Classement global recalculé: {count} apprenants"

        return Response(
            {
                "detail": message,
                "apprenants_traites": count,
            }
        )
