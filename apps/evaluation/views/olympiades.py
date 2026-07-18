import json

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.accounts.services import _get_profile
from apps.core.exceptions import ConflictError, PaymentRequiredError, InsufficientBalanceError
from apps.core.models import ParametreSysteme, enregistrer_activite
from apps.core.pagination import PaginatedListMixin
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
    EXEMPLE_CONFLICT,
    EXEMPLE_PAYMENT_REQUIRED,
    EXEMPLE_INSUFFICIENT_BALANCE,
    EXEMPLE_THROTTLED,
)
from apps.core.services import _get_client_ip
from apps.formation.models import Departement
from apps.notifications.models import creer_notification
from apps.paiement.models import PaiementOlympiade, YekiWallet, Paiement
from apps.evaluation.models import (
    Olympiade,
    InscriptionOlympiade,
    ReponseOlympiade,
    ClassementOlympiade,
    Devoir,
)
from apps.evaluation.serializers import (
    OlympiadeListSerializer,
    OlympiadeDetailSerializer,
    InscriptionOlympiadeSerializer,
    ClassementOlympiadeSerializer,
)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les olympiades",
        description="Retourne la liste paginée des olympiades, filtrable par statut.",
        tags=["evaluation"],
        parameters=[
            *PARAMS_PAGINATION,
            OpenApiParameter(
                "statut",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre sur le statut calculé (ex: en_cours, terminee).",
            ),
        ],
        responses={200: OlympiadeListSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class ListeOlympiadesView(PaginatedListMixin, APIView):
    """GET /api/olympiades/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Olympiade.objects.all().order_by("-date_debut_olympiade")

        statut = request.query_params.get("statut")

        serializer = OlympiadeListSerializer(qs, many=True, context={"request": request})
        data = serializer.data

        # Filtre statut post-sérialisation (statut_auto est une propriété
        # calculée, pas un champ DB : le filtre ne peut pas être fait dans
        # le queryset). La pagination se fait donc sur la liste déjà
        # sérialisée et filtrée, pas sur le queryset.
        if statut:
            data = [d for d in data if d["statut"] == statut]

        page = self.paginate_queryset(data)
        return self.get_paginated_response(page)


@extend_schema_view(
    get=extend_schema(
        summary="Détail d'une olympiade",
        description="Retourne les informations complètes d'une olympiade donnée.",
        tags=["evaluation"],
        responses={200: OlympiadeDetailSerializer},
        examples=[*ERREURS_COURANTES],
    ),
)
class DetailOlympiadeView(APIView):
    """GET /api/olympiades/<id>/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)
        serializer = OlympiadeDetailSerializer(olympiade, context={"request": request})
        return Response(serializer.data)


@extend_schema_view(
    post=extend_schema(
        summary="S'inscrire à une olympiade",
        description=(
            "Inscrit l'apprenant connecté à l'olympiade. Échoue si les "
            "inscriptions ne sont pas ouvertes/sont closes, si un paiement de "
            "participation est requis et non effectué (402), ou si déjà "
            "inscrit (409)."
        ),
        tags=["evaluation"],
        responses={201: InscriptionOlympiadeSerializer},
        examples=[*ERREURS_ECRITURE, EXEMPLE_CONFLICT, EXEMPLE_PAYMENT_REQUIRED],
    ),
)
class SInscrireOlympiadeView(APIView):
    """POST /api/olympiades/<id>/inscrire/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)
        now = timezone.now()

        # ── Vérifications ────────────────────────────────────────
        if now < olympiade.date_ouverture_inscription:
            return Response(
                {"detail": "Les inscriptions ne sont pas encore ouvertes."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if now > olympiade.date_cloture_inscription:
            return Response(
                {"detail": "Les inscriptions sont clôturées."}, status=status.HTTP_403_FORBIDDEN
            )

        # Vérifier si l'olympiade est payante pour les participants
        if olympiade.demande_paiement_participants and olympiade.prix_participation > 0:
            # Vérifier si l'apprenant a déjà payé
            paiement = PaiementOlympiade.objects.filter(
                apprenant=request.user, olympiade=olympiade, statut="paye"
            ).first()

            if not paiement:
                raise PaymentRequiredError(
                    "Cette olympiade requiert un paiement de participation.",
                    fields={
                        "prix_participation": olympiade.prix_participation,
                        "olympiade_id": olympiade.id,
                        "need_payment": True,
                    },
                )

        inscription, created = InscriptionOlympiade.objects.get_or_create(
            olympiade=olympiade,
            apprenant=request.user,
            defaults={
                "ip_inscription": _get_client_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:500],
            },
        )

        if not created:
            raise ConflictError("Vous êtes déjà inscrit à cette olympiade.")

        serializer = InscriptionOlympiadeSerializer(inscription, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PayerOlympiadeView(APIView):
    """
    POST /api/olympiades/<id>/payer/
    ⚠️ DÉPRÉCIÉE (Partie 3.2 du cahier des charges) : la création d'une
    olympiade est désormais GRATUITE pour le cadre et publiée immédiatement,
    sans validation admin. Ce endpoint est conservé uniquement pour ne pas
    casser d'anciens appels frontend ; il ne fait plus rien payer.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Payer une olympiade (dépréciée)",
        description=(
            "Endpoint conservé pour compatibilité descendante uniquement : "
            "la création d'olympiade est gratuite depuis la Partie 3.2 du "
            "CDC. Ne déclenche plus aucun paiement."
        ),
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    )
    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)
        return Response(
            {
                "detail": "La création d'une olympiade est gratuite : aucun paiement n'est requis.",
                "olympiade_id": olympiade.id,
                "deja_publiee": bool(olympiade.devoir and olympiade.devoir.est_publie),
            },
            status=status.HTTP_200_OK,
        )


