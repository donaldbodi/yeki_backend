import re
import unicodedata
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
from apps.core.permissions import AccesMatricePermission
from apps.core.services import _get_client_ip
from apps.formation.models import Cours
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
    EnonceDevoirUpdateSerializer,
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

    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Devoir
    acces_action = "voir"

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

    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Devoir
    acces_action = "voir"

    def get(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id, est_publie=True)
        self.check_object_permissions(request, devoir)

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

    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Devoir
    acces_action = "soumettre"

    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id, est_publie=True)
        self.check_object_permissions(request, devoir)

        # Vérifier que la date de début est passée
        if timezone.now() < devoir.date_debut:
            # P7.2, point 6 : affichage en heure de Douala (TIME_ZONE du
            # projet), pas en UTC — `.strftime()` sur un datetime aware
            # non localisé affiche le fuseau de stockage (UTC), pas celui
            # configuré pour l'app (`timezone.localtime()` convertit).
            date_debut_douala = timezone.localtime(devoir.date_debut)
            return Response(
                {
                    "detail": f"Ce devoir sera disponible à partir du {date_debut_douala.strftime('%d/%m/%Y à %H:%M')}."
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
        summary="Signaler une sortie du devoir",
        description=(
            "Enregistre une SORTIE de page (pas une soumission — P7.3 : « tentatives » "
            "désigne le nombre de sorties tolérées, pas des soumissions multiples). Si "
            "le nombre de sorties atteint `tentatives_max`, les réponses fournies sont "
            "corrigées et le devoir est soumis automatiquement EN L'ÉTAT, exactement "
            "comme une soumission explicite."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class SortirDevoirView(APIView):
    """
    POST /api/devoirs/<id>/sortir/
    Enregistre une sortie du devoir. Si le nombre de sorties atteint le maximum,
    corrige et soumet automatiquement le devoir (P7.3).
    """

    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Devoir
    acces_action = "soumettre"

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id, est_publie=True)
        self.check_object_permissions(request, devoir)

        soum = get_object_or_404(
            SoumissionDevoir, devoir=devoir, utilisateur=request.user, statut="en_cours"
        )

        # Incrémenter le compteur de sorties — la sortie seule NE SOUMET
        # JAMAIS (P7.3, exigence explicite répétée dans le ticket).
        soum.sorties += 1
        soum.save(update_fields=["sorties"])

        # Sorties épuisées → soumission automatique EN L'ÉTAT, corrigée
        # exactement comme une soumission explicite (même fonction que
        # SoumettreDevoirView — aucune logique dupliquée).
        if soum.sorties >= devoir.tentatives_max:
            reponses = request.data.get("reponses", {})
            _corriger_et_soumettre_devoir(devoir, soum, reponses)

            return Response(
                {
                    "detail": "Nombre maximum de sorties atteint. Devoir soumis automatiquement.",
                    "force_submit": True,
                    "sorties": soum.sorties,
                    "sorties_max": devoir.tentatives_max,
                    "statut": soum.statut,
                    "note": soum.note,
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


def _normaliser_texte(texte) -> str:
    """
    Normalise un texte pour une comparaison tolérante (P7.3, correction
    auto des questions texte libre) : casse, accents, ponctuation finale,
    espaces multiples. Une comparaison stricte transformerait chaque
    question texte en piège et l'enseignant recevrait des plaintes
    légitimes. Accent-folding repris de la logique déjà écrite pour le
    backfill `Choix.est_correct` (migrations/0002_...py, P2.2) plutôt que
    réinventée (règle 1).
    """
    texte = (texte or "").strip().lower()
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"[.!?,;:]+$", "", texte)  # ponctuation finale
    texte = re.sub(r"\s+", " ", texte).strip()  # espaces multiples
    return texte


def _corriger_et_soumettre_devoir(devoir, soum, reponses):
    """
    Corrige les réponses (QCM via `Choix.est_correct`, texte via
    `_normaliser_texte` en correction auto) et finalise la soumission
    (statut, note si auto, horodatage). Factorisée pour être appelée
    IDENTIQUEMENT depuis `SoumettreDevoirView` ET `SortirDevoirView`
    (sortie forcée par épuisement des tentatives, P7.3) — aucune logique
    dupliquée entre les deux vues, même patron que
    `_corriger_reponses_exercice` (apps/evaluation/views/exercices.py).
    """
    score = 0.0
    total = 0.0

    for question in devoir.questions.prefetch_related("choix").all():
        total += question.points
        user_rep = reponses.get(str(question.id), "").strip()

        repobj, _ = ReponseDevoir.objects.get_or_create(soumission=soum, question=question)

        if question.type_question == "qcm":
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
            # P7.3 : comparaison normalisée (casse/accents/ponctuation
            # finale/espaces multiples) — auparavant un simple
            # `.strip().lower()`, cause probable de plaintes légitimes.
            if devoir.type_correction == "auto":
                repobj.est_correct = _normaliser_texte(user_rep) == _normaliser_texte(
                    question.reponse_attendue
                )
                repobj.points_obtenus = question.points if repobj.est_correct else 0
                if repobj.est_correct:
                    score += question.points
            else:
                repobj.est_correct = None  # correction manuelle

        repobj.save()

    now = timezone.now()
    soum.soumis_le = now
    soum.statut = "en_retard" if soum.est_en_retard else "soumis"

    if devoir.type_correction == "auto":
        # QCM ET texte (comparaison normalisée) sont déjà corrigés dans la
        # boucle ci-dessus : on enregistre la note dans tous les cas, qu'il
        # y ait ou non des questions texte (correction précédente : la note
        # n'était enregistrée que pour les devoirs 100% QCM, perdant le
        # score des devoirs mixtes QCM+texte en correction automatique).
        soum.note = round((score / total) * devoir.note_sur, 2) if total > 0 else 0
        soum.statut = "corrige"
        soum.corrige_le = now

    soum.save()
    return score, total


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

    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Devoir
    acces_action = "soumettre"

    @transaction.atomic
    def post(self, request, devoir_id):
        # P7.2, point 7 : même filtre défensif que DemarrerDevoirView — un
        # devoir non publié ne doit pas pouvoir recevoir de soumission.
        devoir = get_object_or_404(Devoir, pk=devoir_id, est_publie=True)
        self.check_object_permissions(request, devoir)
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

        _corriger_et_soumettre_devoir(devoir, soum, reponses)

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

    # P9.1 : pas de gating AccesMatricePermission ici — une SoumissionDevoir
    # n'existe que si DemarrerDevoirView (déjà gaté) a réussi ; consulter le
    # résultat d'une soumission déjà faite ne doit pas redevenir bloqué si
    # le Premium a expiré entre-temps.
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
        summary="Dupliquer un devoir",
        description=(
            "Crée une copie non publiée d'un devoir existant, avec toutes ses "
            "questions et choix de réponse (copie profonde). Réservé au créateur du "
            "devoir ou à un enseignant du même cours (principal ou secondaire) — "
            "permission plus large que les autres endpoints de gestion, qui restent "
            "réservés au seul enseignant principal (P7.2)."
        ),
        tags=["evaluation"],
        responses={201: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
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

        # P7.2 : permission volontairement plus large qu'ailleurs, propre
        # à CETTE action (« le créateur ou un enseignant du même cours »,
        # texte exact du ticket) — n'affecte pas
        # `_profile_autorise_gerer_devoir`, partagée par tous les autres
        # endpoints de gestion (modifier/publier/questions), qui restent
        # volontairement réservés au seul enseignant principal.
        autorise = profile == source.cree_par
        cours = source.cours_lie
        if cours is not None:
            autorise = autorise or profile == cours.enseignant_principal or cours.enseignants.filter(pk=profile.pk).exists()
        olympiade = getattr(source, "olympiade_config", None)
        if olympiade is not None:
            autorise = autorise or olympiade.organisateur == profile
        if not autorise:
            return Response(
                {"detail": "Seul le créateur du devoir ou un enseignant du même cours peut le dupliquer."},
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
            # Copier les choix (ordre préservé — sans quoi tous les choix
            # copiés retombent sur le défaut `ordre=1`, ordre non
            # déterministe, même classe de bug déjà corrigée en P7.1 pour
            # la création directe de question).
            for choix in q.choix.all():
                ChoixReponse.objects.create(
                    question=nouvelle_question,
                    texte=choix.texte,
                    est_correct=choix.est_correct,
                    ordre=choix.ordre,
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
        summary="Modifier une question de devoir",
        description=(
            "Modifie une question d'un devoir non encore publié. Réservé à "
            "l'enseignant principal du cours lié. 409 Conflict si le devoir est déjà "
            "publié (P7.2, cohérence avec les endpoints d'énoncés/questions de P7.1)."
        ),
        tags=["evaluation"],
        request=QuestionDevoirCreateUpdateSerializer,
        responses={200: QuestionDevoirAdminSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
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

        # P7.2 : 409 (pas 403) — cohérence avec EnonceDevoirDetailView/
        # AjouterQuestionEnonceDevoirView (P7.1).
        if devoir.est_publie:
            raise ConflictError("Ce devoir est déjà publié : ses questions ne peuvent plus être modifiées.")

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
        summary="Supprimer une question de devoir",
        description=(
            "Supprime une question d'un devoir non encore publié. Réservé à "
            "l'enseignant principal du cours lié. 409 Conflict si le devoir est déjà "
            "publié (P7.2, cohérence avec les endpoints d'énoncés/questions de P7.1)."
        ),
        tags=["evaluation"],
        responses={204: None},
        examples=[*ERREURS_ECRITURE],
    ),
)
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

        # P7.2 : 409 (pas 403) — cohérence avec le reste du module.
        if devoir.est_publie:
            raise ConflictError("Ce devoir est déjà publié : ses questions ne peuvent plus être supprimées.")

        question.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    patch=extend_schema(
        summary="Modifier un devoir",
        description=(
            "Modifie les champs d'un devoir existant. Réservé à l'enseignant "
            "principal du cours lié (ou à l'organisateur pour un devoir d'olympiade). "
            "409 Conflict si le devoir est déjà publié — même contrôle que pour les "
            "questions/énoncés (P7.2, CDC §7.2.2)."
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
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)
        # P7.2 : corrige le NameError pré-existant (`cours` n'était jamais
        # défini, seul `devoir` l'était) — `cours` peut être None pour un
        # devoir d'olympiade (`cours_lie=None`).
        cours = devoir.cours_lie

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Seul l'enseignant principal du cours peut modifier ce devoir."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # P7.2, point 4 : « même contrôle » que les questions — AUCUN champ
        # n'est modifiable une fois le devoir publié (le serializer ne
        # bloquait auparavant que enonce/enonces_supplementaires).
        if devoir.est_publie:
            raise ConflictError("Ce devoir est déjà publié et ne peut plus être modifié.")

        serializer = DevoirUpdateSerializer(devoir, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        enregistrer_activite(
            user=request.user,
            action="homework_modified",
            description=f"Devoir « {updated.titre} » modifié",
            data={
                "devoir": updated.titre,
                "cours": cours.titre if cours else None,
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
        summary="Publier un devoir",
        description=(
            "Publie un devoir (le rend accessible aux apprenants et non modifiable), "
            "et notifie les apprenants du cours concerné. Réservé à l'enseignant "
            "principal du cours lié. Renvoie un avertissement explicite : au-delà de "
            "ce point, plus aucune question ni énoncé ne peut être ajouté ou modifié "
            "(P7.2, point 5)."
        ),
        tags=["evaluation"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class PublierDevoirView(APIView):
    """POST /api/devoirs/<devoir_id>/publier/"""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)
        # P7.2 : corrige le NameError pré-existant (`cours` n'était jamais
        # défini) — `cours` est None pour un devoir d'olympiade
        # (`cours_lie=None`), auquel cas il n'y a ni statistique de cours
        # ni cohorte d'apprenants de cours à notifier ici.
        cours = devoir.cours_lie

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Seul l'enseignant principal du cours peut publier ce devoir."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # P7.2 : 409 (pas 400) — cohérence avec le reste du module.
        if devoir.est_publie:
            raise ConflictError("Ce devoir est déjà publié.")

        if not devoir.questions.exists():
            return Response(
                {"detail": "Le devoir doit contenir au moins une question avant d'être publié."},
                status=400,
            )

        devoir.est_publie = True
        devoir.save(update_fields=["est_publie"])

        if cours is not None:
            # Corrige l'affectation sur la CLASSE (`Cours.nb_devoirs = ...`,
            # no-op) en affectation sur l'INSTANCE.
            cours.nb_devoirs = Devoir.objects.filter(cours_lie=cours, est_publie=True).count()
            cours.save(update_fields=["nb_devoirs"])

        enregistrer_activite(
            user=request.user,
            action="homework_published",
            description=f"Devoir « {devoir.titre} » publié",
            data={
                "devoir": devoir.titre,
                "cours": cours.titre if cours else None,
            },
            objet_id=devoir.id,
            objet_type="Devoir",
        )

        # Notification aux apprenants du cours : signal post_save sur
        # Devoir (apps/evaluation/signals.py, P10.3) — plus d'appel manuel
        # ici (un devoir d'olympiade, cours_lie=None, est déjà exclu par
        # le signal).

        return Response(
            {
                "detail": "Devoir publié avec succès. Il ne peut plus être modifié.",
                "id": devoir.id,
                "est_publie": True,
                # Point 5 : l'enseignant DOIT être informé, au moment de
                # publier, qu'il ne pourra plus ajouter/modifier de
                # question ni d'énoncé.
                "message": "Une fois publié, vous ne pouvez plus ajouter ou modifier les questions ni les énoncés.",
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

    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Devoir
    acces_action = "voir"

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

            # P7.4 : `coefficient`/`fichier_correction_url` manquaient —
            # sans eux l'écran de gestion enseignant devrait refaire un
            # appel réseau séparé pour des champs déjà en base ici.
            fichier_correction_url = None
            if devoir.fichier_correction:
                fichier_correction_url = request.build_absolute_uri(devoir.fichier_correction.url)

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
                    "coefficient": float(devoir.coefficient),
                    "duree_minutes": devoir.duree_minutes,
                    "tentatives_max": devoir.tentatives_max,
                    "est_publie": devoir.est_publie,
                    "type_correction": getattr(devoir, "type_correction", "auto"),
                    "fichier_correction_url": fichier_correction_url,
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

    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Devoir
    acces_action = "soumettre"
    parser_classes = [MultiPartParser, FormParser]

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)
        self.check_object_permissions(request, devoir)

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
    get=extend_schema(
        summary="Lister les énoncés d'un devoir",
        description="Retourne les énoncés du devoir, ORDONNÉS, avec leurs questions imbriquées (elles-mêmes ordonnées).",
        tags=["evaluation"],
        responses={200: EnonceDevoirSerializer(many=True)},
        examples=[*ERREURS_COURANTES],
    ),
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
class EnoncesDevoirView(APIView):
    """
    GET/POST /api/devoirs/<devoir_id>/enonces/
    P7.1 (CDC §7.2.1 : « un énoncé a plusieurs questions, ces questions »).
    Un devoir a toujours au moins un énoncé (ordre=1, créé automatiquement
    à la création du devoir, voir DevoirCreateSerializer.create) ; cette
    vue liste les énoncés existants et permet d'en ajouter d'autres
    (ordre=2, 3…) avant publication.
    """

    permission_classes = [IsAuthenticated, AccesMatricePermission]
    acces_modele = Devoir
    acces_action = "voir"

    def get(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)
        return Response(EnonceDevoirSerializer(devoir.enonces.all(), many=True).data)

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
    patch=extend_schema(
        summary="Modifier un énoncé de devoir",
        description="Modifie le contenu d'un énoncé d'un devoir non encore publié. 409 Conflict si publié.",
        tags=["evaluation"],
        request=EnonceDevoirUpdateSerializer,
        responses={200: EnonceDevoirSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
    delete=extend_schema(
        summary="Supprimer un énoncé de devoir",
        description=(
            "Supprime un énoncé (et ses questions/choix en cascade) d'un devoir non "
            "encore publié. 409 Conflict si le devoir est déjà publié, ou si c'est le "
            "DERNIER énoncé restant du devoir (un devoir doit toujours en conserver "
            "au moins un). Les énoncés restants sont renumérotés pour rester contigus."
        ),
        tags=["evaluation"],
        responses={204: None},
        examples=[*ERREURS_ECRITURE],
    ),
)
class EnonceDevoirDetailView(APIView):
    """PATCH/DELETE /api/devoirs/enonces/<enonce_id>/ — P7.1."""

    permission_classes = [IsAuthenticated]

    def _get_enonce_et_verifier(self, request, enonce_id):
        enonce = get_object_or_404(EnonceDevoir, pk=enonce_id)
        devoir = enonce.devoir
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return None, None, Response({"detail": "Profil introuvable."}, status=404)
        if not _profile_autorise_gerer_devoir(devoir, profile):
            return None, None, Response(
                {"detail": "Seul l'enseignant principal peut gérer les énoncés de ce devoir."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return enonce, devoir, None

    @transaction.atomic
    def patch(self, request, enonce_id):
        enonce, devoir, erreur = self._get_enonce_et_verifier(request, enonce_id)
        if erreur:
            return erreur

        if devoir.est_publie:
            raise ConflictError("Ce devoir est déjà publié : ses énoncés ne peuvent plus être modifiés.")

        serializer = EnonceDevoirUpdateSerializer(enonce, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(EnonceDevoirSerializer(updated).data)

    @transaction.atomic
    def delete(self, request, enonce_id):
        enonce, devoir, erreur = self._get_enonce_et_verifier(request, enonce_id)
        if erreur:
            return erreur

        if devoir.est_publie:
            raise ConflictError("Ce devoir est déjà publié : ses énoncés ne peuvent plus être supprimés.")

        if devoir.enonces.count() <= 1:
            raise ConflictError("Impossible de supprimer le dernier énoncé restant d'un devoir.")

        enonce.delete()

        # Renumérote les énoncés restants pour rester contigus (1..N) —
        # sans cela, `EnoncesDevoirView.post` (ordre = count() + 1)
        # pourrait recréer un `ordre` déjà utilisé par un énoncé restant
        # et violer `unique_together = ("devoir", "ordre")`.
        restants = list(devoir.enonces.order_by("ordre"))
        for nouvel_ordre, e in enumerate(restants, start=1):
            if e.ordre != nouvel_ordre:
                e.ordre = nouvel_ordre
                e.save(update_fields=["ordre"])

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    post=extend_schema(
        summary="Ajouter une question à un énoncé de devoir",
        description=(
            "Ajoute une question (avec ses choix éventuels pour un QCM) à un énoncé "
            "d'un devoir non encore publié — la question est rattachée à CET énoncé "
            "(`enonce_devoir`), pas seulement au devoir. Réservé à l'enseignant "
            "principal du cours lié (ou à l'organisateur pour un devoir d'olympiade). "
            "409 Conflict si le devoir est déjà publié."
        ),
        tags=["evaluation"],
        request=QuestionDevoirCreateUpdateSerializer,
        responses={201: QuestionDevoirAdminSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AjouterQuestionEnonceDevoirView(APIView):
    """
    POST /api/devoirs/enonces/<enonce_id>/questions/ — P7.1.
    Remplace `AjouterQuestionDevoirView` (qui créait des `QuestionDevoir`
    sans jamais rattacher `enonce_devoir`, malgré le modèle le permettant
    — exactement le bug dénoncé par le commanditaire : « un énoncé a
    plusieurs questions, CES questions »).
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, enonce_id):
        enonce = get_object_or_404(EnonceDevoir, pk=enonce_id)
        devoir = enonce.devoir

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Seul l'enseignant principal peut ajouter des questions."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # CDC §7.2.2 : 409 (pas 403) — cohérent avec EnoncesDevoirView/
        # EnonceDevoirDetailView, qui appliquent déjà ce même code après
        # publication.
        if devoir.est_publie:
            raise ConflictError("Ce devoir est déjà publié : aucune question ne peut plus être ajoutée.")

        data = request.data.copy()
        data["ordre"] = data.get("ordre", devoir.questions.count() + 1)

        serializer = QuestionDevoirCreateUpdateSerializer(
            data=data, context={"type_correction": devoir.type_correction}
        )
        serializer.is_valid(raise_exception=True)
        question = serializer.save(devoir=devoir, enonce_devoir=enonce)

        return Response(
            QuestionDevoirAdminSerializer(question).data, status=status.HTTP_201_CREATED
        )


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

        # P7.4 : garde manquante jusqu'ici — cette vue renvoie
        # `QuestionDevoirAdminSerializer` (est_correct/reponse_attendue
        # inclus), réservée à l'enseignant qui gère le devoir. Sans
        # cette vérification, n'importe quel utilisateur authentifié
        # pouvait voir les bonnes réponses avant même de composer.
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)
        if not _profile_autorise_gerer_devoir(devoir, profile):
            return Response(
                {"detail": "Seul l'enseignant principal peut consulter les questions."},
                status=status.HTTP_403_FORBIDDEN,
            )

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

        # Notification à l'apprenant : signal post_save sur SoumissionDevoir
        # (apps/evaluation/signals.py, P10.3) — plus d'appel manuel ici.

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
        for rep in soum.reponses.select_related("question", "choix").prefetch_related(
            "question__choix"
        ):
            question = rep.question
            reponses.append(
                {
                    "question_id": question.id,
                    # P7.3 : corrige `rep.question.texte` — champ inexistant
                    # sur QuestionDevoir (seul `enonce` existe), levait un
                    # AttributeError à chaque appel réel de cette vue.
                    "question_enonce": question.enonce,
                    "type_question": question.type_question,
                    "reponse": rep.reponse,
                    "est_correct": rep.est_correct,
                    "points_obtenus": rep.points_obtenus,
                    "points_max": question.points,
                    # P7.3 : parité avec la vue apprenant — utile à
                    # l'enseignant pour une correction manuelle.
                    "bonne_reponse": (
                        question.reponse_attendue
                        if question.type_question == "texte"
                        else (
                            question.choix.filter(est_correct=True).first().texte
                            if question.choix.filter(est_correct=True).exists()
                            else None
                        )
                    ),
                    "choix": (
                        [
                            {"id": c.id, "texte": c.texte, "est_correct": c.est_correct}
                            for c in question.choix.all()
                        ]
                        if question.type_question == "qcm"
                        else []
                    ),
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
