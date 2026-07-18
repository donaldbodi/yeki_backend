# apps/ia/services.py - Version complète avec Claude 3.5 Haiku
# ═══════════════════════════════════════════════════════════════════════════

import os
import sys
import logging

from apps.core.models import ParametreSysteme
from apps.formation.models import Cours
from apps.paiement.models import YekiWallet, YekiCompteIA

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION CLAUDE 3.5 HAIKU
# ═══════════════════════════════════════════════════════════════════════════

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Tarification Claude 3.5 Haiku (USD) — prix par token facturés par
# Anthropic, PAS dans la liste de valeurs ParametreSysteme du ticket P2.4
# (aucune valeur initiale donnée) : laissés en constantes ici, signalé
# comme dette technique à traiter dans une tâche dédiée si besoin
# (docs/AUDIT_BACKEND.md).
# Input: $0.80 / million tokens
# Output: $4.00 / million tokens
INPUT_TOKEN_PRICE_USD = 0.80
OUTPUT_TOKEN_PRICE_USD = 4.00
ESTIMATED_TOKENS_PER_REQUEST = 800  # Estimation pour le calcul du coût

# P2.4 : ces valeurs viennent désormais de ParametreSysteme (éditables sans
# redéploiement) — les constantes ci-dessous ne servent plus que de valeur
# de repli si la ligne n'existe pas encore en base (ne devrait jamais
# arriver après la migration de seed, mais évite un crash si elle est
# supprimée par erreur).
_MODELE_IA_DEFAUT = "claude-3-5-haiku-20241022"
_USD_TO_XAF_DEFAUT = 600
_COMMISSION_IA_POURCENT_DEFAUT = 20
_SOLDE_MIN_IA_DEFAUT = 20


def modele_ia() -> str:
    return ParametreSysteme.get("modele_ia", default=_MODELE_IA_DEFAUT)


def usd_to_xaf() -> float:
    return float(ParametreSysteme.get("usd_to_xaf", default=_USD_TO_XAF_DEFAUT))


def commission_ia_pourcent() -> float:
    return float(
        ParametreSysteme.get("commission_ia_pourcent", default=_COMMISSION_IA_POURCENT_DEFAUT)
    )


def solde_min_ia() -> int:
    return int(ParametreSysteme.get("solde_min_ia", default=_SOLDE_MIN_IA_DEFAUT))


# Tentative d'import de requests
REQUESTS_AVAILABLE = False
try:
    import requests

    REQUESTS_AVAILABLE = True
    print("✓ Requests disponible", file=sys.stderr)
except ImportError as e:
    print(f"✗ Requests non disponible: {e}", file=sys.stderr)


def calculate_cost(input_tokens: int, output_tokens: int) -> int:
    """
    Calcule le coût total en FCFA (coût de base Claude + commission Yéki en
    pourcentage, voir commission_yeki_sur_cout ci-dessous) selon la
    tarification Claude 3.5 Haiku.
    """
    input_cost_usd = (input_tokens / 1_000_000) * INPUT_TOKEN_PRICE_USD
    output_cost_usd = (output_tokens / 1_000_000) * OUTPUT_TOKEN_PRICE_USD
    total_cost_usd = input_cost_usd + output_cost_usd
    cout_base_xaf = total_cost_usd * usd_to_xaf()
    total_cost_xaf = int(cout_base_xaf * (1 + commission_ia_pourcent() / 100))
    return max(solde_min_ia(), total_cost_xaf)


