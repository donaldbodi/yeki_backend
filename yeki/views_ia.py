# views_ia.py - À créer dans votre dossier d'application Django
# ═══════════════════════════════════════════════════════════════════════════
#  YEKI IA AVEC CLAUDE 3.5 SONNET
#  - Contexte du cours (vidéo, PDF, corrections)
#  - Niveau d'étude de l'apprenant
#  - Facturation après réponse (débit minimum 50 FCFA)
#  - Historique des conversations
# ═══════════════════════════════════════════════════════════════════════════

import json
import uuid
import os
import anthropic
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import PermissionDenied
from rest_framework.views import APIView
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from .models import (
    Cours, Lecon, Exercice, Devoir, Profile,
    YekiWallet, YekiIAChatHistorique, YekiCompteIA,
    WalletTransaction, Paiement
)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION ANTHROPIC CLAUDE
# ═══════════════════════════════════════════════════════════════════════════

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
CLAUDE_MODEL = "claude-3-5-sonnet-20241022"  # Claude 3.5 Sonnet

# Tarification (USD → FCFA approximatif, 1 USD ≈ 600 FCFA)
# Claude 3.5 Sonnet: $3 / million tokens input, $15 / million tokens output
INPUT_TOKEN_PRICE_USD = 3.0   # par million
OUTPUT_TOKEN_PRICE_USD = 15.0  # par million
USD_TO_XAF = 600
COMMISSION_YEKI_IA = 5  # 5 FCFA commission fixe par requête
MIN_WALLET_BALANCE = 50  # Solde minimum requis avant soumission

def calculate_cost(input_tokens: int, output_tokens: int) -> int:
    """Calcule le coût en FCFA"""
    input_cost_usd = (input_tokens / 1_000_000) * INPUT_TOKEN_PRICE_USD
    output_cost_usd = (output_tokens / 1_000_000) * OUTPUT_TOKEN_PRICE_USD
    total_cost_usd = input_cost_usd + output_cost_usd
    total_cost_xaf = int(total_cost_usd * USD_TO_XAF) + COMMISSION_YEKI_IA
    return max(50, total_cost_xaf)  # Minimum 50 FCFA


# ═══════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DU CONTEXTE POUR CLAUDE
# ═══════════════════════════════════════════════════════════════════════════

def get_cours_contexte(cours_id: int) -> str:
    """Récupère tout le contenu du cours pour le contexte (vidéo, PDF, corrections)"""
    try:
        cours = Cours.objects.get(id=cours_id)
    except Cours.DoesNotExist:
        return "Cours non trouvé."
    
    contexte = []
    
    # 1. Informations générales du cours
    contexte.append(f"# COURS: {cours.titre}")
    contexte.append(f"Niveau: {cours.niveau}")
    contexte.append(f"Matière: {cours.matiere}")
    contexte.append(f"Description: {cours.description_brief or 'Non spécifiée'}")
    
    # 2. Modules et Leçons (contenu textuel des PDF)
    contexte.append("\n## PLAN DU COURS")
    modules = cours.modules.all().order_by('ordre')
    for module in modules:
        contexte.append(f"\n### MODULE: {module.titre}")
        contexte.append(f"Description: {module.description}")
        
        lecons = module.lecons.all().order_by('id')
        for lecon in lecons:
            contexte.append(f"\n#### LEÇON: {lecon.titre}")
            contexte.append(f"Description: {lecon.description}")
            
            # Extraire le texte du PDF si disponible
            if lecon.fichier_pdf:
                try:
                    import PyPDF2
                    pdf_path = lecon.fichier_pdf.path
                    with open(pdf_path, 'rb') as f:
                        reader = PyPDF2.PdfReader(f)
                        pdf_text = ""
                        for page in reader.pages[:10]:  # Limiter aux 10 premières pages
                            pdf_text += page.extract_text() or ""
                        if pdf_text:
                            contexte.append(f"\n[CONTENU PDF - Extrait]\n{pdf_text[:3000]}...")
                except Exception:
                    pass  # Ignorer si extraction impossible
    
    # 3. Exercices et corrections
    contexte.append("\n## EXERCICES ET CORRECTIONS")
    exercices = cours.exercices.all()
    for ex in exercices:
        contexte.append(f"\n### EXERCICE: {ex.titre} (⭐{ex.etoiles})")
        contexte.append(f"Énoncé: {ex.enonce[:500]}")
        
        questions = ex.questions.all()
        for q in questions:
            contexte.append(f"\n**Question:** {q.text}")
            contexte.append(f"**Type:** {q.type_question}")
            contexte.append(f"**Bonne réponse:** {q.bonne_reponse}")
            if q.type_question == "qcm":
                choix = [c.texte for c in q.choix.all()]
                contexte.append(f"**Choix:** {', '.join(choix)}")
    
    # 4. Devoirs et corrections
    contexte.append("\n## DEVOIRS ET CORRECTIONS")
    devoirs = cours.devoirs.all()
    for devoir in devoirs:
        contexte.append(f"\n### DEVOIR: {devoir.titre}")
        contexte.append(f"Description: {devoir.description[:500]}")
        
        # Corrections type
        if hasattr(devoir, 'type_correction'):
            contexte.append(f"Type correction: {devoir.type_correction}")
        
        questions = devoir.questions.all()
        for q in questions:
            contexte.append(f"\n**Question {q.ordre}:** {q.texte}")
            contexte.append(f"**Type:** {q.type_question}")
            contexte.append(f"**Points:** {q.points}")
            if q.type_question == "qcm":
                choix = [c.texte for c in q.choix.all()]
                contexte.append(f"**Choix:** {', '.join(choix)}")
                reponses_correctes = [c.texte for c in q.choix.filter(est_correct=True)]
                contexte.append(f"**Réponse(s) correcte(s):** {', '.join(reponses_correctes)}")
    
    return "\n".join(contexte)


