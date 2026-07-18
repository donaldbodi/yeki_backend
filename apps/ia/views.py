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
from apps.paiement.models import YekiWallet, Paiement
from apps.ia.models import YekiIAChatHistorique
from apps.ia.services import (
    ANTHROPIC_API_KEY,
    REQUESTS_AVAILABLE,
    solde_min_ia,
    calculate_cost,
    estimate_cost_from_message,
    call_claude_api,
    get_fallback_response,
    get_system_prompt,
    check_and_debit_wallet,
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
            "image_url, cree_le`."
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

        def get_image_url(img):
            if not img:
                return None
            return request.build_absolute_uri(img.url)

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
                    "image_url": get_image_url(m.image),
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
        summary="Envoyer un message à Yéki IA (facturé au wallet)",
        description=(
            "Envoie un message (texte, optionnellement accompagné d'une image) "
            "au tuteur Yéki IA dans le contexte d'un cours, et facture le coût "
            "de la requête (estimé puis ajusté au coût réel des tokens) sur le "
            "wallet Yéki de l'apprenant. Si le solde est insuffisant "
            "(`ParametreSysteme['solde_min_ia']`), retourne 402 avec le détail "
            "`{detail, solde_actuel, minimum_requis, cout_estime}` sans "
            "appeler l'API Claude. En cas d'échec de l'appel à l'API Claude "
            "3.5 Haiku, une réponse de repli locale est renvoyée à la place.\n\n"
            "Réponse 200 : `{reponse, message_id, assistant_id, tokens_input, "
            "tokens_output, cout_xaf, solde_restant, debit_ok}`. Limité par "
            "`throttle_scope='ia'` (facturation au token, anti-abus)."
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

    Body JSON:
    {
        "message": "Explique-moi les dérivées",
        "source": "lecon",
        "source_id": 5,
        "source_titre": "Chapitre 3: Les dérivées"
    }

    Multipart: image (optionnel)

    Retourne:
    {
        "reponse": "Yeki IA : ...",
        "message_id": 123,
        "assistant_id": 124,
        "tokens_input": 450,
        "tokens_output": 320,
        "cout_xaf": 50,
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

        # 4. Récupération du niveau de l'apprenant
        try:
            profile = request.user.profile
            niveau_apprenant = profile.niveau or "Licence 1"
        except Profile.DoesNotExist:
            niveau_apprenant = "Licence 1"

        # 5. Sauvegarde du message utilisateur
        user_msg = YekiIAChatHistorique.objects.create(
            apprenant=request.user,
            cours=cours,
            role="user",
            contenu=message,
            source=source,
            source_id=source_id,
            source_titre=source_titre,
            image=image_file,
        )

        # 6. Récupération de l'historique pour le contexte
        historique = list(
            YekiIAChatHistorique.objects.filter(apprenant=request.user, cours=cours)
            .order_by("-cree_le")[:10]
            .values("role", "contenu")
        )
        historique.reverse()

        # 7. Estimation du coût
        estimated_cost = estimate_cost_from_message(message)

        # 8. Vérification et débit du wallet
        debit_ok, solde_avant, debit_message = check_and_debit_wallet(
            request.user, estimated_cost, f"Yeki IA - Cours: {cours.titre}"
        )

        if not debit_ok:
            return Response(
                {
                    "detail": debit_message,
                    "solde_actuel": solde_avant,
                    "minimum_requis": solde_min_ia(),
                    "cout_estime": estimated_cost,
                },
                status=402,
            )

        # 9. Construction du prompt système
        system_prompt = get_system_prompt(cours_id, niveau_apprenant, source, source_titre)

        # 10. Appel à l'API Claude 3.5 Haiku
        texte_ia = None
        input_tokens = 0
        output_tokens = 0
        error_msg = None

        if ANTHROPIC_API_KEY and REQUESTS_AVAILABLE:
            texte_ia, input_tokens, output_tokens, error_msg = call_claude_api(
                system_prompt, message, historique
            )

        # 11. Fallback si l'appel a échoué
        if not texte_ia:
            texte_ia = get_fallback_response(message, error_msg)
            input_tokens = len(message) // 3
            output_tokens = len(texte_ia) // 3

        # 12. Calcul du coût réel
        cout_reel = calculate_cost(input_tokens, output_tokens)

        # 13. Ajustement du solde si le coût réel est différent
        if cout_reel != estimated_cost:
            wallet = YekiWallet.get_or_create_wallet(request.user)
            difference = cout_reel - estimated_cost
            if difference > 0:
                # Débit supplémentaire si le coût réel est plus élevé
                if wallet.solde >= difference:
                    wallet.debiter(difference, f"Ajustement coût IA - {cours.titre}")
                    wallet.save()
            elif difference < 0:
                # Remboursement si le coût réel est moins élevé
                wallet.crediter(abs(difference), f"Remboursement surestimation IA - {cours.titre}")
                wallet.save()

        # 14. Récupération du solde final
        wallet = YekiWallet.get_or_create_wallet(request.user)
        solde_final = wallet.solde

        # 15. Formatage de la réponse
        if not texte_ia.startswith("Yeki IA :"):
            texte_ia = f"Yeki IA : {texte_ia}"

        # 16. Sauvegarde de la réponse IA
        assistant_msg = YekiIAChatHistorique.objects.create(
            apprenant=request.user,
            cours=cours,
            role="assistant",
            contenu=texte_ia,
        )

        # 17. Enregistrement du paiement
        try:
            Paiement.objects.create(
                utilisateur=request.user,
                type_paiement="ia_request",
                moyen="wallet",
                montant=cout_reel,
                statut="succes",
                transaction_id=f"IA-{uuid.uuid4().hex[:10].upper()}",
            )
        except Exception:
            # Volontairement large : la trace comptable Paiement ne doit pas
            # faire échouer une réponse IA déjà générée et déjà facturée au
            # wallet de l'utilisateur.
            logger.exception("Erreur enregistrement paiement IA")

        # 18. Réponse finale
        return Response(
            {
                "reponse": texte_ia,
                "message_id": user_msg.id,
                "assistant_id": assistant_msg.id,
                "tokens_input": input_tokens,
                "tokens_output": output_tokens,
                "cout_xaf": cout_reel,
                "solde_restant": solde_final,
                "debit_ok": True,
            }
        )