def commission_yeki_sur_cout(cout_total_xaf: int) -> int:
    """
    Retrouve la part commission Yéki incluse dans un coût total déjà
    calculé par calculate_cost() (coût_base + commission%). Évite de
    changer la signature de calculate_cost()/ses appelants existants pour
    exposer séparément le montant à créditer à YekiCompteIA.
    """
    pourcent = commission_ia_pourcent()
    if pourcent <= 0 or cout_total_xaf <= 0:
        return 0
    cout_base = cout_total_xaf / (1 + pourcent / 100)
    return int(round(cout_total_xaf - cout_base))


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
        "content-type": "application/json",
    }

    # Construire les messages
    messages = []

    # Ajouter l'historique si fourni (max 10 derniers messages)
    if history:
        for h in history[-10:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

    messages.append({"role": "user", "content": user_message})

    data = {
        "model": modele_ia(),
        "max_tokens": 800,
        "temperature": 0.7,
        "system": system_prompt[:6000],  # Limiter la taille du prompt
        "messages": messages,
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=45)

        if response.status_code == 200:
            result = response.json()
            text = result.get("content", [{}])[0].get("text", "")
            usage = result.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            return text, input_tokens, output_tokens, None
        else:
            error_msg = f"API error {response.status_code}: {response.text[:200]}"
            logger.error(error_msg)
            return None, 0, 0, error_msg

    except requests.exceptions.Timeout:
        return None, 0, 0, "Timeout de l'API Claude"
    except requests.exceptions.RequestException as e:
        logger.exception("Claude API : échec réseau/HTTP")
        return None, 0, 0, str(e)
    except (KeyError, IndexError, ValueError) as e:
        logger.exception("Claude API : réponse inattendue")
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
    modules = cours.modules.all().order_by("ordre")
    for module in modules:
        contexte.append(f"\n### MODULE: {module.titre}")
        contexte.append(f"Description: {module.description or 'Aucune description'}")

        lecons = module.lecons.all().order_by("id")
        for idx, lecon in enumerate(lecons, 1):
            contexte.append(f"\n#### {idx}. LEÇON: {lecon.titre}")
            contexte.append(f"Description: {lecon.description[:300]}")

    # Exercices disponibles
    contexte.append("\n## EXERCICES DISPONIBLES")
    exercices = cours.exercices.all()
    for ex in exercices:
        contexte.append(
            f"\n### EXERCICE: {ex.titre} (⭐{'⭐' * (ex.etoiles - 1) if ex.etoiles else ''})"
        )
        contexte.append(f"Énoncé: {ex.enonce[:200]}")

    # Devoirs
    contexte.append("\n## DEVOIRS")
    devoirs = cours.devoirs.all()
    for devoir in devoirs:
        contexte.append(f"\n### DEVOIR: {devoir.titre}")
        contexte.append(f"Description: {devoir.description[:200]}")

    return "\n".join(contexte[:8000])  # Limiter à 8000 caractères


def get_system_prompt(
    cours_id: int, niveau_apprenant: str, source: str = "libre", source_titre: str = ""
) -> str:
    """Construit le prompt système pour Claude 3.5 Haiku"""

    cours_contexte = get_cours_contexte_complet(cours_id)

    # Guide des niveaux
    niveaux_guide = {
        "6eme": "très simple, avec des métaphores concrètes (cm1, primaire)",
        "5eme": "simple et imagé (collège)",
        "4eme": "accessible, avec des exemples (collège)",
        "3eme": "clair, avec des illustrations (collège)",
        "seconde": "structuré, mais pas trop technique (lycée)",
        "premiere": "rigoureux, adapté au lycée",
        "terminale": "précis, niveau bac (lycée)",
        "licence1": "universitaire, niveau L1 (début université)",
        "licence2": "universitaire, niveau L2",
        "licence3": "universitaire, niveau L3",
        "master1": "expert, niveau M1",
        "master2": "très expert, niveau M2",
    }

    niveau_clean = niveau_apprenant.lower().strip()
    niveau_desc = niveaux_guide.get(niveau_clean, "adapté au niveau de l'apprenant")

    # Source de la question
    source_desc = {
        "lecon": "depuis une leçon du cours",
        "exercice": "en faisant un exercice",
        "devoir": "en travaillant sur un devoir",
        "libre": "de manière générale",
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
    solde_min = solde_min_ia()

    if wallet.solde < solde_min:
        return (
            False,
            wallet.solde,
            f"Solde minimum requis: {solde_min} FCFA. Votre solde: {wallet.solde} FCFA.",
        )

    if wallet.solde < estimated_cost:
        return (
            False,
            wallet.solde,
            f"Solde insuffisant. Coût estimé: {estimated_cost} FCFA. Votre solde: {wallet.solde} FCFA.",
        )

    success = wallet.debiter(estimated_cost, description)
    if success:
        try:
            YekiCompteIA.crediter_commission(commission_yeki_sur_cout(estimated_cost))
        except Exception:
            # Volontairement large : la comptabilisation interne de la
            # commission Yéki ne doit jamais faire échouer le débit déjà
            # effectué chez l'utilisateur.
            logger.exception("Échec crédit commission Yéki IA")
        return True, wallet.solde, f"Débit de {estimated_cost} FCFA effectué."
    else:
        return False, wallet.solde, "Erreur lors du débit. Veuillez réessayer."