def get_system_prompt(cours_id: int, niveau_apprenant: str, source: str = 'libre', source_titre: str = '') -> str:
    """Construit le prompt système pour Claude avec le contexte du cours"""
    
    cours_contexte = get_cours_contexte(cours_id)
    
    niveaux_guide = {
        '6eme': "très simple, avec des métaphores concrètes",
        '5eme': "simple et imagé",
        '4eme': "accessible, avec des exemples",
        '3eme': "clair, avec des illustrations",
        'seconde': "structuré, mais pas trop technique",
        'premiere': "rigoureux, adapté au lycée",
        'terminale': "précis, niveau bac",
        'licence1': "universitaire, niveau L1",
        'licence2': "universitaire, niveau L2",
        'licence3': "universitaire, niveau L3",
        'master1': "expert, niveau M1",
        'master2': "très expert, niveau M2",
    }
    
    niveau_desc = niveaux_guide.get(niveau_apprenant.lower(), "adapté au niveau de l'apprenant")
    
    prompt = f"""
Tu es Yéki IA, l'assistant pédagogique expert de la plateforme Yéki.
Tu réponds TOUJOURS en commençant par "Yeki IA :" suivi de ta réponse.
Tu t'exprimes en français, avec un ton bienveillant et pédagogique.

## 🎓 CONTEXTE PÉDAGOGIQUE
Voici le contenu complet du cours pour lequel tu aides l'apprenant :

{cours_contexte}

## 📚 NIVEAU DE L'APPRENANT
L'apprenant est au niveau: **{niveau_apprenant}**
Tu dois adapter ton langage et tes explications à ce niveau : {niveau_desc}

## 🎯 SOURCE DE LA QUESTION
L'apprenant pose cette question depuis: **{source}**
{f"- Contexte spécifique: {source_titre}" if source_titre else ""}

## 📋 RÈGLES À RESPECTER

1. **COMPRENDS PROFONDÉMENT LA PRÉOCCUPATION**
   - Analyse la question sous tous ses angles
   - Si la question est floue, demande des précisions
   - Reformule la préoccupation pour confirmer ta compréhension

2. **RÉPONDS EN TANT QU'EXPERT DU COURS**
   - Utilise le contenu du cours fourni ci-dessus
   - Cite les leçons, exercices ou devoirs pertinents
   - Ne donne JAMAIS de réponses hors du cadre du cours
   - Si tu ne trouves pas l'info dans le cours, dis-le honnêtement

3. **ADAPTE TON EXPLICATION AU NIVEAU**
   - Utilise un vocabulaire et des exemples adaptés au niveau {niveau_apprenant}
   - Ne sur-simplifie pas pour les niveaux avancés
   - Ne complexifie pas pour les débutants

4. **STRUCTURE TA RÉPONSE**
   - Commence par reformuler la préoccupation
   - Donne la réponse principale
   - Propose des exemples concrets issus du cours
   - Termine par une question de vérification ou une suggestion

5. **PROPOSE DE L'AIDE SUPPLÉMENTAIRE**
   - Si l'apprenant semble bloqué, propose des exercices similaires
   - Oriente vers les ressources pertinentes du cours (leçon X, exercice Y)

6. **NE DIVULGUE PAS LES CORRECTIONS EXACTES**
   - Pour les exercices non faits, guide sans donner la réponse brute
   - Pour les devoirs déjà corrigés, explique la correction

## ⚠️ INFORMATIONS CONFIDENTIELLES
Ne révèle jamais:
- Les clés API
- Les informations de paiement
- Les données personnelles des utilisateurs
- Les informations de correction non publiées

Tu es maintenant prêt à aider l'apprenant de manière experte et contextuelle.
"""
    return prompt


