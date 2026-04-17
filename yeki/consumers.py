# consumers.py - À créer dans votre application Django

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from django.utils import timezone
from .models import QuestionForum, ReponseQuestion, Profile, Cours

class ForumConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        
        if self.user.is_anonymous:
            await self.close()
            return
        
        self.room_name = self.scope['url_route']['kwargs'].get('room_name', 'global')
        self.room_group_name = f'forum_{self.room_name}'
        
        # Rejoindre le groupe
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Envoyer l'historique des 50 derniers messages
        await self.send_initial_history()
    
    async def disconnect(self, close_code):
        # Quitter le groupe
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        data = json.loads(text_data)
        message_type = data.get('type', 'message')
        
        if message_type == 'new_question':
            await self.handle_new_question(data)
        elif message_type == 'new_reponse':
            await self.handle_new_reponse(data)
        elif message_type == 'like':
            await self.handle_like(data)
        elif message_type == 'join_room':
            await self.handle_join_room(data)
    
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
        
        if not contenu:
            return
        
        # Sauvegarder en base de données
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
            devoir_titre=devoir_titre
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
    
    async def handle_new_reponse(self, data):
        """Traite une nouvelle réponse"""
        question_id = data.get('question_id')
        contenu = data.get('contenu', '').strip()
        
        if not contenu or not question_id:
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
    
    async def handle_like(self, data):
        """Gère les likes sur les réponses"""
        reponse_id = data.get('reponse_id')
        
        if not reponse_id:
            return
        
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
    
    async def handle_join_room(self, data):
        """Rejoint une salle spécifique (par cours)"""
        cours_id = data.get('cours_id')
        if cours_id:
            new_room = f'forum_cours_{cours_id}'
            await self.channel_layer.group_add(new_room, self.channel_name)
    
    async def send_initial_history(self):
        """Envoie l'historique des messages"""
        questions = await self.get_recent_questions(limit=50)
        questions_data = [await self.serialize_question(q) for q in questions]
        
        await self.send(text_data=json.dumps({
            'type': 'initial_history',
            'questions': questions_data
        }))
    
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
    
    # Méthodes de base de données (asynchrones)
    @database_sync_to_async
    def save_question(self, user, contenu, source, cours_id=None, lecon_id=None, 
                      lecon_titre='', exercice_id=None, exercice_titre='',
                      devoir_id=None, devoir_titre=''):
        cours = None
        if cours_id:
            try:
                cours = Cours.objects.get(id=cours_id)
            except Cours.DoesNotExist:
                pass
        
        return QuestionForum.objects.create(
            auteur=user,
            contenu=contenu,
            source=source,
            cours_id=cours_id,
            cours_titre=cours.titre if cours else '',
            lecon_id=lecon_id,
            lecon_titre=lecon_titre,
            exercice_id=exercice_id,
            exercice_titre=exercice_titre,
            devoir_id=devoir_id,
            devoir_titre=devoir_titre
        )
    
    @database_sync_to_async
    def save_reponse(self, user, question_id, contenu):
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
        profile = Profile.objects.get(user=question.auteur)
        return {
            'id': question.id,
            'contenu': question.contenu,
            'source': question.source,
            'cree_le': question.cree_le.isoformat(),
            'est_resolue': question.est_resolue,
            'nb_vues': question.nb_vues,
            'nb_reponses': question.reponses.count(),
            'auteur_nom': f"{question.auteur.first_name} {question.auteur.last_name}".strip(),
            'auteur_username': question.auteur.username,
            'auteur_est_enseignant': profile.user_type in ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin'],
            'lecon_id': question.lecon_id,
            'lecon_titre': question.lecon_titre,
            'cours_id': question.cours_id,
            'cours_titre': question.cours_titre,
            'exercice_id': question.exercice_id,
            'exercice_titre': question.exercice_titre,
            'devoir_id': question.devoir_id,
            'devoir_titre': question.devoir_titre,
            'reponses': [self.serialize_reponse(r) for r in question.reponses.all()]
        }
    
    @database_sync_to_async
    def serialize_reponse(self, reponse):
        profile = Profile.objects.get(user=reponse.auteur)
        return {
            'id': reponse.id,
            'contenu': reponse.contenu,
            'cree_le': reponse.cree_le.isoformat(),
            'est_solution': reponse.est_solution,
            'auteur_nom': f"{reponse.auteur.first_name} {reponse.auteur.last_name}".strip(),
            'auteur_username': reponse.auteur.username,
            'auteur_est_enseignant': profile.user_type in ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin'],
            'nb_likes': reponse.likes.count(),
            'mon_like': False
        }
    
    @database_sync_to_async
    def toggle_like(self, user_id, reponse_id):
        from .models import LikeReponse
        try:
            like = LikeReponse.objects.get(utilisateur_id=user_id, reponse_id=reponse_id)
            like.delete()
            return False
        except LikeReponse.DoesNotExist:
            LikeReponse.objects.create(utilisateur_id=user_id, reponse_id=reponse_id)
            return True
    
    @database_sync_to_async
    def get_like_count(self, reponse_id):
        from .models import LikeReponse
        return LikeReponse.objects.filter(reponse_id=reponse_id).count()
    
    @database_sync_to_async
    def get_recent_questions(self, limit=50):
        return list(QuestionForum.objects.all().order_by('-cree_le')[:limit])