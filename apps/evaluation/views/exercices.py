from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.core.models import enregistrer_activite
from apps.core.pagination import PaginatedListMixin
from apps.core.permissions import AccesMatricePermission
from apps.core.services import AccesService
from apps.notifications.models import creer_notification
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
)
from apps.formation.models import Cours, Module
from apps.evaluation.models import (
    Exercice,
    SessionExercice,
    Question,
    ExerciceTentative,
    EvaluationExercice,
)
from apps.evaluation.services import ClassementService
from apps.evaluation.serializers import (
    ExerciceSerializer,
    ExerciceCreateSerializer,
    QuestionSerializer,
    QuestionCreateSerializer,
    EvaluationSerializer,
)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les exercices d'un cours",
        description=(
            "Retourne la liste paginée des exercices d'un cours, triés du plus récent "
            "au plus ancien. Exclut par défaut les épreuves (`est_epreuve=True`) sauf "
            "si `include_epreuves=true` est passé."
        ),
        tags=["evaluation"],
        parameters=[
            OpenApiParameter(
                "module_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtrer par module.",
            ),
            OpenApiParameter(
                "lecon_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtrer par leçon.",
            ),
            OpenApiParameter(
                "type",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="general | module | lecon | epreuve",
            ),
            OpenApiParameter(
                "include_epreuves",
                OpenApiTypes.BOOL,
                OpenApiParameter.QUERY,
                required=False,
                description="Si 'true', inclut aussi les épreuves dans les résultats.",
            ),
            *PARAMS_PAGINATION,
        ],
        responses={200: ExerciceSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class ListeExercicesCoursView(PaginatedListMixin, APIView):
    """
    GET /api/cours/<cours_id>/exercices/
    Paramètres optionnels :
    - module_id: filtrer par module
    - lecon_id: filtrer par leçon
    - type: general, module, lecon, epreuve
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)

        # Base queryset
        exercices = Exercice.objects.filter(cours=cours)

        # Filtres
        module_id = request.query_params.get("module_id")
        if module_id:
            # P6.3 : un exercice rattaché à une leçon DU module doit aussi
            # apparaître (pas seulement ceux rattachés directement au
            # module) — sinon « cliquer sur un module » masquait les
            # exercices liés à ses leçons.
            exercices = exercices.filter(
                Q(module_id=module_id) | Q(lecon__module_id=module_id)
            )

        lecon_id = request.query_params.get("lecon_id")
        if lecon_id:
            exercices = exercices.filter(lecon_id=lecon_id)

        type_exercice = request.query_params.get("type")
        if type_exercice:
            exercices = exercices.filter(type_exercice=type_exercice)
        else:
            # Par défaut, afficher tous les types sauf les épreuves (sauf si demandé)
            if request.query_params.get("include_epreuves") != "true":
                exercices = exercices.exclude(est_epreuve=True)

        # CORRECTION : Ne pas annoter avec nb_questions, le serializer le calcule
        exercices = exercices.order_by("-id")

        # P9.1 : matrice d'accès Gratuit/Premium — un gratuit voit les
        # exercices 1★/2★ (vitrine), pas au-delà. Filtrage de queryset
        # (pas la permission_class, qui est tout-ou-rien) : voir
        # AccesService.etoiles_max_visibles.
        seuil = AccesService.etoiles_max_visibles(request.user, cours.departement)
        if seuil is not None:
            exercices = exercices.filter(etoiles__lte=seuil)

        page = self.paginate_queryset(exercices)
        serializer = ExerciceSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)


@extend_schema_view(
    post=extend_schema(
        summary="Ajouter un exercice à un cours",
        description=(
            "Crée un nouvel exercice pour un cours (supporte l'upload d'une image "
            "d'énoncé via `enonce_image`). Réservé à l'enseignant principal du cours."
        ),
        tags=["evaluation"],
        request={"multipart/form-data": ExerciceCreateSerializer},
        responses={201: ExerciceSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AjouterExerciceView(APIView):
    """
    POST /api/cours/<cours_id>/exercices/ajouter/
    Body: { "titre": "...", "enonce": "...", "etoiles": 3, ... }
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut ajouter un exercice."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Copier les données pour les modifier
        data = request.data.copy()

        # Gérer l'énoncé image
        if "enonce_image" in request.FILES:
            data["enonce_image"] = request.FILES["enonce_image"]

        serializer = ExerciceCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        exercice = serializer.save(cours=cours)

        # Enregistrer dans l'historique
        enregistrer_activite(
            user=request.user,
            action="exercise_created",
            description=f"Exercice « {exercice.titre} » ajouté au cours « {cours.titre} »",
            data={
                "exercice": exercice.titre,
                "cours": cours.titre,
                "etoiles": exercice.etoiles,
                "type": exercice.type_exercice,
            },
            objet_id=exercice.id,
            objet_type="Exercice",
        )

        cours.nb_devoirs += 1
        cours.save(update_fields=["nb_devoirs"])

        # Retourner l'exercice créé avec ses données enrichies
        return Response(
            ExerciceSerializer(exercice, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


def _corriger_reponses_exercice(exercice, reponses):
    """
    Corrige les réponses fournies pour un exercice donné.
    Retourne (score, total, details) où `details` est une liste de
    dictionnaires au format SNAPSHOT complet (P6.2, CDC_BACKEND §6.1) :
    question_id, enonce_snapshot, type, choix_snapshot, reponse_apprenant,
    bonne_reponse, est_correct, points_obtenus, points_max, explication —
    figé au moment de la correction, indépendant de tout état futur de
    `Question`/`Choix`. C'est cette forme canonique qui est stockée telle
    quelle dans `ExerciceTentative.reponses["questions"]`.
    Factorisé pour être appelé identiquement depuis SoumettreEvaluationView
    et SortirExerciceView (aucune logique dupliquée entre les deux vues).
    """
    score = 0.0
    total = 0.0
    details = []
    for question in exercice.questions.all():
        points = question.points
        total += points

        user_rep = reponses.get(str(question.id), "").strip().lower()

        # P2.2 : pour un QCM, la correction se fait via Choix.est_correct
        # (source de vérité), pas via une comparaison texte-à-texte contre
        # bonne_reponse (fragile — casse/espaces/accents). Même convention
        # que SoumettreDevoirView (apps/evaluation/views/devoirs.py).
        if question.type_question == "qcm":
            choix_selectionne = question.choix.filter(texte__iexact=user_rep).first()
            is_correct = bool(choix_selectionne and choix_selectionne.est_correct)
        else:
            is_correct = user_rep == question.bonne_reponse.strip().lower()

        points_obtenus = points if is_correct else 0

        if is_correct:
            score += points

        choix_snapshot = (
            [
                {"id": c.id, "texte": c.texte, "est_correct": c.est_correct}
                for c in question.choix.all()
            ]
            if question.type_question == "qcm"
            else []
        )

        details.append(
            {
                "question_id": question.id,
                "enonce_snapshot": question.text,
                "type": question.type_question,
                "choix_snapshot": choix_snapshot,
                "reponse_apprenant": user_rep,
                "bonne_reponse": question.bonne_reponse,
                "est_correct": is_correct,
                "points_obtenus": points_obtenus,
                "points_max": points,
                "explication": question.explication,
            }
        )
    return score, total, details


def _detail_soumission(d):
    """
    Adapte le schéma canonique (snapshot P6.2) vers les noms de clés
    HISTORIQUES du champ `detail` renvoyé immédiatement par
    SortirExerciceView/SoumettreEvaluationView — inchangés pour ne pas
    casser `passer_exercice.dart`, qui les consomme déjà tels quels.
    """
    return {
        "question_id": d["question_id"],
        "question": d["enonce_snapshot"],
        "reponse_utilisateur": d["reponse_apprenant"],
        "bonne_reponse": d["bonne_reponse"],
        "correct": d["est_correct"],
        "points_obtenus": d["points_obtenus"],
        "points_max": d["points_max"],
        "explication": d["explication"],
    }


def _detail_historique(d):
    """
    Adapte le schéma canonique vers les noms de clés HISTORIQUES du champ
    `reponses` de `HistoriqueTentativesExerciceView` (et désormais de
    `ResultatExerciceView.historique[].reponses`) — `points_obtenus` et
    `explication` sont de PURS AJOUTS (absents avant P6.2, un lecteur
    Flutter qui ne les connaît pas encore les ignore sans risque).
    """
    return {
        "question_id": d["question_id"],
        "question": d["enonce_snapshot"],
        "reponse": d["reponse_apprenant"],
        "bonne_reponse": d["bonne_reponse"],
        "est_correct": d["est_correct"],
        "points_obtenus": d["points_obtenus"],
        "points_max": d["points_max"],
        "explication": d["explication"],
    }


def _corriger_epreuve_composee(exercice, user):
    """
    Note d'une ÉPREUVE (P6.3, décision actée) : SOMME des scores des
    exercices de `exercice.exercices_composes`, PAS ses propres
    `questions` (souvent vides pour un pur conteneur). Chaque composant
    contribue son total plein de points (tenté ou non — dénominateur
    stable, ne rétrécit pas si l'apprenant n'a pas encore touché à un
    composant) et son score actuel (0 s'il n'a jamais été tenté).
    Retourne (score, total, details) où `details` est
    `[{"exercice_id", "titre", "score", "total"}, ...]` — pas de detail
    par question, une épreuve n'a pas de réponses propres à corriger.
    """
    score = 0.0
    total = 0.0
    details = []
    for composant in exercice.exercices_composes.all():
        total_composant = composant.questions.aggregate(total=Sum("points"))["total"] or 0.0
        evaluation = EvaluationExercice.objects.filter(user=user, exercice=composant).first()
        score_composant = evaluation.score if evaluation else 0.0

        score += score_composant
        total += total_composant

        details.append(
            {
                "exercice_id": composant.id,
                "titre": composant.titre,
                "score": score_composant,
                "total": total_composant,
            }
        )
    return score, total, details


def _detail_tentative_pour_lecture(tentative_reponses, adapter):
    """
    Lit le snapshot d'une tentative quelle que soit sa forme : detail
    question-par-question pour un exercice normal (sous la clé
    `"questions"`, adapté via `adapter` — `_detail_soumission` ou
    `_detail_historique` selon l'appelant) ; liste d'exercices composants
    pour une épreuve (sous la clé `"exercices"`, P6.3 — déjà dans sa forme
    finale, aucun renommage de clé nécessaire, concept nouveau sans
    convention historique à préserver).
    """
    data = tentative_reponses or {}
    if "exercices" in data:
        return data["exercices"]
    return [adapter(d) for d in data.get("questions", [])]


def _verifier_gain_de_rang(user, exercice):
    """
    P6.3 : après chaque soumission, recalcule le classement du département
    de l'exercice et détecte si `user` a gagné des places. Si oui, crée la
    notification `type="classement"` (déjà définie dans
    `apps/notifications/models.py`, jusqu'ici jamais utilisée) et renvoie
    le gain pour l'injecter dans la réponse HTTP de soumission. Retourne
    `None` si pas de gain (rien à ajouter à la réponse).
    """
    gain = ClassementService.recalculer_et_detecter_gain(user, exercice.cours.departement)
    if gain:
        creer_notification(
            utilisateur=user,
            type_notif="classement",
            titre="Vous avez gagné des places au classement !",
            contenu=(
                f"Vous êtes passé du rang {gain['ancien_rang']} au rang "
                f"{gain['nouveau_rang']} dans le classement de votre département."
            ),
            objet_type="Departement",
            objet_id=exercice.cours.departement_id,
        )
    return gain


@extend_schema_view(
    post=extend_schema(
        summary="Sortie anticipée d'un exercice",
        description=(
            "Enregistre une sortie anticipée d'un exercice avec soumission "
            "automatique des réponses déjà fournies (l'apprenant n'a pas cliqué sur "
            "« Valider »). Cette tentative compte dans le nombre de tentatives "
            "autorisées, sauf si celles-ci sont déjà épuisées."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class SortirExerciceView(APIView):
    """
    POST /api/exercices/<exercice_id>/sortir/
    Gère la sortie anticipée d'un exercice avec soumission automatique.

    Comportement (Partie 1.2 du cahier des charges) :
    - La tentative est enregistrée dans ExerciceTentative avec les réponses
      déjà fournies, qu'elle soit complète ou non (est_soumise=False pour
      distinguer une auto-soumission d'une validation explicite).
    - Cette tentative compte dans le nombre de tentatives autorisées.
    - Si les tentatives sont déjà épuisées, on ne recrée pas de tentative
      supplémentaire : on renvoie simplement l'état "épuisé".
    """

    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Exercice
    acces_action = "soumettre"

    @transaction.atomic
    def post(self, request, exercice_id):
        user = request.user
        exercice = get_object_or_404(Exercice, id=exercice_id)
        self.check_object_permissions(request, exercice)

        # Récupérer la session en cours
        session = SessionExercice.objects.filter(
            user=user, exercice=exercice, termine=False
        ).first()

        if not session:
            return Response(
                {"detail": "Aucune session en cours pour cet exercice."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Tentatives déjà enregistrées (source de vérité = ExerciceTentative)
        nb_tentatives = ExerciceTentative.objects.filter(apprenant=user, exercice=exercice).count()

        if nb_tentatives >= exercice.tentatives_max:
            session.termine = True
            session.save(update_fields=["termine"])
            return Response(
                {
                    "detail": "Nombre maximum de tentatives déjà atteint. Cette sortie n'est pas comptée.",
                    "tentatives_epuisees": True,
                },
                status=status.HTTP_200_OK,
            )

        # P6.3 : une épreuve n'a pas de réponses propres à corriger — sa
        # note est la somme des scores actuels de ses exercices composés.
        if exercice.est_epreuve:
            score, total, details = _corriger_epreuve_composee(exercice, user)
            snapshot_key = "exercices"
            est_terminee = True
            detail_http = details
        else:
            reponses_brutes = request.data.get("reponses", {})
            score, total, details = _corriger_reponses_exercice(exercice, reponses_brutes)
            snapshot_key = "questions"
            est_terminee = len(reponses_brutes) >= exercice.questions.count()
            detail_http = [_detail_soumission(d) for d in details]

        tentative = ExerciceTentative.objects.create(
            apprenant=user,
            exercice=exercice,
            tentative_numero=ExerciceTentative.prochain_numero(user, exercice),
            # Snapshot auto-suffisant (P6.2) : figé au moment de la
            # tentative, ne dépend plus de l'état futur de Question/Choix.
            reponses={
                snapshot_key: details,
                "score": score,
                "total": total,
                "date": timezone.now().isoformat(),
            },
            score=score,
            total_points=total,
            est_soumise=False,  # sortie anticipée, pas une validation explicite
            est_terminee=est_terminee,
        )

        ClassementService.enregistrer_evaluation_finale(user, exercice, tentative)
        gain_de_rang = _verifier_gain_de_rang(user, exercice)

        note_sur_20 = (score / total) * 20 if total > 0 else 0

        reponse = {
            "score": score,
            "total": total,
            "note": round(note_sur_20, 1),
            "note_sur": 20,
            "detail": detail_http,
            "tentative_numero": tentative.tentative_numero,
            "tentatives_restantes": max(0, exercice.tentatives_max - (nb_tentatives + 1)),
            "message": "Exercice soumis automatiquement avec les réponses actuelles.",
            "auto_soumis": True,
        }
        if gain_de_rang:
            reponse.update(gain_de_rang)

        return Response(reponse, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        summary="Vérifier la progression au classement",
        description=(
            "Vérifie si l'apprenant connecté a gagné des places dans le classement de "
            "son département depuis le dernier calcul, en comparant la progression "
            "hebdomadaire enregistrée. Réservé aux apprenants."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class VerifierProgressionRangView(APIView):
    """
    GET /api/classement/verifier-progression/
    Vérifie si l'apprenant a gagné des places dans son département.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.formation.models import Departement
        from apps.evaluation.models import RangApprenant

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "apprenant":
            return Response({"detail": "Réservé aux apprenants."}, status=403)

        if not profile.cursus:
            return Response({"detail": "Aucun cursus assigné."}, status=404)

        # Récupérer le département principal. `.first()` renvoie déjà None
        # si aucun résultat : pas de try/except nécessaire (une vraie erreur
        # DB doit remonter à EXCEPTION_HANDLER, pas être masquée en "aucun
        # département").
        parcours = Departement.objects.filter(
            parcours__nom=profile.cursus, parcours__type_parcours="cursus"
        ).first()

        if not parcours:
            return Response({"detail": "Aucun département trouvé pour votre cursus."}, status=404)

        # Récupérer le rang actuel
        rang_actuel = RangApprenant.objects.filter(
            apprenant=request.user, departement=parcours
        ).first()

        if not rang_actuel:
            return Response({"detail": "Aucun rang calculé pour vous."}, status=404)

        # Vérifier la progression (comparer avec le dernier calcul)
        # Pour simplifier, on compare avec la dernière valeur de progression
        progression = rang_actuel.progression_semaine

        # Simuler un gain de rang (à adapter selon votre logique)
        rang_ameliore = progression > 0

        return Response(
            {
                "rang": rang_actuel.rang,
                "score": rang_actuel.score,
                "progression": progression,
                "rang_ameliore": rang_ameliore,
                "message": (
                    "Félicitations ! Vous avez gagné des places au classement."
                    if rang_ameliore
                    else ""
                ),
                "departement": {
                    "id": parcours.id,
                    "nom": parcours.nom,
                },
            }
        )


@extend_schema_view(
    get=extend_schema(
        summary="Exercices d'un module",
        description=(
            "Retourne la liste paginée des exercices liés à un module, y compris ceux "
            "rattachés aux leçons de ce module. Peut être filtrée par type d'exercice."
        ),
        tags=["evaluation"],
        parameters=[
            OpenApiParameter(
                "type",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="general | module | lecon | epreuve",
            ),
            *PARAMS_PAGINATION,
        ],
        responses={200: ExerciceSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class ExercicesParModuleView(PaginatedListMixin, APIView):
    """
    GET /api/modules/<module_id>/exercices/
    Retourne tous les exercices liés à un module (y compris ceux des leçons).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, module_id):
        module = get_object_or_404(Module, pk=module_id)

        # Exercices directement liés au module
        exercices_module = Exercice.objects.filter(module=module)

        # Exercices liés aux leçons du module
        lecons_ids = module.lecons.values_list("id", flat=True)
        exercices_lecons = Exercice.objects.filter(lecon_id__in=lecons_ids)

        # Combiner et filtrer par type
        exercices = exercices_module | exercices_lecons
        exercices = exercices.distinct()

        # Filtres supplémentaires
        type_exercice = request.query_params.get("type")
        if type_exercice:
            exercices = exercices.filter(type_exercice=type_exercice)

        page = self.paginate_queryset(exercices)
        serializer = ExerciceSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)


@extend_schema_view(
    patch=extend_schema(
        summary="Modifier un exercice",
        description=(
            "Modifie un exercice existant (supporte l'upload d'une nouvelle image "
            "d'énoncé via `enonce_image`, ou sa suppression en envoyant `'null'`). "
            "Réservé à l'enseignant principal du cours."
        ),
        tags=["evaluation"],
        request={"multipart/form-data": ExerciceCreateSerializer},
        responses={200: ExerciceSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class ModifierExerciceView(APIView):
    """
    PATCH /api/exercices/<exercice_id>/modifier/
    Modifie un exercice existant.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @transaction.atomic
    def patch(self, request, exercice_id):
        exercice = get_object_or_404(Exercice, pk=exercice_id)
        cours = exercice.cours

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut modifier un exercice."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Copier les données
        data = request.data.copy()

        # Gérer l'énoncé image
        if "enonce_image" in request.FILES:
            data["enonce_image"] = request.FILES["enonce_image"]

        # Si enonce_image est null, supprimer l'image existante
        if data.get("enonce_image") == "null":
            data["enonce_image"] = None

        serializer = ExerciceCreateSerializer(exercice, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        enregistrer_activite(
            user=request.user,
            action="exercise_modified",
            description=f"Exercice « {updated.titre} » modifié",
            data={
                "exercice": updated.titre,
                "cours": cours.titre,
            },
            objet_id=updated.id,
            objet_type="Exercice",
        )

        return Response(
            ExerciceSerializer(updated, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    delete=extend_schema(
        summary="Supprimer un exercice",
        description="Supprime un exercice et met à jour le compteur du cours. Réservé à l'enseignant principal du cours.",
        tags=["evaluation"],
        responses={204: None},
        examples=[*ERREURS_ECRITURE],
    ),
)
class SupprimerExerciceView(APIView):
    """
    DELETE /api/exercices/<exercice_id>/supprimer/
    Supprime un exercice.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def delete(self, request, exercice_id):
        exercice = get_object_or_404(Exercice, pk=exercice_id)
        cours = exercice.cours

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut supprimer un exercice."},
                status=status.HTTP_403_FORBIDDEN,
            )

        enregistrer_activite(
            user=request.user,
            action="exercise_deleted",
            description=f"Exercice « {exercice.titre} » supprimé du cours « {cours.titre} »",
            data={
                "exercice": exercice.titre,
                "cours": cours.titre,
            },
            objet_type="Exercice",
        )

        exercice.delete()

        # Mettre à jour le compteur
        cours.nb_devoirs = max(0, cours.nb_devoirs - 1)
        cours.save(update_fields=["nb_devoirs"])

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    post=extend_schema(
        summary="Soumettre une évaluation d'exercice",
        description=(
            "Soumission explicite d'un exercice (l'apprenant clique sur « Valider »), "
            "par opposition à `SortirExerciceView` qui gère la sortie anticipée / "
            "auto-soumission. Si le temps de la session est écoulé, la soumission "
            "est traitée comme automatique."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class SoumettreEvaluationView(APIView):
    """
    POST /api/exercices/<exercice_id>/soumettre/
    Soumission explicite (l'apprenant clique sur "Valider"), par opposition
    à SortirExerciceView qui gère la sortie anticipée / auto-soumission.
    """

    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Exercice
    acces_action = "soumettre"

    @transaction.atomic
    def post(self, request, exercice_id):
        user = request.user
        exercice = get_object_or_404(Exercice, id=exercice_id)
        self.check_object_permissions(request, exercice)

        # Tentatives déjà enregistrées (source de vérité = ExerciceTentative)
        nb_tentatives = ExerciceTentative.objects.filter(apprenant=user, exercice=exercice).count()

        # P6.2 : harmonisé avec SortirExerciceView — une fois les
        # tentatives épuisées, la soumission n'est plus REJETÉE (l'ancien
        # 403 empêchait tout accès) mais acceptée sans effet : aucune
        # nouvelle tentative n'est créée, la note officielle n'est pas
        # modifiée. La correction reste consultable à tout moment via
        # ResultatExerciceView/HistoriqueTentativesExerciceView.
        if nb_tentatives >= exercice.tentatives_max:
            return Response(
                {
                    "detail": f"Nombre maximum de tentatives atteint ({exercice.tentatives_max}). Cette soumission n'est pas comptée.",
                    "tentatives_epuisees": True,
                },
                status=status.HTTP_200_OK,
            )

        # Récupérer / créer la session en cours
        session = SessionExercice.objects.filter(
            user=user, exercice=exercice, termine=False
        ).first()
        if not session:
            session = SessionExercice.objects.create(user=user, exercice=exercice)

        # Vérifier si le temps est écoulé : dans ce cas, la soumission
        # devient une auto-soumission (mêmes règles que SortirExerciceView)
        temps_ecoule = session.temps_restant() <= 0

        # P6.3 : une épreuve n'a pas de réponses propres à corriger — sa
        # note est la somme des scores actuels de ses exercices composés.
        if exercice.est_epreuve:
            score, total, details = _corriger_epreuve_composee(exercice, user)
            snapshot_key = "exercices"
            est_terminee = True
            detail_http = details
        else:
            reponses_brutes = request.data.get("reponses", {})
            score, total, details = _corriger_reponses_exercice(exercice, reponses_brutes)
            snapshot_key = "questions"
            est_terminee = len(reponses_brutes) >= exercice.questions.count()
            detail_http = [_detail_soumission(d) for d in details]

        tentative = ExerciceTentative.objects.create(
            apprenant=user,
            exercice=exercice,
            tentative_numero=ExerciceTentative.prochain_numero(user, exercice),
            # Snapshot auto-suffisant (P6.2), voir SortirExerciceView.
            reponses={
                snapshot_key: details,
                "score": score,
                "total": total,
                "date": timezone.now().isoformat(),
            },
            score=score,
            total_points=total,
            est_soumise=not temps_ecoule,
            est_terminee=est_terminee,
        )

        ClassementService.enregistrer_evaluation_finale(user, exercice, tentative)
        gain_de_rang = _verifier_gain_de_rang(user, exercice)

        session.termine = True
        session.save(update_fields=["termine"])

        note_sur_20 = (score / total) * 20 if total > 0 else 0

        reponse = {
            "score": score,
            "total": total,
            "note": round(note_sur_20, 1),
            "note_sur": 20,
            "detail": detail_http,
            "tentative_numero": tentative.tentative_numero,
            "tentatives_restantes": max(0, exercice.tentatives_max - (nb_tentatives + 1)),
            "message": (
                "Temps écoulé, examen soumis automatiquement."
                if temps_ecoule
                else "Examen soumis avec succès."
            ),
            "auto_soumis": temps_ecoule,
        }
        if gain_de_rang:
            reponse.update(gain_de_rang)

        return Response(reponse, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        summary="Historique des tentatives d'un exercice",
        description=(
            "Retourne l'historique complet des tentatives de l'apprenant connecté sur "
            "un exercice, avec les réponses détaillées question par question "
            "(`ExerciceTentative` est la source de vérité)."
        ),
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class HistoriqueTentativesExerciceView(PaginatedListMixin, APIView):
    """
    GET /api/evaluations/exercice/<exercice_id>/historique/
    Retourne l'historique COMPLET des tentatives d'un apprenant, avec
    réponses détaillées question par question (ExerciceTentative est la
    source de vérité depuis la Partie 1 du cahier des charges).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, exercice_id):
        exercice = get_object_or_404(Exercice, id=exercice_id)
        user = request.user

        tentatives = ExerciceTentative.objects.filter(apprenant=user, exercice=exercice).order_by(
            "-tentative_numero"
        )

        page = self.paginate_queryset(tentatives)

        result = []
        for t in page:
            # P6.2 : snapshot FIGÉ au moment de la tentative — ne re-dérive
            # plus la correction contre l'état actuel de Question/Choix
            # (une modification ultérieure de l'exercice ne change donc
            # plus rétroactivement une correction déjà rendue, et une
            # question supprimée depuis reste visible dans l'historique).
            # P6.3 : ou liste d'exercices composants si c'est une épreuve.
            reponses_detail = _detail_tentative_pour_lecture(t.reponses, _detail_historique)

            result.append(
                {
                    "id": t.id,
                    "tentative_numero": t.tentative_numero,
                    "date": t.date_tentative.isoformat(),
                    "score": t.score,
                    "total": t.total_points,
                    "note_sur_20": (
                        round((t.score / t.total_points) * 20, 1) if t.total_points > 0 else 0
                    ),
                    "est_soumise": t.est_soumise,
                    "est_terminee": t.est_terminee,
                    "reponses": reponses_detail,
                }
            )

        return self.get_paginated_response(result)


@extend_schema_view(
    get=extend_schema(
        summary="Résultat d'un exercice",
        description=(
            "Retourne la note officielle (issue de la dernière tentative) ainsi que "
            "l'historique de toutes les tentatives de l'apprenant connecté pour cet "
            "exercice. 404 si l'apprenant n'a encore aucun résultat."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class ResultatExerciceView(APIView):
    """
    GET /api/evaluations/exercice/<exercice_id>/
    Retourne le dernier résultat avec l'historique des tentatives.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, exercice_id):
        exercice = get_object_or_404(Exercice, id=exercice_id)
        user = request.user

        # Note "officielle" = toujours celle de la dernière tentative
        evaluation = (
            EvaluationExercice.objects.filter(user=user, exercice=exercice)
            .select_related("tentative_finale")
            .first()
        )

        if not evaluation:
            return Response(
                {"detail": "Aucun résultat trouvé pour cet exercice."},
                status=status.HTTP_404_NOT_FOUND,
            )

        tentatives = ExerciceTentative.objects.filter(apprenant=user, exercice=exercice).order_by(
            "-tentative_numero"
        )
        # P6.2 : chaque tentative porte désormais son propre snapshot figé
        # (voir SortirExerciceView/SoumettreEvaluationView) — plus de
        # re-dérivation live contre l'état actuel de Question/Choix.
        historique = [
            {
                "id": t.id,
                "tentative_numero": t.tentative_numero,
                "date": t.date_tentative.isoformat(),
                "score": t.score,
                "total": t.total_points,
                "note_sur_20": (
                    round((t.score / t.total_points) * 20, 1) if t.total_points > 0 else 0
                ),
                "est_soumise": t.est_soumise,
                "reponses": _detail_tentative_pour_lecture(t.reponses, _detail_historique),
            }
            for t in tentatives
        ]

        nb_tentatives = tentatives.count()

        # Détail de la note officielle (dernière tentative valide) — clé
        # `detail` déjà attendue par le Flutter (`_buildDetailQuestion`,
        # jusqu'ici toujours vide faute d'être renvoyée par ce endpoint).
        tentative_finale = evaluation.tentative_finale
        detail_note_officielle = (
            _detail_tentative_pour_lecture(tentative_finale.reponses, _detail_soumission)
            if tentative_finale
            else []
        )

        return Response(
            {
                "exercice_id": exercice.id,
                "exercice_titre": exercice.titre,
                "note": evaluation.score,
                "note_sur": evaluation.total,
                "score": evaluation.score,
                "total": evaluation.total,
                "date": evaluation.date,
                "detail": detail_note_officielle,
                "historique": historique,
                "tentatives_restantes": max(0, exercice.tentatives_max - nb_tentatives),
                "tentatives_max": exercice.tentatives_max,
                "tentatives_epuisees": nb_tentatives >= exercice.tentatives_max,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    get=extend_schema(
        summary="Historique de mes évaluations d'exercices",
        description=(
            "Retourne la liste paginée de toutes les évaluations d'exercices de "
            "l'apprenant connecté (une évaluation par exercice, reflétant sa dernière "
            "tentative), triées par date décroissante."
        ),
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: EvaluationSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class HistoriqueEvaluationsView(PaginatedListMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        evaluations = EvaluationExercice.objects.filter(user=request.user).order_by("-date")
        page = self.paginate_queryset(evaluations)
        serializer = EvaluationSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


@extend_schema_view(
    post=extend_schema(
        summary="Démarrer un exercice",
        description=(
            "Démarre (ou reprend) une session de composition d'exercice : crée une "
            "nouvelle session si aucune n'est en cours ou si la précédente a expiré, "
            "et renvoie le temps restant. Renvoie 403 si le nombre maximum de "
            "tentatives est déjà atteint."
        ),
        tags=["evaluation"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class DemarrerExerciceView(APIView):
    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Exercice
    acces_action = "soumettre"

    def post(self, request, exercice_id):
        user = request.user
        exercice = get_object_or_404(Exercice, id=exercice_id)
        self.check_object_permissions(request, exercice)

        # Vérifier les tentatives déjà faites (source de vérité = ExerciceTentative)
        tentatives = ExerciceTentative.objects.filter(apprenant=user, exercice=exercice).count()

        if tentatives >= exercice.tentatives_max:
            return Response(
                {
                    "detail": f"Nombre maximum de tentatives atteint ({exercice.tentatives_max}).",
                    "tentatives_restantes": 0,
                    "tentatives_max": exercice.tentatives_max,
                    "tentatives_epuisees": True,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Vérifier si une session non terminée existe déjà
        session = SessionExercice.objects.filter(
            user=user, exercice=exercice, termine=False
        ).first()

        if session:
            # Si la session existe mais que le temps est écoulé
            if session.temps_restant() <= 0:
                session.termine = True
                session.save()
                session = None

        # Créer une nouvelle session si nécessaire
        if not session:
            session = SessionExercice.objects.create(user=user, exercice=exercice)

        duree_totale = exercice.duree_minutes * 60
        temps_restant = session.temps_restant()

        return Response(
            {
                "session_id": session.id,
                "debut": session.debut.isoformat(),
                "duree_totale": duree_totale,
                "temps_restant": temps_restant,
                "tentatives_restantes": exercice.tentatives_max - tentatives,
                "tentatives_max": exercice.tentatives_max,
                "tentatives_epuisees": False,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    get=extend_schema(
        summary="Détail d'un exercice pour composition",
        description=(
            "Retourne le détail d'un exercice avec ses questions et choix, ainsi que "
            "le temps restant de la session en cours et le nombre de tentatives "
            "restantes. Note : la réponse inclut `bonne_reponse` par question "
            "(comportement existant, à ne pas exposer tel quel en production)."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class ExerciceDetailView(APIView):
    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Exercice
    acces_action = "voir"

    def get(self, request, exercice_id):
        user = request.user
        exercice = get_object_or_404(
            Exercice.objects.prefetch_related("questions__choix"), id=exercice_id
        )
        self.check_object_permissions(request, exercice)

        # Vérifier si une session est en cours
        session = SessionExercice.objects.filter(
            user=user, exercice=exercice, termine=False
        ).first()

        # Calculer le temps restant
        duree_totale = exercice.duree_minutes * 60
        temps_restant = duree_totale

        if session:
            temps_restant = session.temps_restant()
            # Si le temps est écoulé, marquer la session comme terminée
            if temps_restant <= 0:
                session.termine = True
                session.save()
                temps_restant = 0

        # Compter les tentatives déjà faites
        tentatives = EvaluationExercice.objects.filter(user=user, exercice=exercice).count()

        tentatives_restantes = max(0, exercice.tentatives_max - tentatives)

        # Sérialiser les questions
        questions_data = []
        for q in exercice.questions.all():
            q_data = {
                "id": q.id,
                "text": q.text,
                "type": q.type_question,
                "points": q.points,
                "bonne_reponse": q.bonne_reponse,  # À ne pas exposer en prod
                # P6.3 : complet (id/est_correct) et ordonné (Choix.Meta.ordering),
                # même correctif que QuestionSerializer.get_choix — doublon de
                # logique appauvrie corrigé ici aussi (règle 1).
                "choix": (
                    [
                        {"id": c.id, "texte": c.texte, "est_correct": c.est_correct}
                        for c in q.choix.all()
                    ]
                    if q.type_question == "qcm"
                    else []
                ),
            }
            questions_data.append(q_data)

        return Response(
            {
                "id": exercice.id,
                "titre": exercice.titre,
                "enonce": exercice.enonce,
                "etoiles": exercice.etoiles,
                "duree_minutes": exercice.duree_minutes,
                "duree_totale": duree_totale,
                "temps_restant": temps_restant,
                "tentatives_max": exercice.tentatives_max,
                "tentatives_restantes": tentatives_restantes,
                "questions": questions_data,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Ajouter une question à un exercice",
        description="Ajoute une question à un exercice existant. Réservé à l'enseignant principal du cours.",
        tags=["evaluation"],
        request=QuestionCreateSerializer,
        responses={201: QuestionSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AjouterQuestionView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request, exercice_id):
        exercice = get_object_or_404(Exercice, pk=exercice_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if exercice.cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut ajouter des questions."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = QuestionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.save(exercice=exercice)
        return Response(
            QuestionSerializer(question).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    get=extend_schema(
        summary="Lister les questions d'un exercice",
        description="Retourne la liste paginée des questions d'un exercice avec leurs choix de réponse.",
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: QuestionSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class ListeQuestionsExerciceView(PaginatedListMixin, APIView):
    """
    GET /api/exercices/<exercice_id>/questions/
    Retourne toutes les questions d'un exercice avec leurs choix.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, exercice_id):
        exercice = get_object_or_404(Exercice, pk=exercice_id)
        questions = Question.objects.filter(exercice=exercice).prefetch_related("choix")
        page = self.paginate_queryset(questions)
        return self.get_paginated_response(QuestionSerializer(page, many=True).data)