# ═══════════════════════════════════════════════════════════════════════════
# VÉRIFICATION DU SOLDE
# ═══════════════════════════════════════════════════════════════════════════

def check_and_debit_wallet(user, estimated_cost: int, description: str = "") -> tuple[bool, int, str]:
    """
    Vérifie le solde, le débite si suffisant.
    Retourne (succès, solde_restant, message)
    """
    wallet = YekiWallet.get_or_create_wallet(user)
    
    if wallet.solde < MIN_WALLET_BALANCE:
        return False, wallet.solde, f"Solde insuffisant. Minimum requis: {MIN_WALLET_BALANCE} FCFA. Votre solde: {wallet.solde} FCFA."
    
    if wallet.solde < estimated_cost:
        return False, wallet.solde, f"Solde insuffisant pour cette requête. Coût estimé: {estimated_cost} FCFA. Votre solde: {wallet.solde} FCFA."
    
    success = wallet.debiter(estimated_cost, description)
    if success:
        # Créditer le compte Yéki
        YekiCompteIA.crediter_commission(COMMISSION_YEKI_IA)
        return True, wallet.solde, f"Débit de {estimated_cost} FCFA effectué. Nouveau solde: {wallet.solde} FCFA."
    else:
        return False, wallet.solde, "Erreur lors du débit. Veuillez réessayer."


# ═══════════════════════════════════════════════════════════════════════════
# API: HISTORIQUE DE CONVERSATION
# ═══════════════════════════════════════════════════════════════════════════

