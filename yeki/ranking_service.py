# yeki/services/ranking_service.py
# ═══════════════════════════════════════════════════════════════════════════
# SERVICE DE CALCUL DES RANGS ET SCORES
# ═══════════════════════════════════════════════════════════════════════════

from django.db import models
from django.db.models import Count, Sum, Avg, Q, F
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import User
from .models import (
    Departement, Cours, Lecon, Devoir, SoumissionDevoir, 
    EvaluationExercice, ProgressionLecon, QuestionForum, 
    ReponseQuestion, RangApprenant, ScoreDetail, Profile
)
import logging
from django.db import transaction

logger = logging.getLogger(__name__)


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
        'devoirs': 1.0,
        'notes_devoirs': 3.0,
        'exercices': 2.0,
        'lecons': 1.0,
        'forum': 0.5,
        'regularite': 0.5,
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
        'devoirs': 100.0,
        'notes_devoirs': 100.0,
        'exercices': 100.0,
        'lecons': 100.0,
        'forum': 100.0,
        'regularite': 100.0,
    }
    
    @classmethod
    def _calculer_score_exercices(cls, apprenant: User, departement: Departement) -> float:
        """
        Score basé sur les résultats aux exercices avec pondération par étoiles.
        """
        cours_ids = Cours.objects.filter(departement=departement).values_list('id', flat=True)
        
        # Récupérer toutes les évaluations d'exercices avec les étoiles
        evaluations = EvaluationExercice.objects.filter(
            user=apprenant,
            exercice__cours_id__in=cours_ids
        ).select_related('exercice').order_by('-date')
        
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
                etoiles = eval.exercice.etoiles if hasattr(eval.exercice, 'etoiles') else 3
                weight = cls.EXERCISE_STAR_WEIGHTS.get(etoiles, 1.0)
                
                total_score += pourcentage * weight
                total_weight += weight
        
        if total_weight == 0:
            return 0.0
        
        moyenne = total_score / total_weight
        return round(min(100, moyenne), 2)


# ═══════════════════════════════════════════════════════════════════════════
# COMMANDE DJANGO POUR EXÉCUTION PROGRAMMÉE
# Créer fichier: management/commands/update_rankings.py
# ═══════════════════════════════════════════════════════════════════════════

"""
# management/commands/update_rankings.py

"""