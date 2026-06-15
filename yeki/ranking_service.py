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
    - Résultats exercices : 2.0
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
    def calculer_score_apprenant(cls, apprenant: User, departement: Departement) -> dict:
        """
        Calcule le score détaillé d'un apprenant dans un département.
        Retourne un dict avec les scores par catégorie et le total.
        """
        scores = {}
        
        # 1. Devoirs rendus à temps (poids 1)
        scores['devoirs'] = cls._calculer_score_devoirs(apprenant, departement)
        
        # 2. Notes aux devoirs (poids 3 - le plus important)
        scores['notes_devoirs'] = cls._calculer_score_notes_devoirs(apprenant, departement)
        
        # 3. Résultats exercices (poids 2)
        scores['exercices'] = cls._calculer_score_exercices(apprenant, departement)
        
        # 4. Progression leçons (poids 1)
        scores['lecons'] = cls._calculer_score_lecons(apprenant, departement)
        
        # 5. Participation forum (poids 0.5)
        scores['forum'] = cls._calculer_score_forum(apprenant, departement)
        
        # 6. Régularité de connexion (poids 0.5)
        scores['regularite'] = cls._calculer_score_regularite(apprenant)
        
        # Calcul du score total pondéré
        total = 0.0
        max_total = 0.0
        for cat, score in scores.items():
            poids = cls.WEIGHTS.get(cat, 1.0)
            max_cat = cls.MAX_SCORES.get(cat, 100.0)
            total += score * poids
            max_total += max_cat * poids
        
        # Normaliser sur 1000
        score_normalise = (total / max_total) * 1000 if max_total > 0 else 0
        
        return {
            'score': round(score_normalise, 2),
            'details': scores,
        }
    
    @classmethod
    def _calculer_score_devoirs(cls, apprenant: User, departement: Departement) -> float:
        """
        Score basé sur les devoirs rendus à temps.
        - 100% si tous les devoirs sont rendus
        - Prorata si certains manquent
        """
        # Récupérer tous les devoirs du département (cours du département)
        cours_ids = Cours.objects.filter(departement=departement).values_list('id', flat=True)
        devoirs = Devoir.objects.filter(cours_lie_id__in=cours_ids, est_publie=True)
        
        total_devoirs = devoirs.count()
        if total_devoirs == 0:
            return 100.0
        
        # Comptage des soumissions à temps
        soumissions = SoumissionDevoir.objects.filter(
            utilisateur=apprenant,
            devoir__in=devoirs,
            statut__in=['soumis', 'corrige']
        )
        
        # Exclure ceux en retard
        soumissions_a_temps = soumissions.exclude(statut='en_retard').count()
        
        score = (soumissions_a_temps / total_devoirs) * 100
        return round(min(100, score), 2)
    
    @classmethod
    def _calculer_score_notes_devoirs(cls, apprenant: User, departement: Departement) -> float:
        """
        Score basé sur les notes obtenues aux devoirs corrigés.
        - Moyenne des notes normalisée sur 20, puis sur 100
        """
        cours_ids = Cours.objects.filter(departement=departement).values_list('id', flat=True)
        devoirs = Devoir.objects.filter(cours_lie_id__in=cours_ids, est_publie=True)
        
        soumissions = SoumissionDevoir.objects.filter(
            utilisateur=apprenant,
            devoir__in=devoirs,
            statut='corrige',
            note__isnull=False
        )
        
        if not soumissions.exists():
            return 0.0
        
        # Moyenne des notes
        notes = [s.note for s in soumissions]
        moyenne = sum(notes) / len(notes)
        
        # Normaliser sur 100 (note sur 20 → pourcentage)
        score = (moyenne / 20) * 100
        return round(min(100, score), 2)
    
    @classmethod
    def _calculer_score_exercices(cls, apprenant: User, departement: Departement) -> float:
        """
        Score basé sur les résultats aux exercices.
        - Prend en compte la première tentative (valorise l'effort initial)
        """
        cours_ids = Cours.objects.filter(departement=departement).values_list('id', flat=True)
        
        # Récupérer toutes les évaluations d'exercices
        evaluations = EvaluationExercice.objects.filter(
            user=apprenant,
            exercice__cours_id__in=cours_ids
        ).order_by('exercice_id', '-date')
        
        # Grouper par exercice et prendre la première tentative
        first_attempts = {}
        for eval in evaluations:
            if eval.exercice_id not in first_attempts:
                first_attempts[eval.exercice_id] = eval
        
        if not first_attempts:
            return 0.0
        
        # Calculer le score moyen des premières tentatives
        total_score = 0
        for eval in first_attempts.values():
            if eval.total > 0:
                pourcentage = (eval.score / eval.total) * 100
                total_score += pourcentage
        
        moyenne = total_score / len(first_attempts)
        return round(min(100, moyenne), 2)
    
    @classmethod
    def _calculer_score_lecons(cls, apprenant: User, departement: Departement) -> float:
        """
        Score basé sur la progression dans les leçons du département.
        """
        cours_ids = Cours.objects.filter(departement=departement).values_list('id', flat=True)
        
        # Compter les leçons du département
        total_lecons = Lecon.objects.filter(cours_id__in=cours_ids).count()
        if total_lecons == 0:
            return 100.0
        
        # Compter les leçons terminées
        lecons_terminees = ProgressionLecon.objects.filter(
            apprenant=apprenant,
            cours_id__in=cours_ids,
            terminee=True
        ).count()
        
        score = (lecons_terminees / total_lecons) * 100
        return round(min(100, score), 2)
    
    @classmethod
    def _calculer_score_forum(cls, apprenant: User, departement: Departement) -> float:
        """
        Score basé sur la participation au forum.
        - Questions posées : 10 pts chacune
        - Réponses données : 5 pts chacune
        - Solutions marquées : 20 pts chacune
        - Max 100 points
        """
        cours_ids = Cours.objects.filter(departement=departement).values_list('id', flat=True)
        
        # Questions posées
        questions = QuestionForum.objects.filter(
            auteur=apprenant,
            cours_id__in=cours_ids
        ).count()
        
        # Réponses données
        reponses = ReponseQuestion.objects.filter(
            auteur=apprenant,
            question__cours_id__in=cours_ids
        ).count()
        
        # Solutions marquées (ses réponses marquées comme solution)
        solutions = ReponseQuestion.objects.filter(
            auteur=apprenant,
            question__cours_id__in=cours_ids,
            est_solution=True
        ).count()
        
        # Calcul du score
        score = (questions * 10) + (reponses * 5) + (solutions * 20)
        return round(min(100, score), 2)
    
    @classmethod
    def _calculer_score_regularite(cls, apprenant: User) -> float:
        """
        Score basé sur la régularité de connexion.
        - Nombre de jours de connexion sur les 30 derniers jours
        """
        from django.contrib.admin.models import LogEntry
        
        # Compter les connexions récentes
        trente_jours = timezone.now() - timedelta(days=30)
        
        # LogEntry pour les connexions (si configuré)
        # Alternative : utiliser last_login
        jours_connectes = set()
        
        # Utiliser last_login comme approximation
        if apprenant.last_login and apprenant.last_login > trente_jours:
            jours_connectes.add(apprenant.last_login.date())
        
        # Compter les jours de connexion via historique (si disponible)
        try:
            from .models import HistoriqueActivite
            connexions = HistoriqueActivite.objects.filter(
                user=apprenant,
                action='login',
                timestamp__gte=trente_jours
            ).values_list('timestamp__date', flat=True).distinct()
            jours_connectes.update(connexions)
        except Exception:
            pass
        
        score = (len(jours_connectes) / 30) * 100
        return round(min(100, score), 2)
    
    @classmethod
    @transaction.atomic
    def mettre_a_jour_rangs_departement(cls, departement: Departement):
        """
        Met à jour les rangs pour tous les apprenants d'un département.
        À exécuter périodiquement (cron) ou après des actions importantes.
        """
        logger.info(f"Calcul des rangs pour le département: {departement.nom}")
        
        # Récupérer tous les apprenants du parcours du département
        apprenants = Profile.objects.filter(
            user_type='apprenant',
            cursus=departement.parcours.nom,
            is_active=True
        ).select_related('user')
        
        scores = []
        
        for profile in apprenants:
            try:
                resultat = cls.calculer_score_apprenant(profile.user, departement)
                
                # Mettre à jour ou créer le rang
                rang, created = RangApprenant.objects.update_or_create(
                    apprenant=profile.user,
                    departement=departement,
                    defaults={
                        'score': resultat['score'],
                        'progression_semaine': 0,  # À calculer séparément
                    }
                )
                
                # Mettre à jour les détails
                for cat, score_cat in resultat['details'].items():
                    ScoreDetail.objects.update_or_create(
                        rang_apprenant=rang,
                        categorie=cat,
                        defaults={
                            'score': score_cat,
                            'poids': cls.WEIGHTS.get(cat, 1.0),
                        }
                    )
                
                scores.append({
                    'apprenant': profile.user,
                    'score': resultat['score'],
                    'rang_obj': rang,
                })
                logger.debug(f"  {profile.user.username}: {resultat['score']:.0f} pts")
                
            except Exception as e:
                logger.error(f"Erreur calcul score pour {profile.user.username}: {e}")
        
        # Classer par score décroissant
        scores.sort(key=lambda x: x['score'], reverse=True)
        
        # Assigner les rangs
        for idx, item in enumerate(scores, start=1):
            item['rang_obj'].rang = idx
            item['rang_obj'].save(update_fields=['rang'])
        
        logger.info(f"Rangs mis à jour: {len(scores)} apprenants traités")
        return len(scores)
    
    @classmethod
    @transaction.atomic
    def mettre_a_jour_tous_les_rangs(cls):
        """Met à jour les rangs pour tous les départements actifs."""
        departements = Departement.objects.filter(est_actif=True)
        total = 0
        for dept in departements:
            total += cls.mettre_a_jour_rangs_departement(dept)
        logger.info(f"Mise à jour globale terminée: {total} apprenants traités")
        return total
    
    @classmethod
    def obtenir_classement_departement(cls, departement: Departement, limit: int = 100):
        """
        Retourne le classement d'un département avec les détails des apprenants.
        """
        rangs = RangApprenant.objects.filter(
            departement=departement,
            rang__isnull=False
        ).select_related('apprenant').order_by('rang')[:limit]
        
        classement = []
        for r in rangs:
            nom = f"{r.apprenant.first_name} {r.apprenant.last_name}".strip()
            if not nom:
                nom = r.apprenant.username
            
            classement.append({
                'rang': r.rang,
                'apprenant_id': r.apprenant.id,
                'nom': nom,
                'username': r.apprenant.username,
                'score': round(r.score, 1),
                'progression': round(r.progression_semaine, 1),
                'details': {
                    d.categorie: round(d.score, 1) 
                    for d in r.details.all()
                } if r.details.exists() else {},
            })
        
        return classement
    
    @classmethod
    def obtenir_historique_apprenant(cls, apprenant: User, departement: Departement = None):
        """Retourne l'historique des scores d'un apprenant."""
        queryset = RangApprenant.objects.filter(apprenant=apprenant)
        if departement:
            queryset = queryset.filter(departement=departement)
        
        return queryset.order_by('-calcule_le').values('departement__nom', 'score', 'rang', 'calcule_le')


# ═══════════════════════════════════════════════════════════════════════════
# COMMANDE DJANGO POUR EXÉCUTION PROGRAMMÉE
# Créer fichier: management/commands/update_rankings.py
# ═══════════════════════════════════════════════════════════════════════════

"""
# management/commands/update_rankings.py

"""