class PayerParticipationOlympiadeView(APIView):
    """
    POST /api/olympiades/<id>/payer-participation/
    Body: {"montant": 100}
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "paiement"  # anti-spam de demandes (CDC_BACKEND §2.5) : 10/min

    @extend_schema(
        summary="Payer sa participation à une olympiade",
        description=(
            "Débite le portefeuille Yéki de l'apprenant du montant de "
            "participation (split 80% Yéki / 20% cadre organisateur)."
        ),
        tags=["evaluation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[
            *ERREURS_ECRITURE,
            EXEMPLE_CONFLICT,
            EXEMPLE_INSUFFICIENT_BALANCE,
            EXEMPLE_THROTTLED,
        ],
    )
    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "apprenant":
            return Response(
                {"detail": "Seuls les apprenants peuvent payer leur participation."}, status=403
            )

        if not olympiade.demande_paiement_participants:
            return Response(
                {"detail": "Cette olympiade ne demande pas de paiement de participation."},
                status=400,
            )

        if olympiade.prix_participation <= 0:
            return Response({"detail": "Le prix de participation est invalide."}, status=400)

        # Vérifier que l'apprenant n'a pas déjà payé
        if PaiementOlympiade.objects.filter(
            apprenant=request.user, olympiade=olympiade, statut="paye"
        ).exists():
            raise ConflictError("Vous avez déjà payé pour cette olympiade.")

        montant = request.data.get("montant", olympiade.prix_participation)
        try:
            montant = int(montant)
        except (TypeError, ValueError):
            return Response({"detail": "Montant invalide."}, status=400)

        if montant < olympiade.prix_participation:
            return Response(
                {
                    "detail": f"Le montant minimum est de {olympiade.prix_participation} FCFA.",
                    "prix_participation": olympiade.prix_participation,
                },
                status=400,
            )

        # ── Débit réel du portefeuille de l'apprenant ─────────────
        wallet, _ = YekiWallet.objects.get_or_create(utilisateur=request.user)
        if not wallet.peut_debiter(montant):
            raise InsufficientBalanceError(
                "Solde insuffisant. Rechargez votre portefeuille Yéki.",
                fields={"solde_actuel": wallet.solde, "montant_requis": montant},
            )

        wallet.debiter(montant, description=f"Participation olympiade « {olympiade.titre} »")

        # ── Split compte Yéki / compte du cadre organisateur (P2.4 :
        # ParametreSysteme['part_yeki_olympiade'], plus de valeur en dur) ──
        part_yeki_pourcent = float(ParametreSysteme.get("part_yeki_olympiade", default=80))
        part_yeki = int(montant * part_yeki_pourcent / 100)
        part_cadre = montant - part_yeki

        if olympiade.organisateur and olympiade.organisateur.user_id:
            wallet_cadre, _ = YekiWallet.objects.get_or_create(
                utilisateur=olympiade.organisateur.user
            )
            wallet_cadre.crediter(
                part_cadre,
                description=f"Participation apprenant — olympiade « {olympiade.titre} » (20%)",
                reference=f"OLYMP-{olympiade.id}-{request.user.id}",
            )

        # Créer le paiement de participation
        paiement = PaiementOlympiade.objects.create(
            apprenant=request.user,
            olympiade=olympiade,
            montant=montant,
            statut="paye",
            paye_le=timezone.now(),
        )

        # Enregistrer dans Paiement global — part_yeki tracée comme commission Yéki
        Paiement.objects.create(
            utilisateur=request.user,
            type_paiement="olympiade_participation",
            moyen="wallet",
            montant=montant,
            statut="succes",
            olympiade_liee=olympiade,
            commission_yeki=part_yeki,
        )

        return Response(
            {
                "detail": "Paiement de participation effectué avec succès.",
                "montant": montant,
                "part_yeki": part_yeki,
                "part_cadre": part_cadre,
                "nouveau_solde": wallet.solde,
                "reference": paiement.reference,
            },
            status=200,
        )


class DemarrerOlympiadeView(APIView):
    """
    POST /api/olympiades/<id>/demarrer/
    Démarre la session de composition.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Démarrer la session de composition",
        description="Marque le début de la composition de l'apprenant pour cette olympiade.",
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)
        now = timezone.now()

        if olympiade.statut_auto != "en_cours":
            return Response(
                {"detail": "L'olympiade n'est pas en cours actuellement."},
                status=status.HTTP_403_FORBIDDEN,
            )

        inscription = get_object_or_404(
            InscriptionOlympiade, olympiade=olympiade, apprenant=request.user, statut="inscrit"
        )

        if inscription.soumis:
            return Response(
                {"detail": "Vous avez déjà soumis votre composition."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Si une session unique est imposée et déjà démarrée
        if olympiade.une_seule_session and inscription.session_demarree:
            return Response(
                {"detail": "Vous ne pouvez pas reprendre une session interrompue."},
                status=status.HTTP_403_FORBIDDEN,
            )

        inscription.session_demarree = True
        inscription.heure_debut_compo = inscription.heure_debut_compo or now
        inscription.ip_composition = _get_client_ip(request)
        inscription.save(update_fields=["session_demarree", "heure_debut_compo", "ip_composition"])

        serializer = InscriptionOlympiadeSerializer(inscription, context={"request": request})
        return Response(
            {
                "inscription": serializer.data,
                "temps_restant_secondes": inscription.temps_restant_secondes(),
            }
        )


class SoumettreOlympiadeView(APIView):
    """POST /api/olympiades/<id>/soumettre/"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Soumettre sa composition",
        description="Enregistre les réponses de l'apprenant, corrige automatiquement les QCM et calcule la note.",
        tags=["evaluation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    @transaction.atomic
    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        inscription = get_object_or_404(
            InscriptionOlympiade, olympiade=olympiade, apprenant=request.user, session_demarree=True
        )

        if inscription.soumis:
            return Response({"detail": "Déjà soumis."}, status=status.HTTP_400_BAD_REQUEST)

        # Vérifier que l'olympiade est encore en cours (ou temps expiré → auto-soumission)
        temps_restant = inscription.temps_restant_secondes()
        auto = temps_restant <= 0

        reponses = request.data.get("reponses", {})

        # ── Enregistrer les réponses ─────────────────────────────
        score = 0.0
        total = 0.0

        if olympiade.devoir:
            questions = olympiade.devoir.questions.prefetch_related("choix").all()

            for question in questions:
                total += question.points
                user_rep = reponses.get(str(question.id), "").strip()

                repobj, _ = ReponseOlympiade.objects.get_or_create(
                    inscription=inscription, question=question
                )

                if question.type_question == "qcm":
                    choix_sel = question.choix.filter(texte=user_rep).first()
                    repobj.choix = choix_sel
                    repobj.reponse_texte = user_rep
                    if choix_sel and choix_sel.est_correct:
                        repobj.est_correct = True
                        repobj.points_obtenus = question.points
                        score += question.points
                    else:
                        repobj.est_correct = False
                        repobj.points_obtenus = 0
                    repobj.save()

        # ── Finaliser inscription ────────────────────────────────
        note = round((score / total) * olympiade.note_sur, 2) if total > 0 else 0
        now = timezone.now()

        inscription.soumis = True
        inscription.soumis_automatique = auto
        inscription.heure_fin_compo = now
        inscription.note = note
        inscription.save()

        return Response(
            {
                "message": (
                    "Composition soumise." if not auto else "Temps écoulé — soumission automatique."
                ),
                "note": note,
                "note_sur": olympiade.note_sur,
                "auto_soumis": auto,
            }
        )


class FocusPeduOlympiadeView(APIView):
    """
    POST /api/olympiades/<id>/focus-perdu/
    Flutter appelle cet endpoint à chaque perte de focus.
    Si le seuil est atteint → soumission automatique.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Signaler une perte de focus",
        description="Incrémente le compteur de pertes de focus ; soumission automatique si le seuil est atteint.",
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    @transaction.atomic
    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        inscription = get_object_or_404(
            InscriptionOlympiade,
            olympiade=olympiade,
            apprenant=request.user,
            session_demarree=True,
            soumis=False,
        )

        inscription.nb_focus_perdu += 1

        if inscription.nb_focus_perdu >= olympiade.max_focus_perdu:
            inscription.est_suspecte = True
            inscription.soumis = True
            inscription.soumis_automatique = True
            inscription.raison_suspicion = f"Trop de pertes de focus ({inscription.nb_focus_perdu})"
            inscription.heure_fin_compo = timezone.now()
            # Calculer le score avec ce qui a été soumis jusqu'ici
            inscription.save()
            return Response(
                {
                    "detail": "Composition soumise automatiquement pour comportement suspect.",
                    "force_submit": True,
                },
                status=status.HTTP_200_OK,
            )

        inscription.save(update_fields=["nb_focus_perdu", "est_suspecte"])

        return Response(
            {
                "nb_focus_perdu": inscription.nb_focus_perdu,
                "max_focus_perdu": olympiade.max_focus_perdu,
                "restants": olympiade.max_focus_perdu - inscription.nb_focus_perdu,
                "force_submit": False,
            }
        )


@extend_schema_view(
    get=extend_schema(
        summary="Classement d'une olympiade",
        description="Retourne le classement final (paginé), visible seulement une fois l'olympiade terminée.",
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: ClassementOlympiadeSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class ClassementOlympiadeView(PaginatedListMixin, APIView):
    """GET /api/olympiades/<id>/classement/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        if olympiade.statut_auto not in ["terminee"]:
            # Résultats visibles seulement après la fin
            return Response(
                {"detail": "Le classement sera disponible à la fin de l'olympiade."},
                status=status.HTTP_403_FORBIDDEN,
            )

        classement = (
            ClassementOlympiade.objects.filter(olympiade=olympiade)
            .select_related("apprenant")
            .order_by("rang")
        )

        page = self.paginate_queryset(classement)
        serializer = ClassementOlympiadeSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class CalculerClassementView(APIView):
    """
    POST /api/olympiades/<id>/calculer-classement/
    Réservé admin / organisateur — calcule et sauvegarde le classement final.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Calculer le classement final",
        description="Réservé à l'organisateur/admin : calcule et sauvegarde le classement final une fois l'olympiade terminée.",
        tags=["evaluation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    @transaction.atomic
    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        # Vérifier que l'organisateur ou admin fait la requête
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=400)

        if (
            profile.user_type not in ["admin", "enseignant_admin"]
            and olympiade.organisateur != profile
        ):
            return Response({"detail": "Action réservée à l'organisateur."}, status=403)

        if olympiade.statut_auto not in ["terminee"]:
            return Response({"detail": "L'olympiade n'est pas encore terminée."}, status=400)

        # Récupérer toutes les soumissions non-suspectes triées par note
        inscriptions = InscriptionOlympiade.objects.filter(
            olympiade=olympiade,
            soumis=True,
        ).order_by("-note")

        ClassementOlympiade.objects.filter(olympiade=olympiade).delete()

        MENTIONS = {1: "Or 🥇", 2: "Argent 🥈", 3: "Bronze 🥉"}

        for rang, insc in enumerate(inscriptions, start=1):
            mention = MENTIONS.get(rang, "Participant")
            ClassementOlympiade.objects.create(
                olympiade=olympiade,
                apprenant=insc.apprenant,
                rang=rang,
                note=insc.note or 0,
                mention=mention,
            )
            insc.classement = rang
            insc.save(update_fields=["classement"])
        enregistrer_activite(
            user=request.user,
            action="ranking_computed",
            description=f"Classement calculé pour l'olympiade « {olympiade.titre} » ({inscriptions.count()} participants)",
            data={
                "olympiade": olympiade.titre,
                "participants": inscriptions.count(),
            },
            objet_id=olympiade.id,
            objet_type="Olympiade",
        )

        return Response(
            {
                "detail": f"Classement calculé pour {inscriptions.count()} participants.",
                "nb": inscriptions.count(),
            }
        )


@extend_schema_view(
    get=extend_schema(
        summary="Mon inscription à une olympiade",
        description="Retourne l'inscription de l'apprenant connecté à cette olympiade, si elle existe.",
        tags=["evaluation"],
        responses={200: InscriptionOlympiadeSerializer},
        examples=[*ERREURS_COURANTES],
    ),
)
class MonInscriptionOlympiadeView(APIView):
    """GET /api/olympiades/<id>/mon-inscription/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, olympiade_id):
        inscription = get_object_or_404(
            InscriptionOlympiade, olympiade_id=olympiade_id, apprenant=request.user
        )
        serializer = InscriptionOlympiadeSerializer(inscription, context={"request": request})
        return Response(serializer.data)


class CreerOlympiadeParCadreView(APIView):
    """
    POST /api/olympiades/creer/
    Création d'une olympiade par un enseignant_cadre (Partie 3.2) :
    - Gratuite pour le cadre (aucun paiement de création).
    - Plus de validation par l'enseignant admin : publiée immédiatement.
    - Participation apprenant : prix_participation FCFA (100 par défaut),
      split 80% compte Yéki / 20% compte du cadre à chaque paiement
      (voir PayerParticipationOlympiadeView).
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Créer une olympiade (enseignant cadre)",
        description=(
            "Création gratuite et publication immédiate d'une olympiade par "
            "l'enseignant cadre du département. Un Devoir lié est créé "
            "automatiquement."
        ),
        tags=["evaluation"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    @transaction.atomic
    def post(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_cadre":
            return Response(
                {"detail": "Seuls les enseignants cadres peuvent créer des olympiades."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data

        # ── Validation des champs obligatoires ───────────────────
        titre = (data.get("titre") or "").strip()
        if not titre:
            return Response({"detail": "Le titre est obligatoire."}, status=400)

        # ── Validation du département ─────────────────────────────
        departement_id = data.get("departement_id")
        if not departement_id:
            return Response({"detail": "departement_id est obligatoire."}, status=400)

        departement = get_object_or_404(Departement, pk=departement_id)

        if departement.cadre != profile:
            return Response({"detail": "Ce département ne vous appartient pas."}, status=403)

        # ── Validation des dates ──────────────────────────────────
        from django.utils.dateparse import parse_datetime

        def _parse_date(field_name):
            raw = data.get(field_name)
            if not raw:
                return None, f"Le champ '{field_name}' est obligatoire."
            parsed = parse_datetime(str(raw))
            if not parsed:
                return None, f"Format de date invalide pour '{field_name}'. Utilisez ISO 8601."
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            return parsed, None

        date_ouv_insc, err = _parse_date("date_ouverture_inscription")
        if err:
            return Response({"detail": err}, status=400)

        date_clo_insc, err = _parse_date("date_cloture_inscription")
        if err:
            return Response({"detail": err}, status=400)

        date_debut, err = _parse_date("date_debut_olympiade")
        if err:
            return Response({"detail": err}, status=400)

        # ── Paramètres de composition ─────────────────────────────
        try:
            duree_minutes = int(data.get("duree_minutes", 120))
            if duree_minutes < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"detail": "duree_minutes doit être un entier positif."}, status=400)

        # date_fin_olympiade calculée automatiquement (Partie 3.1) :
        # date_debut_olympiade + duree_minutes.
        date_fin = date_debut + timedelta(minutes=duree_minutes)

        # ── Cohérence des dates ───────────────────────────────────
        if date_clo_insc >= date_debut:
            return Response(
                {"detail": "La clôture des inscriptions doit être avant le début de l'olympiade."},
                status=400,
            )

        if date_ouv_insc >= date_clo_insc:
            return Response(
                {"detail": "L'ouverture des inscriptions doit être avant leur clôture."}, status=400
            )

        try:
            nb_questions = int(data.get("nb_questions", 30))
            if nb_questions < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"detail": "nb_questions doit être un entier positif."}, status=400)

        try:
            max_focus = int(data.get("max_focus_perdu", 3))
            if max_focus < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"detail": "max_focus_perdu doit être un entier positif."}, status=400)

        melanger_questions = bool(data.get("melanger_questions", True))
        melanger_choix = bool(data.get("melanger_choix", True))
        une_seule_session = bool(data.get("une_seule_session", True))

        # ── Niveaux accessibles ────────────────────────────────────
        niveaux_accessibles = data.get("niveaux_accessibles", [])
        if isinstance(niveaux_accessibles, str):
            try:
                niveaux_accessibles = json.loads(niveaux_accessibles)
            except json.JSONDecodeError:
                niveaux_accessibles = [
                    n.strip() for n in niveaux_accessibles.split(",") if n.strip()
                ]
        elif not isinstance(niveaux_accessibles, list):
            niveaux_accessibles = []

        # ── Prix de participation (100 FCFA par défaut, Partie 3.2) ─
        try:
            prix_participation = int(data.get("prix_participation", 100))
            if prix_participation < 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"detail": "prix_participation doit être un entier positif ou nul."}, status=400
            )

        # ── Création de l'olympiade — GRATUITE, sans validation admin ──
        olympiade = Olympiade.objects.create(
            titre=titre,
            description=(data.get("description") or "").strip(),
            edition=(data.get("edition") or "").strip(),
            recompense=(data.get("recompense") or data.get("recompenses") or "").strip(),
            date_ouverture_inscription=date_ouv_insc,
            date_cloture_inscription=date_clo_insc,
            date_debut_olympiade=date_debut,
            date_fin_olympiade=date_fin,
            duree_minutes=duree_minutes,
            nb_questions=nb_questions,
            max_focus_perdu=max_focus,
            melanger_questions=melanger_questions,
            melanger_choix=melanger_choix,
            une_seule_session=une_seule_session,
            prix_participation=prix_participation,
            demande_paiement_participants=prix_participation > 0,
            note_sur=20,
            organisateur=profile,
            cree_par=request.user,
            niveaux_accessibles=",".join(niveaux_accessibles) if niveaux_accessibles else "",
            est_validee=True,
            validee_le=timezone.now(),
        )

        # ── Créer automatiquement un Devoir lié, publié immédiatement ──
        devoir_lie = Devoir.objects.create(
            titre=f"[Olympiade] {titre}",
            description=f"Devoir lié à l'olympiade : {titre}",
            type_devoir="olympiade",
            enonce=f"Questions de l'olympiade {titre}",
            date_debut=date_debut,
            date_limite=date_fin,
            duree_minutes=duree_minutes,
            note_sur=20,
            est_publie=False,  # publié dès qu'au moins une question est ajoutée (cf. PublierDevoirView)
            cree_par=profile,
        )
        olympiade.devoir = devoir_lie
        olympiade.save(update_fields=["devoir"])

        # ── Notifier les apprenants éligibles du département ──────
        apprenants = Profile.objects.filter(
            user_type="apprenant", cursus=departement.parcours.nom, is_active=True
        ).select_related("user")

        for apprenant in apprenants:
            if olympiade.est_accessible_par_niveau(apprenant.niveau):
                creer_notification(
                    utilisateur=apprenant.user,
                    type_notif="olympiade",
                    titre=f"Nouvelle olympiade : {olympiade.titre}",
                    contenu=f"Une nouvelle olympiade '{olympiade.titre}' est disponible. Inscrivez-vous maintenant !",
                    objet_id=olympiade.id,
                    objet_type="Olympiade",
                    action_url=f"/olympiades/{olympiade.id}/inscription",
                )

        enregistrer_activite(
            user=request.user,
            action="olympiad_created",
            description=f"Olympiade « {olympiade.titre} » créée",
            data={
                "titre": olympiade.titre,
                "edition": olympiade.edition,
                "prix_participation": prix_participation,
            },
            objet_id=olympiade.id,
            objet_type="Olympiade",
        )

        return Response(
            {
                "id": olympiade.id,
                "titre": olympiade.titre,
                "edition": olympiade.edition,
                "statut": olympiade.statut_auto,
                "date_ouverture_inscription": olympiade.date_ouverture_inscription.isoformat(),
                "date_cloture_inscription": olympiade.date_cloture_inscription.isoformat(),
                "date_debut_olympiade": olympiade.date_debut_olympiade.isoformat(),
                "date_fin_olympiade": olympiade.date_fin_olympiade.isoformat(),
                "duree_minutes": olympiade.duree_minutes,
                "nb_questions": olympiade.nb_questions,
                "devoir_id": devoir_lie.id,
                "recompense": olympiade.recompense,
                "prix_participation": olympiade.prix_participation,
                "demande_paiement_participants": olympiade.demande_paiement_participants,
                "detail": "Olympiade créée et publiée avec succès. Ajoutez maintenant ses questions.",
            },
            status=status.HTTP_201_CREATED,
        )


