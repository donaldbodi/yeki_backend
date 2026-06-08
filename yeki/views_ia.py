# views_ia.py - Version complète avec Claude 3.5 Haiku
# ═══════════════════════════════════════════════════════════════════════════

import json
import uuid
import os
import sys
import logging
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404
from .models import (
    Cours, Lecon, Exercice, Devoir, Profile,
    YekiWallet, YekiIAChatHistorique, YekiCompteIA,
    Paiement
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION CLAUDE 3.5 HAIKU
# ═══════════════════════════════════════════════════════════════════════════

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
CLAUDE_MODEL = "claude-3-5-haiku-20241022"  # Claude 3.5 Haiku - plus stable

# Tarification Claude 3.5 Haiku (USD)
# Input: $0.80 / million tokens
# Output: $4.00 / million tokens
INPUT_TOKEN_PRICE_USD = 0.80
OUTPUT_TOKEN_PRICE_USD = 4.00
USD_TO_XAF = 600
COMMISSION_YEKI_IA = 5
MIN_WALLET_BALANCE = 50
ESTIMATED_TOKENS_PER_REQUEST = 800  # Estimation pour le calcul du coût

# Tentative d'import de requests
REQUESTS_AVAILABLE = False
try:
    import requests
    REQUESTS_AVAILABLE = True
    print("✓ Requests disponible", file=sys.stderr)
except ImportError as e:
    print(f"✗ Requests non disponible: {e}", file=sys.stderr)


def calculate_cost(input_tokens: int, output_tokens: int) -> int:
    """Calcule le coût en FCFA selon la tarification Claude 3.5 Haiku"""
    input_cost_usd = (input_tokens / 1_000_000) * INPUT_TOKEN_PRICE_USD
    output_cost_usd = (output_tokens / 1_000_000) * OUTPUT_TOKEN_PRICE_USD
    total_cost_usd = input_cost_usd + output_cost_usd
    total_cost_xaf = int(total_cost_usd * USD_TO_XAF) + COMMISSION_YEKI_IA
    return max(MIN_WALLET_BALANCE, total_cost_xaf)


def estimate_cost_from_message(message: str) -> int:
    """Estime le coût à partir du message"""
    estimated_tokens = min(2000, len(message) // 3 + 500)
    return calculate_cost(estimated_tokens, estimated_tokens // 2)


def call_claude_api(system_prompt: str, user_message: str, history: list = None) -> tuple:
    """
    Appelle l'API Claude 3.5 Haiku directement avec requests.
    Retourne (réponse, input_tokens, output_tokens, error)
    """
    if not ANTHROPIC_API_KEY:
        return None, 0, 0, "Clé API Anthropic non configurée"
    
    if not REQUESTS_AVAILABLE:
        return None, 0, 0, "Module requests non disponible"
    
    url = "https://api.anthropic.com/v1/messages"
    
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    # Construire les messages
    messages = []
    
    # Ajouter l'historique si fourni (max 10 derniers messages)
    if history:
        for h in history[-10:]:
            messages.append({"role": h.get('role', 'user'), "content": h.get('content', '')})
    
    messages.append({"role": "user", "content": user_message})
    
    data = {
        "model": CLAUDE_MODEL,
        "max_tokens": 800,
        "temperature": 0.7,
        "system": system_prompt[:6000],  # Limiter la taille du prompt
        "messages": messages
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=45)
        
        if response.status_code == 200:
            result = response.json()
            text = result.get('content', [{}])[0].get('text', '')
            usage = result.get('usage', {})
            input_tokens = usage.get('input_tokens', 0)
            output_tokens = usage.get('output_tokens', 0)
            return text, input_tokens, output_tokens, None
        else:
            error_msg = f"API error {response.status_code}: {response.text[:200]}"
            logger.error(error_msg)
            return None, 0, 0, error_msg
            
    except requests.exceptions.Timeout:
        return None, 0, 0, "Timeout de l'API Claude"
    except Exception as e:
        logger.error(f"Claude API exception: {e}")
        return None, 0, 0, str(e)


def get_fallback_response(question: str, error_msg: str = None) -> str:
    """Réponse de secours quand l'API n'est pas disponible"""
    error_part = f"\n\n⚠️ Erreur technique: {error_msg}" if error_msg else ""
    
    return f"""Yeki IA : Merci pour votre question !

Je comprends que vous voulez savoir : "{question[:200]}"

Pour vous aider au mieux :
1. 📚 Consultez les leçons et exercices du cours
2. 💬 Posez votre question dans le forum (réponse garantie sous 24h)
3. 👨‍🏫 Contactez votre enseignant directement

N'hésitez pas à reformuler votre question si besoin.{error_part}

Cordialement,
L'équipe Yéki"""


def get_cours_contexte_complet(cours_id: int) -> str:
    """Récupère le contexte complet du cours pour l'IA"""
    try:
        cours = Cours.objects.get(id=cours_id)
    except Cours.DoesNotExist:
        return "Cours non trouvé."
    
    contexte = []
    
    # Informations générales
    contexte.append(f"# COURS: {cours.titre}")
    contexte.append(f"Niveau: {cours.niveau}")
    contexte.append(f"Matière: {cours.matiere}")
    contexte.append(f"Description: {cours.description_brief or 'Non spécifiée'}")
    
    # Modules et Leçons
    contexte.append("\n## PLAN DETAILLE DU COURS")
    modules = cours.modules.all().order_by('ordre')
    for module in modules:
        contexte.append(f"\n### MODULE: {module.titre}")
        contexte.append(f"Description: {module.description or 'Aucune description'}")
        
        lecons = module.lecons.all().order_by('id')
        for idx, lecon in enumerate(lecons, 1):
            contexte.append(f"\n#### {idx}. LEÇON: {lecon.titre}")
            contexte.append(f"Description: {lecon.description[:300]}")
    
    # Exercices disponibles
    contexte.append("\n## EXERCICES DISPONIBLES")
    exercices = cours.exercices.all()
    for ex in exercices:
        contexte.append(f"\n### EXERCICE: {ex.titre} (⭐{'⭐' * (ex.etoiles - 1) if ex.etoiles else ''})")
        contexte.append(f"Énoncé: {ex.enonce[:200]}")
    
    # Devoirs
    contexte.append("\n## DEVOIRS")
    devoirs = cours.devoirs.all()
    for devoir in devoirs:
        contexte.append(f"\n### DEVOIR: {devoir.titre}")
        contexte.append(f"Description: {devoir.description[:200]}")
    
    return "\n".join(contexte[:8000])  # Limiter à 8000 caractères


def get_system_prompt(cours_id: int, niveau_apprenant: str, source: str = 'libre', source_titre: str = '') -> str:
    """Construit le prompt système pour Claude 3.5 Haiku"""
    
    cours_contexte = get_cours_contexte_complet(cours_id)
    
    # Guide des niveaux
    niveaux_guide = {
        '6eme': "très simple, avec des métaphores concrètes (cm1, primaire)",
        '5eme': "simple et imagé (collège)",
        '4eme': "accessible, avec des exemples (collège)",
        '3eme': "clair, avec des illustrations (collège)",
        'seconde': "structuré, mais pas trop technique (lycée)",
        'premiere': "rigoureux, adapté au lycée",
        'terminale': "précis, niveau bac (lycée)",
        'licence1': "universitaire, niveau L1 (début université)",
        'licence2': "universitaire, niveau L2",
        'licence3': "universitaire, niveau L3",
        'master1': "expert, niveau M1",
        'master2': "très expert, niveau M2",
    }
    
    niveau_clean = niveau_apprenant.lower().strip()
    niveau_desc = niveaux_guide.get(niveau_clean, "adapté au niveau de l'apprenant")
    
    # Source de la question
    source_desc = {
        'lecon': "depuis une leçon du cours",
        'exercice': "en faisant un exercice",
        'devoir': "en travaillant sur un devoir",
        'libre': "de manière générale"
    }.get(source, "depuis la plateforme")
    
    context_part = f"\nContexte spécifique: {source_titre}" if source_titre else ""
    
    prompt = f"""Tu es Yéki IA, l'assistant pédagogique expert de la plateforme Yéki.
Tu réponds TOUJOURS en commençant par "Yeki IA :" suivi de ta réponse.
Tu t'exprimes en français, avec un ton bienveillant, chaleureux et pédagogique.

## 🎓 CONTEXTE PÉDAGOGIQUE COMPLET
Voici le contenu détaillé du cours pour lequel tu aides l'apprenant :

{cours_contexte}

## 📚 NIVEAU DE L'APPRENANT
L'apprenant est au niveau: **{niveau_apprenant}**
Tu dois adapter ton langage et tes explications à ce niveau : {niveau_desc}

## 🎯 SOURCE DE LA QUESTION
L'apprenant pose cette question {source_desc}{context_part}

## 📋 RÈGLES STRICTES À RESPECTER

1. **COMPRENDS PROFONDÉMENT LA PRÉOCCUPATION**
   - Analyse la question sous tous ses angles
   - Si la question est floue, demande des précisions
   - Reformule la préoccupation pour confirmer ta compréhension

2. **RÉPONDS EN TANT QU'EXPERT DU COURS**
   - Utilise UNIQUEMENT le contenu du cours fourni ci-dessus
   - Cite les leçons, exercices ou devoirs pertinents (ex: "Dans la leçon 3...")
   - Ne donne JAMAIS de réponses hors du cadre du cours
   - Si tu ne trouves pas l'info dans le cours, dis-le honnêtement

3. **ADAPTE TON EXPLICATION AU NIVEAU**
   - Utilise un vocabulaire adapté au niveau {niveau_apprenant}
   - Ne sur-simplifie pas pour les niveaux avancés
   - Ne complexifie pas pour les débutants

4. **STRUCTURE TA RÉPONSE**
   - Commence par reformuler la préoccupation
   - Donne la réponse principale
   - Propose des exemples concrets issus du cours
   - Termine par une question de vérification ou une suggestion

5. **PROPOSE DE L'AIDE SUPPLÉMENTAIRE**
   - Si l'apprenant semble bloqué, propose des exercices similaires
   - Oriente vers les ressources pertinentes du cours

6. **NE DIVULGUE PAS LES CORRECTIONS EXACTES**
   - Pour les exercices non faits, guide sans donner la réponse brute
   - Pour les devoirs déjà corrigés, explique la correction

Tu es maintenant prêt à aider l'apprenant de manière experte et contextuelle.
La question de l'apprenant est:"""

    return prompt


def check_and_debit_wallet(user, estimated_cost: int, description: str = ""):
    """Vérifie et débite le wallet de l'utilisateur"""
    wallet = YekiWallet.get_or_create_wallet(user)
    
    if wallet.solde < MIN_WALLET_BALANCE:
        return False, wallet.solde, f"Solde minimum requis: {MIN_WALLET_BALANCE} FCFA. Votre solde: {wallet.solde} FCFA."
    
    if wallet.solde < estimated_cost:
        return False, wallet.solde, f"Solde insuffisant. Coût estimé: {estimated_cost} FCFA. Votre solde: {wallet.solde} FCFA."
    
    success = wallet.debiter(estimated_cost, description)
    if success:
        try:
            YekiCompteIA.crediter_commission(COMMISSION_YEKI_IA)
        except:
            pass
        return True, wallet.solde, f"Débit de {estimated_cost} FCFA effectué."
    else:
        return False, wallet.solde, "Erreur lors du débit. Veuillez réessayer."


# ═══════════════════════════════════════════════════════════════════════════
# VUES API
# ═══════════════════════════════════════════════════════════════════════════

class YekiIAChatHistoriqueView(APIView):
    """GET /api/ia/cours/<cours_id>/historique/ - Récupère l'historique des messages"""
    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        messages = YekiIAChatHistorique.objects.filter(
            apprenant=request.user, cours=cours
        ).order_by('cree_le')[:100]

        def get_image_url(img):
            if not img:
                return None
            try:
                return request.build_absolute_uri(img.url)
            except:
                return None

        return Response([{
            'id': m.id,
            'role': m.role,
            'contenu': m.contenu,
            'source': m.source,
            'source_id': m.source_id,
            'source_titre': m.source_titre,
            'image_url': get_image_url(m.image),
            'cree_le': m.cree_le.isoformat(),
        } for m in messages])

    def delete(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        YekiIAChatHistorique.objects.filter(
            apprenant=request.user, cours=cours).delete()
        return Response({'detail': 'Conversation effacée avec succès.'})


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

    @transaction.atomic
    def post(self, request, cours_id):
        # 1. Récupération du cours
        cours = get_object_or_404(Cours, pk=cours_id)
        
        # 2. Validation du message
        message = (request.data.get('message') or '').strip()
        if not message:
            return Response({'detail': 'Le message est requis.'}, status=400)
        
        # 3. Récupération des métadonnées
        source = request.data.get('source', 'libre')
        source_id = request.data.get('source_id')
        source_titre = request.data.get('source_titre', '')
        image_file = request.FILES.get('image')
        
        # 4. Récupération du niveau de l'apprenant
        try:
            profile = request.user.profile
            niveau_apprenant = profile.niveau or 'Licence 1'
        except Profile.DoesNotExist:
            niveau_apprenant = 'Licence 1'
        
        # 5. Sauvegarde du message utilisateur
        user_msg = YekiIAChatHistorique.objects.create(
            apprenant=request.user,
            cours=cours,
            role='user',
            contenu=message,
            source=source,
            source_id=source_id,
            source_titre=source_titre,
            image=image_file,
        )
        
        # 6. Récupération de l'historique pour le contexte
        historique = list(YekiIAChatHistorique.objects.filter(
            apprenant=request.user, cours=cours
        ).order_by('-cree_le')[:10].values('role', 'contenu'))
        historique.reverse()
        
        # 7. Estimation du coût
        estimated_cost = estimate_cost_from_message(message)
        
        # 8. Vérification et débit du wallet
        debit_ok, solde_avant, debit_message = check_and_debit_wallet(
            request.user, estimated_cost,
            f"Yeki IA - Cours: {cours.titre}"
        )
        
        if not debit_ok:
            return Response({
                'detail': debit_message,
                'solde_actuel': solde_avant,
                'minimum_requis': MIN_WALLET_BALANCE,
                'cout_estime': estimated_cost
            }, status=402)
        
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
        if not texte_ia.startswith('Yeki IA :'):
            texte_ia = f'Yeki IA : {texte_ia}'
        
        # 16. Sauvegarde de la réponse IA
        assistant_msg = YekiIAChatHistorique.objects.create(
            apprenant=request.user,
            cours=cours,
            role='assistant',
            contenu=texte_ia,
        )
        
        # 17. Enregistrement du paiement
        try:
            Paiement.objects.create(
                utilisateur=request.user,
                type_paiement='ia_request',
                moyen='wallet',
                montant=cout_reel,
                statut='succes',
                transaction_id=f"IA-{uuid.uuid4().hex[:10].upper()}",
            )
        except Exception as e:
            logger.error(f"Erreur enregistrement paiement: {e}")
        
        # 18. Réponse finale
        return Response({
            'reponse': texte_ia,
            'message_id': user_msg.id,
            'assistant_id': assistant_msg.id,
            'tokens_input': input_tokens,
            'tokens_output': output_tokens,
            'cout_xaf': cout_reel,
            'solde_restant': solde_final,
            'debit_ok': True,
        })