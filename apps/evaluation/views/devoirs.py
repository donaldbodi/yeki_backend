from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.core.exceptions import ConflictError
from apps.core.models import enregistrer_activite
from apps.core.pagination import PaginatedListMixin
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
)
from apps.core.services import _get_client_ip
from apps.formation.models import Cours
from apps.notifications.models import creer_notification
from apps.evaluation.models import (
    Devoir,
    EnonceDevoir,
    QuestionDevoir,
    ChoixReponse,
    SoumissionDevoir,
    ReponseDevoir,
)
from apps.evaluation.serializers import (
    DevoirListSerializer,
    DevoirDetailSerializer,
    DevoirCreateSerializer,
    DevoirUpdateSerializer,
    EnonceDevoirSerializer,
    ReponseSubmitSerializer,
    SoumissionDetailSerializer,
    SoumissionResultatSerializer,
    QuestionDevoirCreateUpdateSerializer,
    QuestionDevoirAdminSerializer,
)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les devoirs publiés",
        description=(
            "Retourne la liste paginée des devoirs publiés (`est_publie=True`), "
            "triés par date limite décroissante. Peut être filtrée par type de devoir, "
            "matière, niveau, statut de la soumission de l'apprenant connecté, ou "
            "cours lié."
        ),
        tags=["evaluation"],
        parameters=[
            OpenApiParameter(
                "type_devoir",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="cursus | concours | formation_classique | formation_metier | olympiade",
            ),
            OpenApiParameter(
                "matiere",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Ex : Mathématiques, Physique…",
            ),
            OpenApiParameter(
                "niveau",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Ex : Terminale, Licence 1…",
            ),
            OpenApiParameter(
                "statut",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="non_commence | en_cours | soumis | corrige (statut de ma soumission)",
            ),
            OpenApiParameter(
                "cours_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtrer par cours lié.",
            ),
            *PARAMS_PAGINATION,
        ],
        responses={200: DevoirListSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class ListeDevoirsView(PaginatedListMixin, APIView):
    """
    GET /api/devoirs/
    Paramètres query optionnels :
      - type_devoir   : cursus | concours | formation_classique | formation_metier | olympiade
      - matiere       : Mathématiques | Physique | …
      - niveau        : Terminale | Licence 1 | …
      - statut        : non_commence | en_cours | soumis | corrige
      - cours_id      : filtrer par cours lié
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Devoir.objects.filter(est_publie=True).order_by("-date_limite")

        # ── Filtres ──────────────────────────────────────────────
        type_devoir = request.query_params.get("type_devoir")
        matiere = request.query_params.get("matiere")
        niveau = request.query_params.get("niveau")
        statut_filtre = request.query_params.get("statut")
        cours_id = request.query_params.get("cours_id")

        if type_devoir:
            qs = qs.filter(type_devoir=type_devoir)
        if matiere:
            qs = qs.filter(matiere=matiere)
        if niveau:
            qs = qs.filter(niveau=niveau)
        if cours_id:
            qs = qs.filter(cours_lie_id=cours_id)

        # Filtre par statut apprenant (post-queryset)
        if statut_filtre:
            soumissions = SoumissionDevoir.objects.filter(utilisateur=request.user).values_list(
                "devoir_id", "statut"
            )
            soum_map = {d_id: s for d_id, s in soumissions}

            if statut_filtre == "non_commence":
                ids_soumis = set(soum_map.keys())
                qs = qs.exclude(id__in=ids_soumis)
            else:
                ids = [d_id for d_id, s in soum_map.items() if s == statut_filtre]
                qs = qs.filter(id__in=ids)

        page = self.paginate_queryset(qs)
        serializer = DevoirListSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)


@extend_schema_view(
    get=extend_schema(
        summary="Détail d'un devoir",
        description=(
            "Retourne le détail complet d'un devoir publié. Renvoie 403 si le devoir "
            "n'est pas encore ouvert (date de début non atteinte) et que l'apprenant "
            "n'a pas déjà de soumission en cours."
        ),
        tags=["evaluation"],
        responses={200: DevoirDetailSerializer},
        examples=[*ERREURS_COURANTES],
    ),
)
class DetailDevoirView(APIView):
    """GET /api/devoirs/<id>/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id, est_publie=True)

        # Vérifier que le devoir est ouvert (ou déjà commencé par l'apprenant)
        soum = SoumissionDevoir.objects.filter(utilisateur=request.user, devoir=devoir).first()

        if not devoir.est_ouvert and not soum:
            return Response(
                {"detail": "Ce devoir n'est pas encore accessible."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = DevoirDetailSerializer(devoir, context={"request": request})
        return Response(serializer.data)


@extend_schema_view(
    post=extend_schema(
        summary="Démarrer un devoir",
        description=(
            "Démarre (ou reprend) la composition d'un devoir : crée la soumission de "
            "l'apprenant si elle n'existe pas encore, et renvoie le temps restant. "
            "Si le nombre de sorties a déjà atteint le maximum autorisé, le devoir est "
            "soumis automatiquement. Réponse : `{'soumission': <SoumissionDetailSerializer>, "
            "'temps_restant_secondes': int}`."
        ),
        tags=["evaluation"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class DemarrerDevoirView(APIView):
    """POST /api/devoirs/<id>/demarrer/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id, est_publie=True)

        # Vérifier que la date de début est passée
        if timezone.now() < devoir.date_debut:
            return Response(
                {
                    "detail": f"Ce devoir sera disponible à partir du {devoir.date_debut.strftime('%d/%m/%Y à %H:%M')}."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if not devoir.est_ouvert:
            return Response(
                {"detail": "Le devoir n'est plus accessible."}, status=status.HTTP_403_FORBIDDEN
            )

        # Vérifier les sorties déjà effectuées
        soum, created = SoumissionDevoir.objects.get_or_create(
            utilisateur=request.user,
            devoir=devoir,
            defaults={
                "statut": "en_cours",
                "ip_address": self._get_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:500],
            },
        )

        if not created and soum.statut in ["soumis", "corrige"]:
            return Response(
                {"detail": "Vous avez déjà soumis ce devoir."}, status=status.HTTP_400_BAD_REQUEST
            )

        # Si le nombre de sorties a atteint le maximum, soumettre automatiquement
        if soum.sorties >= devoir.tentatives_max:
            soum.statut = "soumis"
            soum.soumis_le = timezone.now()
            soum.save()
            return Response(
                {"detail": "Nombre maximum de sorties atteint. Devoir soumis automatiquement."},
                status=status.HTTP_200_OK,
            )

        serializer = SoumissionDetailSerializer(soum, context={"request": request})
        return Response(
            {
                "soumission": serializer.data,
                "temps_restant_secondes": soum.temps_restant_secondes(),
            }
        )

    def _get_ip(self, request):
        return _get_client_ip(request)


@extend_schema_view(
    post=extend_schema(
        summary="Signaler une sortie du devoir (vue non routée)",
        description=(
            "Enregistre une sortie du devoir. Si le nombre de sorties atteint le "
            "maximum autorisé, les réponses fournies dans le corps sont enregistrées "
            "et le devoir est soumis automatiquement. "
            "Vue orpheline (non routée dans les urls actuelles) — doublon fonctionnel "
            "probable de `SignalerFocusDevoirView` ; conservée telle quelle."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
# TODO(audit): vue orpheline, non routée (docs/AUDIT_BACKEND.md §2.2) —
# doublon fonctionnel quasi certain de SignalerFocusDevoirView (routée sur
# devoirs/<id>/focus-perdu/). Conservée telle quelle.
class SortirDevoirView(APIView):
    """
    POST /api/devoirs/<id>/sortir/
    Enregistre une sortie du devoir. Si le nombre de sorties atteint le maximum,
    soumet automatiquement le devoir.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id, est_publie=True)

        soum = get_object_or_404(
            SoumissionDevoir, devoir=devoir, utilisateur=request.user, statut="en_cours"
        )

        # Incrémenter le compteur de sorties
        soum.sorties += 1
        soum.save(update_fields=["sorties"])

        # Si le nombre de sorties atteint le maximum, soumettre automatiquement
        if soum.sorties >= devoir.tentatives_max:
            # Récupérer les réponses actuelles
            reponses = request.data.get("reponses", {})

            # Enregistrer les réponses
            for question in devoir.questions.all():
                user_rep = reponses.get(str(question.id), "").strip()
                repobj, _ = ReponseDevoir.objects.get_or_create(soumission=soum, question=question)
                repobj.reponse = user_rep
                repobj.save()

            soum.statut = "soumis"
            soum.soumis_le = timezone.now()
            soum.save(update_fields=["statut", "soumis_le"])

            return Response(
                {
                    "detail": "Nombre maximum de sorties atteint. Devoir soumis automatiquement.",
                    "force_submit": True,
                    "sorties": soum.sorties,
                    "sorties_max": devoir.tentatives_max,
                }
            )

        return Response(
            {
                "detail": f"Sortie enregistrée ({soum.sorties}/{devoir.tentatives_max}).",
                "sorties": soum.sorties,
                "sorties_max": devoir.tentatives_max,
                "force_submit": False,
            }
        )


@extend_schema_view(
    post=extend_schema(
        summary="Soumettre un devoir",
        description=(
            "Soumission explicite d'un devoir par l'apprenant : enregistre les réponses "
            "fournies, corrige automatiquement les QCM (et les questions texte si le "
            "devoir est en correction automatique), puis calcule la note si applicable. "
            "Si le temps imparti est écoulé, le devoir est auto-soumis sans correction "
            "immédiate."
        ),
        tags=["evaluation"],
        request=ReponseSubmitSerializer,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class SoumettreDevoirView(APIView):
    """POST /api/devoirs/<id>/soumettre/"""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)
        soum = get_object_or_404(SoumissionDevoir, devoir=devoir, utilisateur=request.user)

        if soum.statut in ["soumis", "corrige"]:
            return Response({"detail": "Devoir déjà soumis."}, status=status.HTTP_400_BAD_REQUEST)

        # Vérifier chrono
        if soum.temps_restant_secondes() <= 0:
            soum.statut = "soumis"
            soum.soumis_le = timezone.now()
            soum.save()
            return Response({"detail": "Temps écoulé. Devoir auto-soumis."})

        serializer_in = ReponseSubmitSerializer(data=request.data)
        serializer_in.is_valid(raise_exception=True)
        reponses = serializer_in.validated_data["reponses"]

        # ── Enregistrer les réponses & corriger les QCM ──────────
        score = 0.0
        total = 0.0
        # TODO(pré-existant, non corrigé — "déplacer, ne pas réécrire") :
        # `has_texte` est mis à True plus bas mais n'est jamais relu (repéré
        # en P1.6 via ruff F841) — semble être le reliquat d'un signal
        # "nécessite correction manuelle" jamais branché sur la soumission.
        has_texte = False  # noqa: F841

        for question in devoir.questions.prefetch_related("choix").all():
            total += question.points
            user_rep = reponses.get(str(question.id), "").strip()

            repobj, _ = ReponseDevoir.objects.get_or_create(soumission=soum, question=question)

            if question.type_question == "qcm":
                # TODO(pré-existant, non corrigé — "déplacer, ne pas
                # réécrire") : `choix_correct` est calculé puis jamais utilisé
                # (repéré en P1.6 via ruff F841) — la correction se fait déjà
                # correctement via `choix_selectionne.est_correct` ci-dessous,
                # mais ce calcul mort suggère une logique de vérification
                # croisée jamais branchée ou retirée par erreur.
                choix_correct = question.choix.filter(est_correct=True).first()  # noqa: F841
                choix_selectionne = question.choix.filter(texte=user_rep).first()
                repobj.reponse = user_rep
                repobj.choix = choix_selectionne
                if choix_selectionne and choix_selectionne.est_correct:
                    repobj.est_correct = True
                    repobj.points_obtenus = question.points
                    score += question.points
                else:
                    repobj.est_correct = False
                    repobj.points_obtenus = 0
            else:
                repobj.reponse = user_rep
                # Pour correction auto, comparer avec reponse_attendue
                if devoir.type_correction == "auto":
                    repobj.est_correct = (
                        user_rep.strip().lower() == question.reponse_attendue.strip().lower()
                    )
                    repobj.points_obtenus = question.points if repobj.est_correct else 0
                    if repobj.est_correct:
                        score += question.points
                else:
                    repobj.est_correct = None  # correction manuelle
                has_texte = True  # noqa: F841 — voir TODO plus haut

            repobj.save()

        # ── Mise à jour soumission ────────────────────────────────
        now = timezone.now()
        soum.soumis_le = now
        soum.statut = "en_retard" if soum.est_en_retard else "soumis"

        if devoir.type_correction == "auto":
            # QCM ET texte (comparaison exacte à reponse_attendue) sont
            # déjà corrigés dans la boucle ci-dessus : on enregistre la
            # note dans tous les cas, qu'il y ait ou non des questions
            # texte (correction précédente : la note n'était enregistrée
            # que pour les devoirs 100% QCM, perdant le score des devoirs
            # mixtes QCM+texte en correction automatique).
            note = round((score / total) * devoir.note_sur, 2) if total > 0 else 0
            soum.note = note
            soum.statut = "corrige"
            soum.corrige_le = now

        soum.save()

        return Response(
            {
                "statut": soum.statut,
                "note": soum.note,
                "note_sur": devoir.note_sur,
                "en_retard": soum.est_en_retard,
                "message": "Devoir soumis avec succès.",
            }
        )


@extend_schema_view(
    get=extend_schema(
        summary="Résultat d'un devoir",
        description=(
            "Retourne le résultat de la soumission de l'apprenant connecté pour ce "
            "devoir. Renvoie 404 si le devoir est encore en cours de composition ou si "
            "aucun résultat n'est disponible, et 202 si la soumission attend encore la "
            "correction de l'enseignant."
        ),
        tags=["evaluation"],
        responses={200: SoumissionResultatSerializer},
        examples=[*ERREURS_COURANTES],
    ),
)
class ResultatDevoirView(APIView):
    """GET /api/devoirs/<id>/resultat/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, devoir_id):
        soum = get_object_or_404(SoumissionDevoir, devoir_id=devoir_id, utilisateur=request.user)

        if soum.statut == "en_cours":
            return Response(
                {"detail": "Devoir encore en cours de composition."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if soum.statut == "soumis":
            return Response(
                {"detail": "Résultat en attente de correction par l'enseignant."},
                status=status.HTTP_202_ACCEPTED,
            )
        if soum.statut not in ["corrige", "en_retard"]:
            return Response(
                {"detail": "Résultat pas encore disponible."}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = SoumissionResultatSerializer(soum, context={"request": request})
        return Response(serializer.data)


@extend_schema_view(
    post=extend_schema(
        summary="Dupliquer un devoir (vue non routée)",
        description=(
            "Crée une copie non publiée d'un devoir existant, avec toutes ses "
            "questions et choix de réponse. Réservé à l'enseignant principal du cours "
            "lié (ou à l'organisateur si c'est un devoir d'olympiade). "
            "Vue orpheline (non routée dans les urls actuelles)."
        ),
        tags=["evaluation"],
        responses={201: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
# TODO(audit): vue orpheline, non routée (docs/AUDIT_BACKEND.md §2.2).
class DupliquerDevoirView(APIView):
    """
    POST /api/devoirs/<id>/dupliquer/
    Crée une copie d'un devoir existant avec toutes ses questions.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, devoir_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        source = get_object_or_404(Devoir, pk=devoir_id)

        # Vérifier que l'utilisateur est autorisé à gérer ce devoir
        if not _profile_autorise_gerer_devoir(source, profile):
            return Response(
                {"detail": "Seul l'enseignant principal peut dupliquer ce devoir."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Copier les champs de base
        nouveau_devoir = Devoir.objects.create(
            titre=f"Copie de {source.titre}",
            description=source.description,
            type_devoir=source.type_devoir,
            enonce=source.enonce,
            date_debut=source.date_debut,
            date_limite=source.date_limite,
            duree_minutes=source.duree_minutes,
            note_sur=source.note_sur,
            coefficient=source.coefficient,
            tentatives_max=source.tentatives_max,
            concours_lie=source.concours_lie,
            formation_liee=source.formation_liee,
            cours_lie=source.cours_lie,
            est_publie=False,  # Nouveau devoir non publié
            acces_restreint=source.acces_restreint,
            type_correction=source.type_correction,
            enonces_supplementaires=source.enonces_supplementaires,
            cree_par=profile,
            source_devoir=source,
        )

        # P2.3 : dupliquer les EnonceDevoir de la source (pas seulement les
        # champs dépréciés enonce/enonces_supplementaires) pour que le
        # nouveau devoir ait une structure d'énoncés/questions cohérente
        # dès sa création.
        mapping_enonces = {}
        for enonce_src in source.enonces.all():
            mapping_enonces[enonce_src.id] = EnonceDevoir.objects.create(
                devoir=nouveau_devoir, contenu=enonce_src.contenu, ordre=enonce_src.ordre
            )

        # Copier les questions
        for q in source.questions.all():
            nouvelle_question = QuestionDevoir.objects.create(
                devoir=nouveau_devoir,
                enonce=q.enonce,
                enonce_devoir=mapping_enonces.get(q.enonce_devoir_id),
                type_question=q.type_question,
                points=q.points,
                ordre=q.ordre,
                reponse_attendue=q.reponse_attendue,
                reponse_exemple=q.reponse_exemple,
            )
            # Copier les choix
            for choix in q.choix.all():
                ChoixReponse.objects.create(
                    question=nouvelle_question,
                    texte=choix.texte,
                    est_correct=choix.est_correct,
                )

        return Response(
            {
                "detail": "Devoir dupliqué avec succès.",
                "id": nouveau_devoir.id,
                "titre": nouveau_devoir.titre,
                "nb_questions": nouveau_devoir.questions.count(),
            },
            status=status.HTTP_201_CREATED,
        )


def _profile_autorise_gerer_devoir(devoir, profile) -> bool:
    """
    Détermine si `profile` est autorisé à gérer ce devoir (questions,
    publication, soumissions, statistiques).

    - Devoir lié à un cours (cursus/concours/formation) → l'enseignant
      principal de ce cours.
    - Devoir d'olympiade (cours_lie=None, cf. CreerOlympiadeParCadreView)
      → l'organisateur (enseignant_cadre) de l'olympiade liée.
      Avant cette correction, `cours_lie` étant toujours None pour un
      devoir d'olympiade, cette vérification renvoyait systématiquement
      403 et empêchait le cadre de gérer sa propre olympiade.
    """
    cours = devoir.cours_lie
    if cours is not None:
        return cours.enseignant_principal == profile
    olympiade = getattr(devoir, "olympiade_config", None)
    if olympiade is not None:
        return olympiade.organisateur == profile
    return False


@extend_schema_view(
    patch=extend_schema(
        summary="Modifier une question de devoir (vue non routée)",
        description=(
            "Modifie une question d'un devoir non encore publié. Réservé à "
            "l'enseignant principal du cours lié. Vue orpheline (non routée dans les "
            "urls actuelles)."
        ),
        tags=["evaluation"],
        request=QuestionDevoirCreateUpdateSerializer,
        responses={200: QuestionDevoirAdminSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
# TODO(audit): vue orpheline, non routée (docs/AUDIT_BACKEND.md §2.2).
class ModifierQuestionDevoirView(APIView):
    """
    PATCH /api/devoirs/questions/<question_id>/modifier/
    Modifie une question d'un devoir.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, question_id):
        question = get_object_or_404(QuestionDevoir, pk=question_id)
        devoir = question.devoir

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        # Vérifier que l'utilisateur est l'enseignant principal
        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Seul l'enseignant principal peut modifier une question."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Vérifier que le devoir n'est pas publié
        if devoir.est_publie:
            return Response(
                {"detail": "Impossible de modifier une question d'un devoir déjà publié."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = QuestionDevoirCreateUpdateSerializer(
            question,
            data=request.data,
            partial=True,
            context={"type_correction": devoir.type_correction},
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(QuestionDevoirAdminSerializer(updated).data, status=status.HTTP_200_OK)


@extend_schema_view(
    delete=extend_schema(
        summary="Supprimer une question de devoir (vue non routée)",
        description=(
            "Supprime une question d'un devoir non encore publié. Réservé à "
            "l'enseignant principal du cours lié. Vue orpheline (non routée dans les "
            "urls actuelles)."
        ),
        tags=["evaluation"],
        responses={204: None},
        examples=[*ERREURS_ECRITURE],
    ),
)
# TODO(audit): vue orpheline, non routée (docs/AUDIT_BACKEND.md §2.2).
class SupprimerQuestionDevoirView(APIView):
    """
    DELETE /api/devoirs/questions/<question_id>/supprimer/
    Supprime une question d'un devoir.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, question_id):
        question = get_object_or_404(QuestionDevoir, pk=question_id)
        devoir = question.devoir

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        # Vérifier que l'utilisateur est l'enseignant principal
        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Seul l'enseignant principal peut supprimer une question."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Vérifier que le devoir n'est pas publié
        if devoir.est_publie:
            return Response(
                {"detail": "Impossible de supprimer une question d'un devoir déjà publié."},
                status=status.HTTP_403_FORBIDDEN,
            )

        question.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    patch=extend_schema(
        summary="Modifier un devoir",
        description=(
            "Modifie les champs d'un devoir existant. Réservé à l'enseignant "
            "principal du cours lié (ou à l'organisateur pour un devoir d'olympiade). "
            "Contient un bug pré-existant documenté (variable `cours` non définie) — "
            "voir le TODO ci-dessous, non corrigé dans cette tâche de documentation."
        ),
        tags=["evaluation"],
        request=DevoirUpdateSerializer,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class ModifierDevoirView(APIView):
    """
    PATCH /api/devoirs/<devoir_id>/modifier/
    Permet à l'enseignant principal de modifier un devoir.

    # TODO(bug pré-existant, non corrigé — "déplacer, ne pas réécrire") :
    # `cours` n'est jamais défini dans cette méthode (seul `devoir` l'est).
    # `cours.titre` ci-dessous lève donc un NameError à chaque appel réel
    # de cet endpoint. Bug présent tel quel avant l'éclatement de
    # yeki/views.py — signalé ici, à corriger dans une tâche dédiée.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Seul l'enseignant principal du cours peut modifier ce devoir."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = DevoirUpdateSerializer(devoir, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        enregistrer_activite(
            user=request.user,
            action="homework_modified",
            description=f"Devoir « {updated.titre} » modifié",
            data={
                "devoir": updated.titre,
                "cours": cours.titre,  # noqa: F821 — bug pré-existant documenté ci-dessus
            },
            objet_id=updated.id,
            objet_type="Devoir",
        )

        return Response(
            {
                "id": updated.id,
                "titre": updated.titre,
                "description": updated.description,
                "date_debut": updated.date_debut.isoformat() if updated.date_debut else None,
                "date_limite": updated.date_limite.isoformat() if updated.date_limite else None,
                "est_publie": updated.est_publie,
                "nb_questions": updated.questions.count(),
                "note_sur": float(updated.note_sur),
                "detail": "Devoir modifié avec succès.",
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Publier un devoir (vue non routée)",
        description=(
            "Publie un devoir (le rend accessible aux apprenants et non modifiable), "
            "et notifie les apprenants du cours concerné. Réservé à l'enseignant "
            "principal du cours lié. Vue orpheline (non routée) contenant un bug "
            "pré-existant documenté (variable `cours` non définie) — non corrigé "
            "dans cette tâche de documentation."
        ),
        tags=["evaluation"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
# TODO(audit): vue orpheline, non routée (docs/AUDIT_BACKEND.md §2.2).
# TODO(bug pré-existant, non corrigé — "déplacer, ne pas réécrire") : `cours`
# n'est jamais défini dans cette méthode. `cours.titre`, `Cours.nb_devoirs = ...`
# (affectation sur la CLASSE, pas une instance — no-op), `cours.save(...)` et
# `cours.departement...` lèvent tous un NameError/comportement incorrect dès
# le premier appel réel. Bug présent tel quel avant l'éclatement de
# yeki/views.py — signalé ici, à corriger dans une tâche dédiée.
class PublierDevoirView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Seul l'enseignant principal du cours peut publier ce devoir."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if devoir.est_publie:
            return Response({"detail": "Ce devoir est déjà publié."}, status=400)

        if not devoir.questions.exists():
            return Response(
                {"detail": "Le devoir doit contenir au moins une question avant d'être publié."},
                status=400,
            )

        devoir.est_publie = True
        devoir.save(update_fields=["est_publie"])

        Cours.nb_devoirs = Devoir.objects.filter(
            cours_lie=cours, est_publie=True  # noqa: F821 — bug pré-existant documenté ci-dessus
        ).count()
        cours.save(update_fields=["nb_devoirs"])  # noqa: F821 — idem

        enregistrer_activite(
            user=request.user,
            action="homework_published",
            description=f"Devoir « {devoir.titre} » publié",
            data={
                "devoir": devoir.titre,
                "cours": cours.titre,  # noqa: F821 — idem
            },
            objet_id=devoir.id,
            objet_type="Devoir",
        )

        # Créer des notifications pour les apprenants du cours
        apprenants = Profile.objects.filter(
            user_type="apprenant",
            cursus=cours.departement.parcours.nom,  # noqa: F821 — idem
            is_active=True,
        ).select_related("user")

        for apprenant in apprenants:
            creer_notification(
                utilisateur=apprenant.user,
                type_notif="devoir",
                titre=f"Nouveau devoir : {devoir.titre}",
                contenu=f"Le devoir '{devoir.titre}' est maintenant disponible dans le cours '{cours.titre}'.",  # noqa: F821 — idem
                objet_id=devoir.id,
                objet_type="Devoir",
                action_url=f"/devoirs/{devoir.id}/composer",
            )

        return Response(
            {
                "detail": "Devoir publié avec succès. Il ne peut plus être modifié.",
                "id": devoir.id,
                "est_publie": True,
                "message": "Une fois publié, vous ne pouvez plus ajouter ou modifier les questions.",
            },
            status=200,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Signaler une perte de focus pendant un devoir",
        description=(
            "Appelé par l'application mobile à chaque fois que l'apprenant quitte "
            "l'application pendant la composition d'un devoir. Marque la soumission "
            "comme suspecte à partir de 5 pertes de focus."
        ),
        tags=["evaluation"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class SignalerFocusDevoirView(APIView):
    """
    POST /api/devoirs/<id>/focus-perdu/
    Appelé par Flutter quand l'apprenant quitte l'app pendant la composition.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, devoir_id):
        soum = get_object_or_404(
            SoumissionDevoir, devoir_id=devoir_id, utilisateur=request.user, statut="en_cours"
        )
        soum.nb_focus_perdu += 1

        # Marquer suspect si trop de sorties
        if soum.nb_focus_perdu >= 5:
            soum.est_suspecte = True

        soum.save(update_fields=["nb_focus_perdu", "est_suspecte"])
        return Response({"nb_focus_perdu": soum.nb_focus_perdu})


@extend_schema_view(
    get=extend_schema(
        summary="Mes soumissions de devoirs",
        description=(
            "Retourne la liste paginée de toutes les soumissions de devoirs de "
            "l'apprenant connecté, triées par date de début décroissante."
        ),
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: SoumissionDetailSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class MesSoumissionsView(PaginatedListMixin, APIView):
    """GET /api/devoirs/mes-soumissions/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        soumissions = (
            SoumissionDevoir.objects.filter(utilisateur=request.user)
            .select_related("devoir")
            .order_by("-debut")
        )

        page = self.paginate_queryset(soumissions)
        serializer = SoumissionDetailSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)


@extend_schema_view(
    get=extend_schema(
        summary="Devoirs d'un cours",
        description=(
            "Retourne les devoirs liés à un cours donné, avec le statut de soumission "
            "de l'apprenant connecté pour chacun. Pour l'enseignant principal du cours "
            "(ou un enseignant cadre/admin), inclut aussi les devoirs non publiés et "
            "des statistiques globales (nombre de soumissions, corrigés, moyenne)."
        ),
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class DevoirsCoursView(PaginatedListMixin, APIView):
    """
    GET /api/cours/<cours_id>/devoirs/
    Retourne les devoirs liés à un cours spécifique avec le statut de l'apprenant.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        # Vérifier si l'utilisateur est enseignant principal du cours
        is_enseignant = profile.user_type in [
            "enseignant_principal",
            "enseignant_cadre",
            "enseignant_admin",
            "admin",
        ] and (
            cours.enseignant_principal == profile
            or profile.user_type in ["enseignant_cadre", "enseignant_admin", "admin"]
        )

        # Base queryset
        if is_enseignant:
            # Enseignant: voir tous les devoirs (publiés ou non)
            devoirs = Devoir.objects.filter(cours_lie=cours).order_by("-date_creation")
        else:
            # Apprenant: voir seulement les devoirs publiés
            devoirs = Devoir.objects.filter(cours_lie=cours, est_publie=True).order_by(
                "-date_creation"
            )

        page = self.paginate_queryset(devoirs)

        result = []
        for devoir in page:
            # Chercher la soumission de l'utilisateur
            soumission = SoumissionDevoir.objects.filter(
                devoir=devoir,
                utilisateur=request.user,
            ).first()

            soumission_data = None
            if soumission:
                soumission_data = {
                    "id": soumission.id,
                    "statut": soumission.statut,
                    "note": float(soumission.note) if soumission.note is not None else None,
                    "soumis_le": soumission.soumis_le.isoformat() if soumission.soumis_le else None,
                    "est_corrige": soumission.statut == "corrige",
                    "commentaire": soumission.commentaire or "",
                }

            # Pour l'enseignant: compter le nombre de soumissions
            stats = None
            if is_enseignant:
                nb_soumissions = SoumissionDevoir.objects.filter(devoir=devoir).count()
                nb_corriges = SoumissionDevoir.objects.filter(
                    devoir=devoir, statut="corrige"
                ).count()

                # Moyenne des notes
                notes = SoumissionDevoir.objects.filter(
                    devoir=devoir, note__isnull=False
                ).values_list("note", flat=True)
                moyenne = sum(notes) / len(notes) if notes else 0.0

                stats = {
                    "nb_soumissions": nb_soumissions,
                    "nb_corriges": nb_corriges,
                    "moyenne": round(moyenne, 2),
                }

            result.append(
                {
                    "id": devoir.id,
                    "titre": devoir.titre,
                    "description": devoir.description,
                    "date_debut": devoir.date_debut.isoformat() if devoir.date_debut else None,
                    "date_limite": devoir.date_limite.isoformat() if devoir.date_limite else None,
                    "est_ouvert": devoir.est_ouvert,
                    "est_expire": devoir.est_expire,
                    "nb_questions": devoir.questions.count(),
                    "note_sur": float(devoir.note_sur),
                    "duree_minutes": devoir.duree_minutes,
                    "tentatives_max": devoir.tentatives_max,
                    "est_publie": devoir.est_publie,
                    "type_correction": getattr(devoir, "type_correction", "auto"),
                    "ma_soumission": soumission_data,
                    "stats": stats,
                }
            )

        return self.get_paginated_response(result)


@extend_schema_view(
    post=extend_schema(
        summary="Créer un devoir pour un cours",
        description=(
            "Crée un nouveau devoir (non publié par défaut) pour un cours donné. "
            "Réservé à l'enseignant principal du cours. Applique des valeurs par "
            "défaut raisonnables (type_devoir=cursus, date_limite=+7 jours, "
            "note_sur=20, tentatives_max=1…) pour les champs non fournis."
        ),
        tags=["evaluation"],
        request=DevoirCreateSerializer,
        responses={201: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class CreerDevoirCoursView(APIView):
    """
    POST /api/cours/<cours_id>/devoirs/creer/
    Permet à l'enseignant principal de créer un devoir pour son cours.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        # Vérifier que l'utilisateur est l'enseignant principal du cours
        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut créer un devoir pour ce cours."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy()
        data["cours_lie"] = cours.id

        # Définir les valeurs par défaut si non fournies
        if "type_devoir" not in data:
            data["type_devoir"] = "cursus"
        if "est_publie" not in data:
            data["est_publie"] = False
        if "date_debut" not in data:
            data["date_debut"] = timezone.now().isoformat()
        if "date_limite" not in data:
            data["date_limite"] = (timezone.now() + timedelta(days=7)).isoformat()
        if "duree_minutes" not in data:
            data["duree_minutes"] = 60
        if "note_sur" not in data:
            data["note_sur"] = 20
        if "tentatives_max" not in data:
            data["tentatives_max"] = 1
        if "coefficient" not in data:
            data["coefficient"] = 1.0
        if "type_correction" not in data:
            data["type_correction"] = "auto"

        serializer = DevoirCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        devoir = serializer.save(cree_par=profile)

        # Stocker type_correction (si champ existe dans le modèle)
        type_correction = data.get("type_correction", "auto")
        if hasattr(devoir, "type_correction"):
            devoir.type_correction = type_correction
            devoir.save(update_fields=["type_correction"])

        # MAJ compteur
        cours.nb_devoirs = Devoir.objects.filter(cours_lie=cours, est_publie=True).count()
        cours.save(update_fields=["nb_devoirs"])

        enregistrer_activite(
            user=request.user,
            action="homework_created",
            description=f"Devoir « {devoir.titre} » créé pour le cours « {cours.titre} »",
            data={
                "devoir": devoir.titre,
                "cours": cours.titre,
                "date_limite": (
                    devoir.date_limite.strftime("%d/%m/%Y") if devoir.date_limite else ""
                ),
            },
            objet_id=devoir.id,
            objet_type="Devoir",
        )

        return Response(
            {
                "id": devoir.id,
                "titre": devoir.titre,
                "description": devoir.description,
                "date_debut": devoir.date_debut.isoformat() if devoir.date_debut else None,
                "date_limite": devoir.date_limite.isoformat() if devoir.date_limite else None,
                "est_publie": devoir.est_publie,
                "nb_questions": devoir.questions.count(),
                "note_sur": float(devoir.note_sur),
                "duree_minutes": devoir.duree_minutes,
                "tentatives_max": devoir.tentatives_max,
                "type_correction": getattr(devoir, "type_correction", "auto"),
                "detail": "Devoir créé avec succès.",
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Soumettre un devoir sous forme de fichier PDF",
        description=(
            "Permet à un apprenant de soumettre un fichier PDF (`fichier`, multipart) "
            "pour un devoir à correction manuelle, à la place de réponses saisies en "
            "ligne. Le nombre de tentatives déjà effectuées est vérifié contre "
            "`tentatives_max`."
        ),
        tags=["evaluation"],
        request={"multipart/form-data": OpenApiTypes.OBJECT},
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class SoumettreDevoirFichierView(APIView):
    """
    POST /api/devoirs/<devoir_id>/soumettre-fichier/
    Permet à un apprenant de soumettre un fichier PDF pour un devoir
    de type correction manuelle.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        if not devoir.est_ouvert:
            return Response(
                {"detail": "Le devoir n'est plus accessible."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Vérifier les tentatives
        nb_tentatives = SoumissionDevoir.objects.filter(
            utilisateur=request.user, devoir=devoir, statut__in=["soumis", "corrige", "en_retard"]
        ).count()

        if nb_tentatives >= devoir.tentatives_max:
            return Response(
                {"detail": f"Nombre maximum de tentatives atteint ({devoir.tentatives_max})."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Récupérer ou créer la soumission
        soum, created = SoumissionDevoir.objects.get_or_create(
            utilisateur=request.user,
            devoir=devoir,
            defaults={
                "statut": "en_cours",
                "ip_address": _get_client_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:500],
            },
        )

        if not created and soum.statut in ["soumis", "corrige"]:
            return Response(
                {"detail": "Vous avez déjà soumis ce devoir."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Traiter le fichier uploadé
        fichier = request.FILES.get("fichier")
        if not fichier:
            return Response(
                {"detail": "Aucun fichier fourni."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not fichier.name.lower().endswith(".pdf"):
            return Response(
                {"detail": "Seuls les fichiers PDF sont acceptés."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Stocker le fichier dans la soumission
        soum.fichier_soumis = fichier

        now = timezone.now()
        soum.statut = "en_retard" if soum.est_en_retard else "soumis"
        soum.soumis_le = now
        soum.save()

        return Response(
            {
                "statut": soum.statut,
                "message": "Fichier soumis avec succès. En attente de correction.",
                "soumis_le": soum.soumis_le.isoformat(),
                "devoir_titre": devoir.titre,
            }
        )


@extend_schema_view(
    post=extend_schema(
        summary="Ajouter une question à un devoir",
        description=(
            "Ajoute une question (avec ses choix éventuels pour un QCM) à un devoir "
            "non encore publié. Réservé à l'enseignant principal du cours lié (ou à "
            "l'organisateur pour un devoir d'olympiade)."
        ),
        tags=["evaluation"],
        request=QuestionDevoirCreateUpdateSerializer,
        responses={201: QuestionDevoirAdminSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AjouterQuestionDevoirView(APIView):
    """
    POST /api/devoirs/<devoir_id>/questions/ajouter/
    Ajoute une question à un devoir. Utilise les mêmes garde-fous que
    ModifierQuestionDevoirView / SupprimerQuestionDevoirView : réservé à
    l'enseignant principal, interdit une fois le devoir publié.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Seul l'enseignant principal peut ajouter des questions."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Même garde que ModifierQuestionDevoirView / SupprimerQuestionDevoirView :
        # impossible d'ajouter une question à un devoir déjà publié (des
        # apprenants pourraient déjà être en train de composer).
        if devoir.est_publie:
            return Response(
                {"detail": "Impossible d'ajouter une question à un devoir déjà publié."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy()
        data["ordre"] = data.get("ordre", devoir.questions.count() + 1)

        serializer = QuestionDevoirCreateUpdateSerializer(
            data=data, context={"type_correction": devoir.type_correction}
        )
        serializer.is_valid(raise_exception=True)
        choix_data = serializer.validated_data.pop("choix", [])
        question = QuestionDevoir.objects.create(devoir=devoir, **serializer.validated_data)

        if question.type_question == "qcm" and choix_data:
            for c in choix_data:
                ChoixReponse.objects.create(
                    question=question,
                    texte=c.get("texte", ""),
                    est_correct=c.get("est_correct", False),
                )

        return Response(
            QuestionDevoirAdminSerializer(question).data, status=status.HTTP_201_CREATED
        )


@extend_schema_view(
    post=extend_schema(
        summary="Ajouter un énoncé à un devoir",
        description=(
            "Ajoute un nouvel énoncé (bloc de contenu HTML enrichi, avec ses propres "
            "questions rattachées séparément) à un devoir non encore publié. `ordre` "
            "est calculé automatiquement (dernier ordre + 1). Réservé à l'enseignant "
            "principal du cours lié (ou à l'organisateur pour un devoir d'olympiade). "
            "409 Conflict si le devoir est déjà publié (CDC §7.2.2 : verrouillage à "
            "la publication)."
        ),
        tags=["evaluation"],
        request=OpenApiTypes.OBJECT,
        responses={201: EnonceDevoirSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AjouterEnonceDevoirView(APIView):
    """
    POST /api/devoirs/<devoir_id>/enonces/ajouter/
    Ajoute un énoncé supplémentaire à un devoir (P2.3 — CDC §7.2.1 : « un
    énoncé a plusieurs questions, ces questions »). Un devoir a toujours au
    moins un énoncé (ordre=1, créé automatiquement à la création du devoir,
    voir DevoirCreateSerializer.create) ; cette vue permet d'en ajouter
    d'autres (ordre=2, 3…) avant publication.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Seul l'enseignant principal peut ajouter un énoncé."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # CDC §7.2.2 : « Après est_publie=True : questions et énoncés en
        # lecture seule. 409 Conflict + message explicite. »
        if devoir.est_publie:
            raise ConflictError(
                "Ce devoir est déjà publié : aucun énoncé ne peut plus être ajouté."
            )

        contenu = (request.data.get("contenu") or "").strip()
        if not contenu:
            return Response({"detail": "Le contenu de l'énoncé est obligatoire."}, status=400)

        ordre = devoir.enonces.count() + 1
        enonce = EnonceDevoir.objects.create(devoir=devoir, contenu=contenu, ordre=ordre)

        return Response(EnonceDevoirSerializer(enonce).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les questions d'un devoir",
        description="Retourne la liste paginée des questions d'un devoir (avec leurs choix), ordonnées par `ordre`.",
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: QuestionDevoirAdminSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class ListeQuestionsDevoirView(PaginatedListMixin, APIView):
    """GET /api/devoirs/<devoir_id>/questions/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)
        questions = devoir.questions.prefetch_related("choix").order_by("ordre")
        page = self.paginate_queryset(questions)
        return self.get_paginated_response(QuestionDevoirAdminSerializer(page, many=True).data)


@extend_schema_view(
    get=extend_schema(
        summary="Soumissions d'un devoir (vue enseignant)",
        description=(
            "Retourne la liste paginée de toutes les soumissions d'apprenants pour un "
            "devoir donné. Réservé à l'enseignant principal du cours lié (ou à "
            "l'organisateur pour un devoir d'olympiade)."
        ),
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class SoumissionsDevoirEnseignantView(PaginatedListMixin, APIView):
    """
    GET /api/devoirs/<devoir_id>/soumissions/
    Retourne toutes les soumissions d'un devoir.
    Réservé à l'enseignant principal du cours lié.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Accès réservé à l'enseignant principal."},
                status=status.HTTP_403_FORBIDDEN,
            )

        soumissions = (
            SoumissionDevoir.objects.filter(devoir=devoir)
            .select_related("utilisateur")
            .order_by("-debut")
        )

        page = self.paginate_queryset(soumissions)

        result = []
        for s in page:
            u = s.utilisateur
            nom = f"{u.first_name} {u.last_name}".strip()
            result.append(
                {
                    "id": s.id,
                    "apprenant_nom": nom,
                    "apprenant_username": u.username,
                    "statut": s.statut,
                    "note": float(s.note) if s.note is not None else None,
                    "soumis_le": s.soumis_le.isoformat() if s.soumis_le else "",
                    "est_suspecte": s.est_suspecte,
                    "nb_focus_perdu": s.nb_focus_perdu,
                    "commentaire": s.commentaire or "",
                }
            )

        return self.get_paginated_response(result)


@extend_schema_view(
    patch=extend_schema(
        summary="Corriger une soumission de devoir",
        description=(
            "Attribue une note (entre 0 et la note maximale du devoir) et un "
            "commentaire à une soumission, notifie l'apprenant et marque la "
            "soumission comme corrigée. Réservé à l'enseignant principal du cours lié."
        ),
        tags=["evaluation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class CorrigerSoumissionView(APIView):
    """
    PATCH /api/soumissions/<soumission_id>/corriger/
    Attribue une note et un commentaire à une soumission.
    Réservé à l'enseignant principal du cours lié.

    Body JSON :
    {
        "note":        15.5,
        "commentaire": "Bon travail, mais…"
    }
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, soumission_id):
        soum = get_object_or_404(SoumissionDevoir, pk=soumission_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if not _profile_autorise_gerer_devoir(soum.devoir, profile):
            return Response(
                {"detail": "Seul l'enseignant principal peut corriger cette soumission."},
                status=status.HTTP_403_FORBIDDEN,
            )

        note_raw = request.data.get("note")
        if note_raw is None:
            return Response(
                {"detail": "Le champ 'note' est requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            note = float(note_raw)
        except (TypeError, ValueError):
            return Response(
                {"detail": "La note doit être un nombre."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        note_sur = float(soum.devoir.note_sur)
        if note < 0 or note > note_sur:
            return Response(
                {"detail": f"La note doit être entre 0 et {note_sur}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        soum.note = note
        soum.statut = "corrige"
        soum.commentaire = request.data.get("commentaire", "")
        soum.corrige_le = timezone.now()
        soum.save(update_fields=["note", "statut", "commentaire", "corrige_le"])

        creer_notification(
            utilisateur=soum.utilisateur,
            type_notif="correction",
            titre="Devoir corrigé",
            contenu=f"Votre devoir « {soum.devoir.titre} » a été corrigé : {note}/{note_sur}.",
            objet_id=soum.devoir.id,
            objet_type="Devoir",
            action_url=f"/devoirs/{soum.devoir.id}/resultat",
        )

        enregistrer_activite(
            user=request.user,
            action="submission_graded",
            description=f"Soumission de {soum.utilisateur.get_full_name() or soum.utilisateur.username} corrigée — note: {soum.note}/{soum.devoir.note_sur}",
            data={
                "apprenant": soum.utilisateur.get_full_name() or soum.utilisateur.username,
                "devoir": soum.devoir.titre,
                "note": str(soum.note),
                "note_sur": str(soum.devoir.note_sur),
            },
            objet_id=soum.id,
            objet_type="Soumission",
        )

        return Response(
            {
                "id": soum.id,
                "note": float(soum.note),
                "statut": soum.statut,
                "commentaire": soum.commentaire,
                "corrige_le": soum.corrige_le.isoformat(),
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    get=extend_schema(
        summary="Détail d'une soumission (vue enseignant)",
        description=(
            "Retourne le détail complet d'une soumission de devoir : réponses "
            "question par question, statut, note, fichier soumis le cas échéant. "
            "Réservé à l'enseignant principal du cours lié."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class DetailSoumissionEnseignantView(APIView):
    """GET /api/soumissions/<soumission_id>/detail/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, soumission_id):
        soum = get_object_or_404(SoumissionDevoir, pk=soumission_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if not _profile_autorise_gerer_devoir(soum.devoir, profile):
            return Response(
                {"detail": "Accès réservé à l'enseignant principal."},
                status=status.HTTP_403_FORBIDDEN,
            )

        u = soum.utilisateur
        nom = f"{u.first_name} {u.last_name}".strip()

        reponses = []
        for rep in soum.reponses.select_related("question", "choix").all():
            reponses.append(
                {
                    "question_id": rep.question.id,
                    "question_texte": rep.question.texte,
                    "type_question": rep.question.type_question,
                    "reponse": rep.reponse,
                    "est_correct": rep.est_correct,
                    "points_obtenus": rep.points_obtenus,
                    "points_max": rep.question.points,
                }
            )

        fichier_url = None
        if hasattr(soum, "fichier_soumis") and soum.fichier_soumis:
            fichier_url = request.build_absolute_uri(soum.fichier_soumis.url)

        return Response(
            {
                "id": soum.id,
                "apprenant_nom": nom or u.username,
                "apprenant_username": u.username,
                "statut": soum.statut,
                "note": float(soum.note) if soum.note is not None else None,
                "note_sur": float(soum.devoir.note_sur),
                "commentaire": soum.commentaire or "",
                "soumis_le": soum.soumis_le.isoformat() if soum.soumis_le else "",
                "corrige_le": soum.corrige_le.isoformat() if soum.corrige_le else "",
                "en_retard": soum.est_en_retard,
                "est_suspecte": soum.est_suspecte,
                "nb_focus_perdu": soum.nb_focus_perdu,
                "reponses": reponses,
                "fichier_soumis": fichier_url,
            }
        )


@extend_schema_view(
    get=extend_schema(
        summary="Statistiques d'un devoir",
        description=(
            "Retourne des statistiques agrégées sur les soumissions d'un devoir "
            "(total, corrigés, en attente, suspects, moyenne, note min/max). Réservé "
            "à l'enseignant principal du cours lié."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class StatsDevoirEnseignantView(APIView):
    """GET /api/devoirs/<devoir_id>/stats/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Accès réservé à l'enseignant principal."},
                status=status.HTTP_403_FORBIDDEN,
            )

        soumissions = SoumissionDevoir.objects.filter(devoir=devoir)
        total = soumissions.count()
        corriges = soumissions.filter(statut="corrige").count()
        en_attente = soumissions.filter(statut__in=["soumis", "en_retard"]).count()
        suspects = soumissions.filter(est_suspecte=True).count()

        notes = list(soumissions.filter(note__isnull=False).values_list("note", flat=True))

        moyenne = sum(notes) / len(notes) if notes else 0
        note_max = max(notes) if notes else 0
        note_min = min(notes) if notes else 0

        return Response(
            {
                "total_soumissions": total,
                "corriges": corriges,
                "en_attente": en_attente,
                "suspects": suspects,
                "moyenne": round(moyenne, 2),
                "note_max": float(note_max),
                "note_min": float(note_min),
                "note_sur": float(devoir.note_sur),
            }
        )


def _devoir_to_dict(devoir, user=None):
    """Sérialise un Devoir en dictionnaire pour les réponses API."""
    soumission_data = None
    if user:
        soum = SoumissionDevoir.objects.filter(devoir=devoir, utilisateur=user).first()
        if soum:
            soumission_data = {
                "id": soum.id,
                "statut": soum.statut,
                "note": float(soum.note) if soum.note is not None else None,
                "soumis_le": soum.soumis_le.isoformat() if soum.soumis_le else None,
            }

    return {
        "id": devoir.id,
        "titre": devoir.titre,
        "description": devoir.description,
        "date_debut": devoir.date_debut.isoformat() if devoir.date_debut else None,
        "date_limite": devoir.date_limite.isoformat() if devoir.date_limite else None,
        "est_ouvert": devoir.est_ouvert,
        "est_expire": devoir.est_expire,
        "nb_questions": devoir.questions.count(),
        "note_sur": float(devoir.note_sur) if hasattr(devoir, "note_sur") else 20,
        "duree_minutes": devoir.duree_minutes,
        "tentatives_max": devoir.tentatives_max,
        "est_publie": devoir.est_publie,
        "type_correction": getattr(devoir, "type_correction", "auto"),
        "ma_soumission": soumission_data,
    }


@extend_schema_view(
    get=extend_schema(
        summary="Mes devoirs (vue cadre)",
        description=(
            "Retourne la liste paginée de tous les devoirs créés par l'enseignant "
            "cadre connecté (utile notamment pour les devoirs liés à ses olympiades). "
            "Réservé aux enseignants cadres."
        ),
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class CadreDevoirsView(PaginatedListMixin, APIView):
    """
    GET /api/devoirs/cadre/mes-devoirs/
    Retourne tous les devoirs créés par le cadre connecté.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_cadre":
            return Response({"detail": "Accès réservé aux enseignants cadres."}, status=403)

        devoirs = Devoir.objects.filter(cree_par=profile).order_by("-date_creation")

        page = self.paginate_queryset(devoirs)

        data = []
        for d in page:
            data.append(
                {
                    "id": d.id,
                    "titre": d.titre,
                    "description": d.description,
                    "type_devoir": d.type_devoir,
                    "matiere": d.matiere,
                    "niveau": d.niveau,
                    "date_debut": d.date_debut.isoformat(),
                    "date_limite": d.date_limite.isoformat(),
                    "est_publie": d.est_publie,
                    "nb_questions": d.questions.count(),
                    "note_sur": d.note_sur,
                    "est_lie_olympiade": hasattr(d, "olympiade_config")
                    and d.olympiade_config is not None,
                }
            )

        return self.get_paginated_response(data)