class CadreModifierOlympiadeView(APIView):
    """
    PATCH /api/olympiades/<olympiade_id>/modifier/
    Modifie une olympiade qui n'a pas encore de devoir lié.

    # TODO(bug CONFIRMÉ, docs/AUDIT_BACKEND.md §5.1) : les champs
    # `prix_1er`/`prix_2eme`/`prix_3eme` ont été supprimés du modèle
    # Olympiade (voir apps/evaluation/models.py) mais restent gérés ici via
    # `setattr` — l'assignation ne lève pas d'erreur mais ne persiste rien
    # (perte silencieuse), alors que la réponse 200 les inclut dans
    # "modifications" comme si la sauvegarde avait réussi. Corrigé dans
    # une tâche dédiée, pas ici ("déplacer, ne pas réécrire").
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Modifier une olympiade (enseignant cadre)",
        description="Modifie une olympiade créée par le cadre connecté, tant qu'elle n'a pas de devoir lié ni n'est validée.",
        tags=["evaluation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    def patch(self, request, olympiade_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_cadre":
            return Response({"detail": "Accès réservé aux enseignants cadres."}, status=403)

        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        # Vérifier que le cadre est l'organisateur
        if olympiade.organisateur != profile:
            return Response(
                {"detail": "Vous n'êtes pas l'organisateur de cette olympiade."}, status=403
            )

        # Vérifier que l'olympiade n'a pas de devoir lié
        if olympiade.devoir:
            return Response(
                {
                    "detail": "Cette olympiade a déjà un devoir lié. Elle ne peut plus être modifiée."
                },
                status=400,
            )

        # Vérifier que l'olympiade n'est pas validée
        if olympiade.est_validee:
            return Response(
                {"detail": "Cette olympiade est déjà validée. Elle ne peut plus être modifiée."},
                status=400,
            )

        data = request.data
        updates = {}

        # Champs modifiables
        if "titre" in data:
            updates["titre"] = data["titre"].strip()
        if "description" in data:
            updates["description"] = data["description"].strip()
        if "edition" in data:
            updates["edition"] = data["edition"].strip()
        # Parsing des dates : `make_aware()` si la chaîne reçue est naïve,
        # exactement comme `CreerOlympiadeParCadreView._parse_date` — sans
        # cela, Django traite une date naïve comme UTC (USE_TZ=True) alors
        # qu'elle représente une heure locale Douala (UTC+1), provoquant un
        # décalage silencieux d'1h par rapport à l'olympiade telle que créée
        # (bug réel corrigé ici, cf. docs/API_FOUNDATIONS.md).
        from django.utils.dateparse import parse_datetime

        def _parse_date_aware(raw):
            parsed = parse_datetime(str(raw))
            if parsed and timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            return parsed

        if "date_ouverture_inscription" in data:
            updates["date_ouverture_inscription"] = _parse_date_aware(
                data["date_ouverture_inscription"]
            )
        if "date_cloture_inscription" in data:
            updates["date_cloture_inscription"] = _parse_date_aware(
                data["date_cloture_inscription"]
            )
        if "date_debut_olympiade" in data:
            updates["date_debut_olympiade"] = _parse_date_aware(data["date_debut_olympiade"])
        if "date_fin_olympiade" in data:
            updates["date_fin_olympiade"] = _parse_date_aware(data["date_fin_olympiade"])
        if "duree_minutes" in data:
            updates["duree_minutes"] = int(data["duree_minutes"])
        if "nb_questions" in data:
            updates["nb_questions"] = int(data["nb_questions"])
        if "max_focus_perdu" in data:
            updates["max_focus_perdu"] = int(data["max_focus_perdu"])
        if "melanger_questions" in data:
            updates["melanger_questions"] = data["melanger_questions"]
        if "melanger_choix" in data:
            updates["melanger_choix"] = data["melanger_choix"]
        if "une_seule_session" in data:
            updates["une_seule_session"] = data["une_seule_session"]
        if "recompense" in data:
            updates["recompense"] = data["recompense"].strip()
        if "niveaux_accessibles" in data:
            niveaux = data["niveaux_accessibles"]
            if isinstance(niveaux, list):
                updates["niveaux_accessibles"] = ",".join(niveaux)
            else:
                updates["niveaux_accessibles"] = niveaux
        if "demande_paiement_participants" in data:
            updates["demande_paiement_participants"] = data["demande_paiement_participants"]
        if "prix_participation" in data:
            updates["prix_participation"] = int(data["prix_participation"])

        if not updates:
            return Response({"detail": "Aucune modification spécifiée."}, status=400)

        # Appliquer les modifications
        for key, value in updates.items():
            setattr(olympiade, key, value)
        olympiade.save()

        enregistrer_activite(
            user=request.user,
            action="olympiad_modified",
            description=f"Olympiade « {olympiade.titre} » modifiée",
            data={"olympiade": olympiade.titre, "modifications": list(updates.keys())},
            objet_id=olympiade.id,
            objet_type="Olympiade",
        )

        return Response(
            {
                "detail": "Olympiade modifiée avec succès.",
                "id": olympiade.id,
                "titre": olympiade.titre,
                "modifications": list(updates.keys()),
            },
            status=200,
        )


class CadreOlympiadesView(PaginatedListMixin, APIView):
    """
    GET /api/olympiades/cadre/mes-olympiades/
    Retourne toutes les olympiades créées par le cadre connecté.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Mes olympiades (enseignant cadre)",
        description="Liste paginée des olympiades créées par le cadre connecté.",
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    )
    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_cadre":
            return Response({"detail": "Accès réservé aux enseignants cadres."}, status=403)

        olympiades = (
            Olympiade.objects.filter(organisateur=profile).select_related("devoir").order_by("-id")
        )

        page = self.paginate_queryset(olympiades)

        data = []
        for o in page:
            data.append(
                {
                    "id": o.id,
                    "titre": o.titre,
                    "edition": o.edition,
                    "statut": o.statut_auto,
                    "date_debut_olympiade": o.date_debut_olympiade.isoformat(),
                    "date_fin_olympiade": o.date_fin_olympiade.isoformat(),
                    "nb_inscrits": o.inscriptions.count(),
                    "nb_questions": o.nb_questions,
                    "duree_minutes": o.duree_minutes,
                    "prix_global": o.prix_global,
                    "est_validee": o.est_validee,
                    "est_refusee": o.est_refusee,
                    "devoir_id": o.devoir.id if o.devoir else None,
                    "est_publiee": o.devoir.est_publie if o.devoir else False,
                    "recompense": o.recompense,
                    "demande_paiement_participants": o.demande_paiement_participants,
                    "prix_participation": o.prix_participation,
                    "niveaux_accessibles": o.get_niveaux_accessibles_list(),
                    "melanger_questions": o.melanger_questions,
                    "melanger_choix": o.melanger_choix,
                    "une_seule_session": o.une_seule_session,
                    "max_focus_perdu": o.max_focus_perdu,
                    "description": o.description,
                }
            )

        return self.get_paginated_response(data)


