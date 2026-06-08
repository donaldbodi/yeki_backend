# consumers.py - Version complète et corrigée

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from django.utils import timezone
from asgiref.sync import sync_to_async
import logging

logger = logging.getLogger(__name__)


class ForumConsumer(AsyncWebsocketConsumer):
    """Consumer WebSocket pour le forum avec gestion par cours"""

    async def connect(self):
        self.user = self.scope['user']
        
        if self.user.is_anonymous:
            logger.warning("Tentative de connexion WebSocket par utilisateur anonyme")
            await self.close()
            return
        
        # Récupérer l'ID du cours depuis l'URL ou les paramètres
        self.cours_id = self.scope['url_route']['kwargs'].get('cours_id')
        self.room_name = f'forum_cours_{self.cours_id}' if self.cours_id else 'forum_global'
        self.room_group_name = self.room_name
        
        # Rejoindre le groupe
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        logger.info(f"WebSocket connecté: user={self.user.username}, room={self.room_name}")
        
        # Envoyer l'historique des messages
        await self.send_initial_history()
    
    async def disconnect(self, close_code):
        # Quitter le groupe
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        logger.info(f"WebSocket déconnecté: user={self.user.username}, code={close_code}")
    
    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'message')
            
            if message_type == 'new_question':
                await self.handle_new_question(data)
            elif message_type == 'new_reponse':
                await self.handle_new_reponse(data)
            elif message_type == 'like':
                await self.handle_like(data)
            elif message_type == 'join_cours':
                await self.handle_join_cours(data)
            elif message_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except json.JSONDecodeError:
            logger.error(f"JSON invalide reçu: {text_data[:100]}")
        except Exception as e:
            logger.error(f"Erreur dans receive: {e}")
    
    async def handle_new_question(self, data):
        """Traite une nouvelle question"""
        contenu = data.get('contenu', '').strip()
        source = data.get('source', 'libre')
        cours_id = data.get('cours_id')
        lecon_id = data.get('lecon_id')
        lecon_titre = data.get('lecon_titre', '')
        exercice_id = data.get('exercice_id')
        exercice_titre = data.get('exercice_titre', '')
        devoir_id = data.get('devoir_id')
        devoir_titre = data.get('devoir_titre', '')
        
        # Gestion des fichiers (image/audio envoyés en base64 ou via le champ files)
        image_data = data.get('image_data')  # base64
        audio_data = data.get('audio_data')  # base64
        
        if not contenu and not image_data and not audio_data:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Le contenu de la question est requis'
            }))
            return
        
        # Sauvegarder en base de données
        try:
            question = await self.save_question(
                user=self.user,
                contenu=contenu,
                source=source,
                cours_id=cours_id,
                lecon_id=lecon_id,
                lecon_titre=lecon_titre,
                exercice_id=exercice_id,
                exercice_titre=exercice_titre,
                devoir_id=devoir_id,
                devoir_titre=devoir_titre,
                image_data=image_data,
                audio_data=audio_data
            )
            
            # Préparer la réponse
            question_data = await self.serialize_question(question)
            
            # Broadcast à tous les utilisateurs du groupe
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'new_question',
                    'question': question_data
                }
            )
        except Exception as e:
            logger.error(f"Erreur sauvegarde question: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Erreur lors de la création: {str(e)}'
            }))
    
    async def handle_new_reponse(self, data):
        """Traite une nouvelle réponse"""
        question_id = data.get('question_id')
        contenu = data.get('contenu', '').strip()
        
        if not contenu:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Le contenu de la réponse est requis'
            }))
            return
        
        if not question_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'question_id est requis'
            }))
            return
        
        # Sauvegarder la réponse
        reponse = await self.save_reponse(
            user=self.user,
            question_id=question_id,
            contenu=contenu
        )
        
        if reponse:
            reponse_data = await self.serialize_reponse(reponse)
            
            # Broadcast à tous les utilisateurs
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'new_reponse',
                    'question_id': question_id,
                    'reponse': reponse_data
                }
            )
        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Question introuvable'
            }))
    
    async def handle_like(self, data):
        """Gère les likes sur les réponses"""
        reponse_id = data.get('reponse_id')
        
        if not reponse_id:
            return
        
        try:
            liked = await self.toggle_like(self.user.id, reponse_id)
            new_count = await self.get_like_count(reponse_id)
            
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'like_updated',
                    'reponse_id': reponse_id,
                    'liked': liked,
                    'count': new_count
                }
            )
        except Exception as e:
            logger.error(f"Erreur like: {e}")
    
    async def handle_join_cours(self, data):
        """Rejoint une salle spécifique (par cours)"""
        cours_id = data.get('cours_id')
        if cours_id and cours_id != self.cours_id:
            # Quitter l'ancien groupe
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
            
            # Rejoindre le nouveau
            self.cours_id = cours_id
            self.room_name = f'forum_cours_{cours_id}'
            self.room_group_name = self.room_name
            
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            
            await self.send_initial_history()
            
            await self.send(text_data=json.dumps({
                'type': 'room_changed',
                'cours_id': cours_id
            }))
    
    async def send_initial_history(self):
        """Envoie l'historique des messages du cours"""
        try:
            questions = await self.get_recent_questions(
                cours_id=self.cours_id,
                limit=50
            )
            questions_data = [await self.serialize_question(q) for q in questions]
            
            await self.send(text_data=json.dumps({
                'type': 'initial_history',
                'questions': questions_data,
                'cours_id': self.cours_id
            }))
        except Exception as e:
            logger.error(f"Erreur envoi historique: {e}")
    
    # Méthodes de broadcast
    async def new_question(self, event):
        await self.send(text_data=json.dumps({
            'type': 'new_question',
            'question': event['question']
        }))
    
    async def new_reponse(self, event):
        await self.send(text_data=json.dumps({
            'type': 'new_reponse',
            'question_id': event['question_id'],
            'reponse': event['reponse']
        }))
    
    async def like_updated(self, event):
        await self.send(text_data=json.dumps({
            'type': 'like_updated',
            'reponse_id': event['reponse_id'],
            'liked': event['liked'],
            'count': event['count']
        }))
    
    # ═══════════════════════════════════════════════════════════════
    # MÉTHODES DE BASE DE DONNÉES (asynchrones)
    # ═══════════════════════════════════════════════════════════════
    
    @database_sync_to_async
    def save_question(self, user, contenu, source, cours_id=None, lecon_id=None, 
                      lecon_titre='', exercice_id=None, exercice_titre='',
                      devoir_id=None, devoir_titre='',
                      image_data=None, audio_data=None):
        from .models import QuestionForum, Cours
        
        cours = None
        if cours_id:
            try:
                cours = Cours.objects.get(id=cours_id)
            except Cours.DoesNotExist:
                pass
        
        # Gestion des fichiers base64
        image_file = None
        audio_file = None
        
        if image_data:
            import base64
            import uuid
            from django.core.files.base import ContentFile
            
            try:
                format, imgstr = image_data.split(';base64,')
                ext = format.split('/')[-1]
                image_file = ContentFile(
                    base64.b64decode(imgstr),
                    name=f'question_{uuid.uuid4().hex[:8]}.{ext}'
                )
            except Exception:
                pass
        
        if audio_data:
            import base64
            import uuid
            from django.core.files.base import ContentFile
            
            try:
                audio_file = ContentFile(
                    base64.b64decode(audio_data),
                    name=f'audio_{uuid.uuid4().hex[:8]}.m4a'
                )
            except Exception:
                pass
        
        return QuestionForum.objects.create(
            auteur=user,
            contenu=contenu or '',
            source=source,
            cours_id=cours_id,
            cours_titre=cours.titre if cours else '',
            lecon_id=lecon_id,
            lecon_titre=lecon_titre,
            exercice_id=exercice_id,
            exercice_titre=exercice_titre,
            devoir_id=devoir_id,
            devoir_titre=devoir_titre,
            image=image_file,
            audio=audio_file
        )
    
    @database_sync_to_async
    def save_reponse(self, user, question_id, contenu):
        from .models import QuestionForum, ReponseQuestion
        
        try:
            question = QuestionForum.objects.get(id=question_id)
            return ReponseQuestion.objects.create(
                question=question,
                auteur=user,
                contenu=contenu
            )
        except QuestionForum.DoesNotExist:
            return None
    
    @database_sync_to_async
    def serialize_question(self, question):
        from .models import Profile, ReponseQuestion
        from django.db.models import Count
        
        try:
            profile = Profile.objects.get(user=question.auteur)
            auteur_est_enseignant = profile.user_type in [
                'enseignant', 'enseignant_principal', 
                'enseignant_cadre', 'enseignant_admin'
            ]
        except Profile.DoesNotExist:
            auteur_est_enseignant = False
        
        nb_reponses = ReponseQuestion.objects.filter(question=question).count()
        
        return {
            'id': question.id,
            'contenu': question.contenu,
            'source': question.source,
            'cree_le': question.cree_le.isoformat(),
            'est_resolue': question.est_resolue,
            'nb_vues': question.nb_vues,
            'nb_reponses': nb_reponses,
            'auteur_nom': f"{question.auteur.first_name} {question.auteur.last_name}".strip(),
            'auteur_username': question.auteur.username,
            'auteur_est_enseignant': auteur_est_enseignant,
            'lecon_id': question.lecon_id,
            'lecon_titre': question.lecon_titre,
            'cours_id': question.cours_id,
            'cours_titre': question.cours_titre,
            'exercice_id': question.exercice_id,
            'exercice_titre': question.exercice_titre,
            'devoir_id': question.devoir_id,
            'devoir_titre': question.devoir_titre,
            'image_url': question.image.url if question.image else None,
            'audio_url': question.audio.url if question.audio else None,
            'reponses': []
        }
    
    @database_sync_to_async
    def serialize_reponse(self, reponse):
        from .models import Profile, LikeReponse
        
        try:
            profile = Profile.objects.get(user=reponse.auteur)
            auteur_est_enseignant = profile.user_type in [
                'enseignant', 'enseignant_principal', 
                'enseignant_cadre', 'enseignant_admin'
            ]
        except Profile.DoesNotExist:
            auteur_est_enseignant = False
        
        nb_likes = LikeReponse.objects.filter(reponse=reponse).count()
        
        return {
            'id': reponse.id,
            'contenu': reponse.contenu,
            'cree_le': reponse.cree_le.isoformat(),
            'est_solution': reponse.est_solution,
            'auteur_nom': f"{reponse.auteur.first_name} {reponse.auteur.last_name}".strip(),
            'auteur_username': reponse.auteur.username,
            'auteur_est_enseignant': auteur_est_enseignant,
            'nb_likes': nb_likes,
            'mon_like': False,
            'image_url': None,
            'audio_url': None
        }
    
    @database_sync_to_async
    def toggle_like(self, user_id, reponse_id):
        from .models import LikeReponse
        
        try:
            like = LikeReponse.objects.get(
                utilisateur_id=user_id, 
                reponse_id=reponse_id
            )
            like.delete()
            return False
        except LikeReponse.DoesNotExist:
            LikeReponse.objects.create(
                utilisateur_id=user_id, 
                reponse_id=reponse_id
            )
            return True
    
    @database_sync_to_async
    def get_like_count(self, reponse_id):
        from .models import LikeReponse
        return LikeReponse.objects.filter(reponse_id=reponse_id).count()
    
    @database_sync_to_async
    def get_recent_questions(self, cours_id=None, limit=50):
        from .models import QuestionForum
        from django.db.models import Count, Q
        
        queryset = QuestionForum.objects.all()
        
        if cours_id:
            queryset = queryset.filter(Q(cours_id=cours_id) | Q(source='libre'))
        
        return list(
            queryset.annotate(
                nb_reponses=Count('reponses')
            ).order_by('-cree_le')[:limit]
        )