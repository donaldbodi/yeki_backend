import uuid
import logging

from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from apps.accounts.models import Profile
from apps.core.pagination import PaginatedListMixin
from apps.formation.models import Cours
from apps.paiement.models import Paiement
from apps.ia.models import YekiIAChatHistorique
from apps.ia.services import (
    ANTHROPIC_API_KEY,
    REQUESTS_AVAILABLE,
    solde_min_ia,
    calculate_cost,
    estimer_fourchette_cout,
    call_claude_api,
    get_system_prompt,
    verifier_solde_suffisant,
    debiter_cout_reel,
)

from drf_spectacular.utils import extend_schema, extend_schema_view
from drf_spectacular.types import OpenApiTypes
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
    EXEMPLE_THROTTLED,
)

logger = logging.getLogger(__name__)


@extend_schema_view(
    get=extend_schema(
        summary="Historique de conversation Yéki IA pour un cours",
        description=(
            "Retourne la liste paginée (ordre chronologique) des messages "
            "échangés entre l'apprenant connecté et Yéki IA pour un cours "
            "donné : `id, role, contenu, source, source_id, source_titre, "
            "image_url, audio_url, tokens_input, tokens_output, cree_le`."
        ),
        tags=["ia"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
    delete=extend_schema(
        summary="Effacer l'historique de conversation Yéki IA d'un cours",
        description=(
            "Supprime définitivement tous les messages de la conversation "
            "Yéki IA de l'apprenant connecté pour le cours donné."
        ),
        tags=["ia"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class YekiIAChatHistoriqueView(PaginatedListMixin, APIView):
    """GET /api/ia/cours/<cours_id>/historique/ - Récupère l'historique des messages"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        messages = YekiIAChatHistorique.objects.filter(
            apprenant=request.user, cours=cours
        ).order_by("cree_le")

        def get_fichier_url(fichier):
            if not fichier:
                return None
            return request.build_absolute_uri(fichier.url)

        page = self.paginate_queryset(messages)
        return self.get_paginated_response(
            [
                {
                    "id": m.id,
                    "role": m.role,
                    "contenu": m.contenu,
                    "source": m.source,
                    "source_id": m.source_id,
                    "source_titre": m.source_titre,
                    "image_url": get_fichier_url(m.image),
                    "audio_url": get_fichier_url(m.audio),
                    "tokens_input": m.tokens_input,
                    "tokens_output": m.tokens_output,
                    "cree_le": m.cree_le.isoformat(),
                }
                for m in page
            ]
        )

    def delete(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        YekiIAChatHistorique.objects.filter(apprenant=request.user, cours=cours).delete()
        return Response({"detail": "Conversation effacée avec succès."})


@extend_schema_view(
    post=extend_schema(
        summary="Envoyer un message à Yéki IA (facturé au wallet, débit après appel)",
        description=(
            "Envoie un message (texte, optionnellement accompagné d'une image "
            "et/ou d'un audio) au tuteur Yéki IA dans le contexte d'un cours. "
            "P10.1 : le débit se fait APRÈS l'appel à Claude, sur le coût RÉEL "
            "des tokens effectivement consommés — jamais une estimation "
            "débitée avant puis « ajustée » (l'ancien flux pouvait sous-"
            "facturer silencieusement). Si le solde est sous le minimum "
            "(`ParametreSysteme['solde_min_ia']`), retourne 402 avec le détail "
            "`{detail, solde_actuel, minimum_requis, cout_estime_min, "
            "cout_estime_max}` SANS appeler l'API Claude (aucune dépense "
            "engagée). En cas d'échec de l'appel à l'API Claude, retourne 503 "
            "SANS AUCUN DÉBIT ET SANS message assistant persisté — plus de "
            "réponse simulée facturée.\n\n"
            "Réponse 200 : `{reponse, message_id, assistant_id, tokens_input, "
            "tokens_output, cout_xaf, solde_avant, solde_restant, debit_ok}`. "
            "Limité par `throttle_scope='ia'` (facturation au token, anti-abus)."
        ),
        tags=["ia"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class YekiIAChatAvecHistoriqueView(APIView):
    """
    POST /api/ia/cours/<cours_id>/chat/

    Body JSON (ou multipart si image/audio) :
    {
        "message": "Explique-moi les dérivées",
        "source": "lecon",
        "source_id": 5,
        "source_titre": "Chapitre 3: Les dérivées"
    }

    Multipart: image, audio (optionnels)

    Retourne (200) :
    {
        "reponse": "Yeki IA : ...",
        "message_id": 123,
        "assistant_id": 124,
        "tokens_input": 450,
        "tokens_output": 320,
        "cout_xaf": 50,
        "solde_avant": 1000,
        "solde_restant": 950,
        "debit_ok": true
    }
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    throttle_scope = "ia"  # facturée au token (CDC_BACKEND §2.5) : 10/min

    @transaction.atomic
    def post(self, request, cours_id):
        # 1. Récupération du cours
        cours = get_object_or_404(Cours, pk=cours_id)

        # 2. Validation du message
        message = (request.data.get("message") or "").strip()
        if not message:
            return Response({"detail": "Le message est requis."}, status=400)

        # 3. Récupération des métadonnées
        source = request.data.get("source", "libre")
        source_id = request.data.get("source_id")
        source_titre = request.data.get("source_titre", "")
        image_file = request.FILES.get("image")
        audio_file = request.FILES.get("audio")

        # 4. Récupération du niveau de l'apprenant et du type de département
        # du cours (P10.2 : le prompt doit s'adapter aux deux).
        try:
            profile = request.user.profile
            niveau_apprenant = profile.niveau or "Licence 1"
        except Profile.DoesNotExist:
            niveau_apprenant = "Licence 1"
        type_departement = cours.departement.type_departement if cours.departement_id else "cursus"

        # 5. Vérification du solde minimum — SANS DÉBITER (P10.1 : le débit
        # se fait après l'appel Claude, sur le coût réel).
        solde_ok, solde_avant, message_solde = verifier_solde_suffisant(request.user)
        if not solde_ok:
            cout_min, cout_max = estimer_fourchette_cout(message)
            return Response(
                {
                    "detail": message_solde,
                    "solde_actuel": solde_avant,
                    "minimum_requis": solde_min_ia(),
                    "cout_estime_min": cout_min,
                    "cout_estime_max": cout_max,
                },
                status=402,
            )

        # 6. Sauvegarde du message utilisateur
        user_msg = YekiIAChatHistorique.objects.create(
            apprenant=request.user,
            cours=cours,
            role="user",
            contenu=message,
            source=source,
            source_id=source_id,
            source_titre=source_titre,
            image=image_file,
            audio=audio_file,
        )

        # 7. Récupération de l'historique pour le contexte
        historique = list(
            YekiIAChatHistorique.objects.filter(apprenant=request.user, cours=cours)
            .order_by("-cree_le")[:10]
            .values("role", "contenu")
        )
        historique.reverse()

        # 8. Construction du prompt système (budgété, voir apps/ia/services.py)
        system_prompt = get_system_prompt(
            cours_id, niveau_apprenant, source, source_titre, type_departement
        )

        # 9. Appel à l'API Claude — AUCUN DÉBIT AVANT CE POINT.
        texte_ia = None
        input_tokens = 0
        output_tokens = 0
        error_msg = None

        if ANTHROPIC_API_KEY and REQUESTS_AVAILABLE:
            texte_ia, input_tokens, output_tokens, error_msg = call_claude_api(
                system_prompt, message, historique
            )

        # 10. Échec API = AUCUN DÉBIT + message honnête (P10.1 : plus de
        # réponse simulée facturée quand même). Le message utilisateur
        # reste enregistré (déjà sauvegardé à l'étape 6) mais aucun message
        # assistant n'est créé et le wallet n'est jamais touché.
        if not texte_ia:
            logger.warning("Yéki IA indisponible (cours=%s): %s", cours_id, error_msg)
            return Response(
                {
                    "detail": (
                        "Yéki IA est temporairement indisponible. Réessayez "
                        "dans quelques instants — aucun débit n'a été effectué."
                    ),
                    "solde_actuel": solde_avant,
                },
                status=503,
            )

        # 11. Calcul du coût RÉEL (à partir des tokens effectivement
        # consommés, renvoyés par l'API) puis débit UNIQUE.
        cout_reel = calculate_cost(input_tokens, output_tokens)
        debit_ok, solde_final = debiter_cout_reel(
            request.user, cout_reel, f"Yeki IA - Cours: {cours.titre}"
        )
        if not debit_ok:
            # Cas limite : solde tombé sous le coût réel entre la
            # vérification (étape 5) et maintenant, malgré MAX_TOKENS_REPONSE
            # qui borne le pire cas. La réponse a déjà été générée et coûte
            # réellement à Yéki côté Anthropic — on la retourne quand même
            # (la cacher ne récupérerait rien) et on journalise l'écart au
            # lieu de le masquer.
            logger.warning(
                "Yéki IA : débit du coût réel (%s FCFA) impossible, solde insuffisant (cours=%s, user=%s)",
                cout_reel, cours_id, request.user.id,
            )
            solde_final = solde_avant

        # 12. Formatage de la réponse
        if not texte_ia.startswith("Yeki IA :"):
            texte_ia = f"Yeki IA : {texte_ia}"

        # 13. Sauvegarde de la réponse IA (avec les tokens réels — non
        # persistés auparavant malgré les champs du modèle)
        assistant_msg = YekiIAChatHistorique.objects.create(
            apprenant=request.user,
            cours=cours,
            role="assistant",
            contenu=texte_ia,
            tokens=input_tokens + output_tokens,
            tokens_input=input_tokens,
            tokens_output=output_tokens,
        )

        # 14. Enregistrement du paiement
        try:
            Paiement.objects.create(
                utilisateur=request.user,
                type_paiement="ia_request",
                moyen="wallet",
                montant=cout_reel,
                statut="succes" if debit_ok else "echec",
                transaction_id=f"IA-{uuid.uuid4().hex[:10].upper()}",
            )
        except Exception:
            # Volontairement large : la trace comptable Paiement ne doit pas
            # faire échouer une réponse IA déjà générée et déjà facturée au
            # wallet de l'utilisateur.
            logger.exception("Erreur enregistrement paiement IA")

        # 15. Réponse finale
        return Response(
            {
                "reponse": texte_ia,
                "message_id": user_msg.id,
                "assistant_id": assistant_msg.id,
                "tokens_input": input_tokens,
                "tokens_output": output_tokens,
                "cout_xaf": cout_reel,
                "solde_avant": solde_avant,
                "solde_restant": solde_final,
                "debit_ok": debit_ok,
            }
        )