class LierDevoirOlympiadeView(APIView):
    """
    POST /api/olympiades/<olympiade_id>/lier-devoir/
    Body: { "devoir_id": 123 }

    Lie un devoir existant à une olympiade.
    Le cadre doit être l'organisateur de l'olympiade et le créateur du devoir.
    Une fois lié, l'olympiade ne peut plus être modifiée.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Lier un devoir existant à une olympiade",
        description="Lie un devoir déjà créé par le cadre à une olympiade sans devoir lié — verrouille ensuite la modification de l'olympiade.",
        tags=["evaluation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    @transaction.atomic
    def post(self, request, olympiade_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_cadre":
            return Response({"detail": "Accès réservé aux enseignants cadres."}, status=403)

        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        # Vérifier que le cadre est l'organisateur
        if olympiade.organisateur != profile:
            return Response(
                {"detail": "Vous n'êtes pas l'organisateur de cette olympiade."}, status=403
            )

        # Vérifier que l'olympiade n'a pas déjà un devoir lié
        if olympiade.devoir:
            return Response(
                {
                    "detail": "Cette olympiade a déjà un devoir lié. Elle ne peut plus être modifiée."
                },
                status=400,
            )

        devoir_id = request.data.get("devoir_id")
        if not devoir_id:
            return Response({"detail": "devoir_id est requis."}, status=400)

        devoir = get_object_or_404(Devoir, pk=devoir_id)

        # Vérifier que le cadre a créé le devoir
        if devoir.cree_par != profile:
            return Response({"detail": "Vous n'êtes pas le créateur de ce devoir."}, status=403)

        # Vérifier que le devoir n'est pas déjà lié à une olympiade
        if hasattr(devoir, "olympiade_config") and devoir.olympiade_config:
            return Response({"detail": "Ce devoir est déjà lié à une olympiade."}, status=400)

        # Lier le devoir à l'olympiade
        olympiade.devoir = devoir
        olympiade.save()

        # Le devoir devient non modifiable
        devoir.est_publie = False  # En attente de validation/paiement
        devoir.save()

        enregistrer_activite(
            user=request.user,
            action="olympiad_modified",
            description=f"Devoir « {devoir.titre} » lié à l'olympiade « {olympiade.titre} »",
            data={
                "olympiade": olympiade.titre,
                "devoir": devoir.titre,
            },
            objet_id=olympiade.id,
            objet_type="Olympiade",
        )

        # Calculer le prix global avec la nouvelle tarification
        nb_apprenants = Profile.objects.filter(
            user_type="apprenant",
            cursus=olympiade.organisateur.departements_cadre.first().parcours.nom,
            is_active=True,
        ).count()

        # Tarification progressive
        if nb_apprenants <= 50:
            prix_global = nb_apprenants * 100
        elif nb_apprenants <= 100:
            prix_global = int(nb_apprenants * 100 * 0.8)
        elif nb_apprenants <= 200:
            prix_global = int(nb_apprenants * 100 * 0.6)
        else:
            prix_global = int(nb_apprenants * 100 * 0.5)

        olympiade.prix_global = prix_global
        olympiade.save(update_fields=["prix_global"])

        return Response(
            {
                "detail": "Devoir lié avec succès à l'olympiade.",
                "olympiade_id": olympiade.id,
                "devoir_id": devoir.id,
                "prix_global": prix_global,
                "nb_apprenants": nb_apprenants,
                "message": "L'olympiade est maintenant prête à être soumise. Veuillez procéder au paiement pour la valider.",
            },
            status=200,
        )


class OlympiadesPourMoiView(PaginatedListMixin, APIView):
    """
    GET /api/olympiades/pour-moi/

    Olympiades filtrées pour l'apprenant connecté selon son niveau.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Olympiades accessibles pour moi",
        description="Liste paginée des olympiades publiées et validées, filtrées selon le niveau de l'apprenant connecté.",
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OlympiadeListSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    )
    def get(self, request):
        profile = _get_profile(request.user)
        if not profile:
            return Response({"detail": "Profil introuvable."}, status=404)

        niveau_apprenant = (profile.niveau or "").strip().lower()

        # Base queryset — olympiades publiées ET validées
        qs = (
            Olympiade.objects.filter(
                devoir__est_publie=True,
            )
            .select_related("organisateur__user", "devoir")
            .order_by("-date_debut_olympiade")
        )

        # ⭐ FILTRAGE PAR NIVEAU (méthode Python, pas un filtre DB : la
        # pagination se fait donc sur la liste déjà filtrée, pas sur `qs`).
        olympiades_accessibles = []
        for o in qs:
            if o.est_accessible_par_niveau(niveau_apprenant):
                olympiades_accessibles.append(o)

        page = self.paginate_queryset(olympiades_accessibles)
        serializer = OlympiadeListSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)