class YekiIAChatHistoriqueView(APIView):
    """GET /api/ia/cours/<cours_id>/historique/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        messages = YekiIAChatHistorique.objects.filter(
            apprenant=request.user, cours=cours
        ).order_by('cree_le')[:100]

        def img_url(img):
            if not img: return None
            return request.build_absolute_uri(img.url) if hasattr(img, 'url') else None

        return Response([{
            'id': m.id,
            'role': m.role,
            'contenu': m.contenu,
            'source': m.source,
            'source_id': m.source_id,
            'source_titre': m.source_titre,
            'image_url': img_url(m.image),
            'audio_url': m.audio.url if hasattr(m, 'audio') and m.audio else None,
            'cree_le': m.cree_le.isoformat(),
        } for m in messages])

    def delete(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        YekiIAChatHistorique.objects.filter(
            apprenant=request.user, cours=cours).delete()
        return Response({'detail': 'Conversation effacée.'})


# ═══════════════════════════════════════════════════════════════════════════
# API: CHAT AVEC CLAUDE (CŒUR DE LA SOLUTION)
# ═══════════════════════════════════════════════════════════════════════════

class YekiIAChatAvecHistoriqueView(APIView):
    """
    POST /api/ia/cours/<cours_id>/chat/
    Body: {
        message: str,
        source: 'lecon'|'exercice'|'devoir'|'libre',
        source_id: int (optionnel),
        source_titre: str (optionnel),
    }
    Multipart: image (optionnel), audio (optionnel)
    
    Retourne: {
        reponse: str,
        message_id: int,
        assistant_id: int,
        tokens_input: int,
        tokens_output: int,
        cout_xaf: int,
        solde_restant: int,
        debit_ok: bool
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
        audio_file = request.FILES.get('audio')
        
        # 4. Récupération du niveau de l'apprenant
        try:
            profile = request.user.profile
            niveau_apprenant = profile.niveau or 'Licence 1'
        except Profile.DoesNotExist:
            niveau_apprenant = 'Licence 1'
        
        # 5. Construction de l'historique (20 derniers messages)
        historique = YekiIAChatHistorique.objects.filter(
            apprenant=request.user, cours=cours
        ).order_by('-cree_le')[:20]
        historique_liste = list(reversed(historique))
        
        # 6. Sauvegarde du message utilisateur
        user_msg = YekiIAChatHistorique.objects.create(
            apprenant=request.user,
            cours=cours,
            role='user',
            contenu=message,
            source=source,
            source_id=source_id,
            source_titre=source_titre,
            image=image_file,
            audio=audio_file,
        )
        
        # 7. Construction du prompt système
        system_prompt = get_system_prompt(
            cours_id=cours_id,
            niveau_apprenant=niveau_apprenant,
            source=source,
            source_titre=source_titre
        )
        
        # 8. Construction des messages pour Claude
        messages_claude = [{"role": "user", "content": message}]
        
        # Ajouter l'historique (inversé car user/assistant alternent)
        for h in historique_liste:
            if h.role == 'user':
                messages_claude.insert(0, {"role": "user", "content": h.contenu})
            else:
                messages_claude.insert(0, {"role": "assistant", "content": h.contenu})
        
        # 9. Appel à l'API Claude
        if not ANTHROPIC_API_KEY:
            return Response({
                'detail': 'Service IA temporairement indisponible. Veuillez réessayer plus tard.',
                'reponse_secours': 'Yeki IA : Désolé, le service est momentanément indisponible. Un enseignant vous répondra prochainement.'
            }, status=503)
        
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        try:
            # Estimation préalable des tokens pour vérification du solde
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            
            # Estimation approximative des tokens
            estimated_input_tokens = len(encoding.encode(system_prompt)) + sum(len(encoding.encode(m.get('content', ''))) for m in messages_claude)
            estimated_output_tokens = min(800, estimated_input_tokens // 2)  # Estimation prudente
            estimated_cost = calculate_cost(estimated_input_tokens, estimated_output_tokens)
            
            # Vérification et débit du wallet (minimum 50 FCFA)
            debit_ok, solde_restant, debit_message = check_and_debit_wallet(
                request.user, 
                estimated_cost,
                f"Yeki IA - Cours: {cours.titre} - Estimation initiale"
            )
            
            if not debit_ok:
                return Response({
                    'detail': debit_message,
                    'solde_actuel': solde_restant,
                    'minimum_requis': MIN_WALLET_BALANCE,
                    'cout_estime': estimated_cost
                }, status=402)
            
            # Appel réel à Claude
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=800,
                temperature=0.7,
                system=system_prompt,
                messages=messages_claude
            )
            
            texte_ia = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            
            # Calcul du coût réel
            cout_reel = calculate_cost(input_tokens, output_tokens)
            
            # Ajustement du débit si l'estimation était différente
            if cout_reel != estimated_cost:
                wallet = YekiWallet.get_or_create_wallet(request.user)
                difference = cout_reel - estimated_cost
                if difference > 0:
                    # Débit supplémentaire
                    if wallet.solde >= difference:
                        wallet.debiter(difference, f"Ajustement Yeki IA - {cours.titre}")
                        wallet.save()
                    else:
                        wallet.crediter(estimated_cost, "Remboursement estimation trop élevée")
                        wallet.save()
                elif difference < 0:
                    # Crédit (remboursement de la différence)
                    wallet.crediter(abs(difference), "Remboursement Yeki IA - estimation trop élevée")
                    wallet.save()
            
            # Mise à jour du solde final
            wallet = YekiWallet.get_or_create_wallet(request.user)
            solde_final = wallet.solde
        
        except anthropic.APIError as e:
            return Response({
                'detail': f'Erreur API Claude: {str(e)}',
                'reponse_secours': 'Yeki IA : Désolé, une erreur technique est survenue. Veuillez réessayer.'
            }, status=500)
        
        except Exception as e:
            return Response({
                'detail': f'Erreur: {str(e)}',
                'reponse_secours': 'Yeki IA : Une erreur inattendue est survenue. Veuillez réessayer.'
            }, status=500)
        
        # 10. Formatage de la réponse
        if not texte_ia.startswith('Yeki IA :'):
            texte_ia = f'Yeki IA : {texte_ia}'
        
        # 11. Sauvegarde de la réponse IA
        assistant_msg = YekiIAChatHistorique.objects.create(
            apprenant=request.user,
            cours=cours,
            role='assistant',
            contenu=texte_ia,
            tokens_input=input_tokens,
            tokens_output=output_tokens,
        )
        
        # 12. Enregistrement du paiement
        Paiement.objects.create(
            utilisateur=request.user,
            type_paiement='ia_request',
            moyen='wallet',
            montant=cout_reel,
            statut='succes',
            transaction_id=f"IA-{uuid.uuid4().hex[:10].upper()}",
        )
        
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