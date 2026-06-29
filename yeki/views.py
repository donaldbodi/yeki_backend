# views.py
import json

from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework import status, generics
from rest_framework.views import APIView, csrf_exempt
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from django.contrib.auth.hashers import check_password
import uuid
import os
import hashlib
import hmac
import requests
from .ranking_service import RankingService
import logging


from django.contrib.auth import get_user_model
from django.db.models import F, Count, Sum, Avg, Q

from .models import *
from .serializers import *

User = get_user_model()


YEKI_COMMISSION_RATE = 0.15  # 15% de commission sur les formations payantes
PRIX_MINIMUM_OLYMPIADE = 100  # 100 FCFA par apprenant

# ── Helpers locaux ────────────────────────────────────────────────

def _get_profile(user):
    try:
        return user.profile
    except Profile.DoesNotExist:
        return None


def _is_premium(user):
    try:
        return user.abonnement.est_actif
    except Exception:
        return False


def _nom_profil(profile):
    n = f"{profile.user.first_name} {profile.user.last_name}".strip()
    return n or profile.user.username


# views.py - Ajouter/Modifier les vues pour l'admin général

# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Liste complète des enseignants avec filtres
# GET /api/admin-general/enseignants/
# ───────────────────────────────────────────────────────────────────────────
class AdminGeneralEnseignantsListView(APIView):
    """
    GET /api/admin-general/enseignants/
    Retourne la liste complète des enseignants avec filtres.
    
    Query params:
    - search: recherche par nom, email, username
    - user_type: filtre par type d'enseignant
    - parcours_id: filtre par parcours
    - departement_id: filtre par département
    - cours_id: filtre par cours
    - is_active: true/false
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'admin':
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Base queryset - tous les enseignants
        enseignants = Profile.objects.filter(
            user_type__in=['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']
        ).select_related('user').order_by('-user__date_joined')

        # ── Filtres ──────────────────────────────────────────────
        search = request.query_params.get('search', '').strip()
        if search:
            enseignants = enseignants.filter(
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search)
            )

        user_type = request.query_params.get('user_type', '')
        if user_type and user_type in ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']:
            enseignants = enseignants.filter(user_type=user_type)

        is_active = request.query_params.get('is_active')
        if is_active is not None:
            if is_active.lower() == 'true':
                enseignants = enseignants.filter(is_active=True)
            elif is_active.lower() == 'false':
                enseignants = enseignants.filter(is_active=False)

        # Filtres par parcours, département, cours
        parcours_id = request.query_params.get('parcours_id')
        if parcours_id:
            enseignants = enseignants.filter(
                Q(parcours_admin__id=parcours_id) |
                Q(departements_cadre__parcours__id=parcours_id) |
                Q(cours_principal__departement__parcours__id=parcours_id) |
                Q(cours_secondaires__departement__parcours__id=parcours_id)
            ).distinct()

        departement_id = request.query_params.get('departement_id')
        if departement_id:
            enseignants = enseignants.filter(
                Q(departements_cadre__id=departement_id) |
                Q(cours_principal__departement__id=departement_id) |
                Q(cours_secondaires__departement__id=departement_id)
            ).distinct()

        cours_id = request.query_params.get('cours_id')
        if cours_id:
            enseignants = enseignants.filter(
                Q(cours_principal__id=cours_id) |
                Q(cours_secondaires__id=cours_id)
            ).distinct()

        # ── Construction de la réponse ──────────────────────────
        data = []
        for e in enseignants:
            # Récupérer les parcours, départements, cours de l'enseignant
            parcours_list = []
            departements_list = []
            cours_list = []

            # Parcours où il est admin
            for p in Parcours.objects.filter(admin=e):
                parcours_list.append({'id': p.id, 'nom': p.nom})

            # Départements où il est cadre
            for d in Departement.objects.filter(cadre=e):
                departements_list.append({'id': d.id, 'nom': d.nom})
                if d.parcours:
                    parcours_list.append({'id': d.parcours.id, 'nom': d.parcours.nom})

            # Cours où il est principal
            for c in Cours.objects.filter(enseignant_principal=e):
                cours_list.append({'id': c.id, 'titre': c.titre, 'niveau': c.niveau})
                if c.departement:
                    departements_list.append({'id': c.departement.id, 'nom': c.departement.nom})
                    if c.departement.parcours:
                        parcours_list.append({'id': c.departement.parcours.id, 'nom': c.departement.parcours.nom})

            # Cours où il est secondaire
            for c in e.cours_secondaires.all():
                cours_list.append({'id': c.id, 'titre': c.titre, 'niveau': c.niveau})
                if c.departement:
                    departements_list.append({'id': c.departement.id, 'nom': c.departement.nom})
                    if c.departement.parcours:
                        parcours_list.append({'id': c.departement.parcours.id, 'nom': c.departement.parcours.nom})

            # Éliminer les doublons
            parcours_unique = {p['id']: p for p in parcours_list}.values()
            departements_unique = {d['id']: d for d in departements_list}.values()
            cours_unique = {c['id']: c for c in cours_list}.values()

            data.append({
                "id": e.id,
                "username": e.user.username,
                "email": e.user.email,
                "nom": _nom_profil(e),
                "user_type": e.user_type,
                "user_type_label": dict(Profile.USER_TYPES).get(e.user_type, e.user_type),
                "is_active": e.is_active,
                "date_joined": e.user.date_joined.isoformat(),
                "last_login": e.user.last_login.isoformat() if e.user.last_login else None,
                "bio": e.bio or '',
                "phone": e.phone or '',
                "avatar": request.build_absolute_uri(e.avatar.url) if e.avatar else None,
                "parcours": list(parcours_unique),
                "departements": list(departements_unique),
                "cours": list(cours_unique),
            })

        return Response({
            "total": len(data),
            "enseignants": data
        }, status=status.HTTP_200_OK)


# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Désactiver un compte enseignant
# POST /api/admin-general/enseignants/<profile_id>/desactiver/
# ───────────────────────────────────────────────────────────────────────────
class AdminGeneralDesactiverEnseignantView(APIView):
    """
    Désactive un compte enseignant (is_active=False).
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, profile_id):
        try:
            profile_admin = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile_admin.user_type != 'admin':
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN
            )

        enseignant = get_object_or_404(Profile, pk=profile_id)

        if enseignant.user_type not in ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']:
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not enseignant.is_active:
            return Response(
                {"detail": "Ce compte est déjà désactivé."},
                status=status.HTTP_400_BAD_REQUEST
            )

        enseignant.is_active = False
        enseignant.save(update_fields=['is_active'])

        # Envoyer un email de notification
        try:
            _envoyer_email_desactivation_enseignant(enseignant)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Erreur envoi email désactivation: {e}")

        enregistrer_activite(
            user=request.user,
            action='teacher_deactivated',
            description=f"Compte enseignant « {_nom_profil(enseignant)} » désactivé",
            data={
                'enseignant_id': enseignant.id,
                'enseignant_nom': _nom_profil(enseignant),
                'enseignant_email': enseignant.user.email,
                'user_type': enseignant.user_type,
            },
            objet_id=enseignant.id,
            objet_type='Profile',
        )

        return Response({
            "detail": "Compte enseignant désactivé avec succès.",
            "enseignant_id": enseignant.id,
            "nom": _nom_profil(enseignant),
            "is_active": False,
        }, status=status.HTTP_200_OK)


def _envoyer_email_desactivation_enseignant(profile):
    """Envoie un email de notification de désactivation."""
    user = profile.user
    nom = f"{user.first_name} {user.last_name}".strip() or user.username

    sujet = "ℹ️ Votre compte Yéki a été désactivé"

    message_texte = f"""
Bonjour {nom},

Votre compte enseignant sur Yéki a été désactivé par l'administrateur.

Vous ne pouvez plus vous connecter à la plateforme.
Pour toute question, veuillez contacter le support.

— L'équipe Yéki
"""

    message_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
    .container {{ max-width: 480px; margin: 40px auto; background: white;
                  border-radius: 16px; overflow: hidden;
                  box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #2884A9, #2A657D);
               padding: 32px 24px; text-align: center; }}
    .header h1 {{ color: white; margin: 0; font-size: 22px; }}
    .header p  {{ color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 14px; }}
    .body   {{ padding: 32px 24px; text-align: center; }}
    .greeting {{ color: #1E293B; font-size: 15px; margin-bottom: 24px; }}
    .note {{ color: #94A3B8; font-size: 11px; margin-top: 28px;
             border-top: 1px solid #E2E8F0; padding-top: 16px; }}
    .footer {{ background: #F8FAFC; padding: 16px; text-align: center;
               color: #94A3B8; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>ℹ️ Compte désactivé</h1>
      <p>Votre accès a été suspendu</p>
    </div>
    <div class="body">
      <p class="greeting">Bonjour <strong>{nom}</strong>,<br>
      Votre compte enseignant a été désactivé par l'administrateur Yéki.</p>

      <p class="note">
        Vous ne pouvez plus vous connecter à la plateforme.<br>
        Pour toute question, veuillez contacter le support.
      </p>
    </div>
    <div class="footer">© Yeki — Plateforme éducative</div>
  </div>
</body>
</html>
"""

    send_mail(
        subject=sujet,
        message=message_texte,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@yeki.app'),
        recipient_list=[user.email],
        html_message=message_html,
        fail_silently=False,
    )


# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Changer le type d'un enseignant (avec email)
# PATCH /api/admin-general/enseignants/<profile_id>/changer-type/
# Body: { "user_type": "enseignant_principal" }
# ───────────────────────────────────────────────────────────────────────────
class AdminGeneralChangerTypeEnseignantView(APIView):
    """
    Change le type d'un enseignant et envoie un email de notification.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, profile_id):
        try:
            profile_admin = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile_admin.user_type != 'admin':
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN
            )

        enseignant = get_object_or_404(Profile, pk=profile_id)

        # Vérifier que c'est bien un enseignant
        if enseignant.user_type not in ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']:
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not enseignant.is_active:
            return Response(
                {"detail": "Le compte enseignant doit d'abord être activé."},
                status=status.HTTP_400_BAD_REQUEST
            )

        nouveau_type = request.data.get('user_type', '').strip()
        types_valides = ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']

        if nouveau_type not in types_valides:
            return Response(
                {"detail": f"Type invalide. Valeurs: {types_valides}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        ancien_type = enseignant.user_type
        if ancien_type == nouveau_type:
            return Response(
                {"detail": "Le type est déjà identique."},
                status=status.HTTP_400_BAD_REQUEST
            )

        enseignant.user_type = nouveau_type
        enseignant.save(update_fields=['user_type'])

        # Envoyer un email de notification
        try:
            _envoyer_email_changement_type_enseignant(enseignant, ancien_type, nouveau_type)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Erreur envoi email changement type: {e}")

        # Enregistrer dans l'historique
        enregistrer_activite(
            user=request.user,
            action='teacher_type_changed',
            description=f"Type enseignant modifié : {dict(Profile.USER_TYPES).get(ancien_type, ancien_type)} → {dict(Profile.USER_TYPES).get(nouveau_type, nouveau_type)} pour {_nom_profil(enseignant)}",
            data={
                'enseignant_id': enseignant.id,
                'enseignant_nom': _nom_profil(enseignant),
                'ancien_type': ancien_type,
                'nouveau_type': nouveau_type,
                'email': enseignant.user.email,
            },
            objet_id=enseignant.id,
            objet_type='Profile',
        )

        # Ajouter une réponse avec les labels pour le frontend
        return Response({
            "detail": "Type enseignant modifié avec succès. Un email de notification a été envoyé.",
            "enseignant_id": enseignant.id,
            "nom": _nom_profil(enseignant),
            "ancien_type": ancien_type,
            "ancien_type_label": dict(Profile.USER_TYPES).get(ancien_type, ancien_type),
            "nouveau_type": nouveau_type,
            "nouveau_type_label": dict(Profile.USER_TYPES).get(nouveau_type, nouveau_type),
        }, status=status.HTTP_200_OK)


def _envoyer_email_changement_type_enseignant(profile, ancien_type, nouveau_type):
    """Envoie un email de notification pour le changement de type."""
    user = profile.user
    nom = f"{user.first_name} {user.last_name}".strip() or user.username

    type_labels = {
        'enseignant': 'Enseignant',
        'enseignant_principal': 'Enseignant Principal',
        'enseignant_cadre': 'Enseignant Cadre',
        'enseignant_admin': 'Enseignant Administrateur',
    }

    ancien_label = type_labels.get(ancien_type, ancien_type)
    nouveau_label = type_labels.get(nouveau_type, nouveau_type)

    sujet = "📋 Votre grade Yéki a été modifié"

    message_texte = f"""
Bonjour {nom},

L'administrateur Yéki a modifié votre grade sur la plateforme.

Ancien grade : {ancien_label}
Nouveau grade : {nouveau_label}

Connectez-vous pour voir les nouvelles fonctionnalités accessibles avec votre nouveau grade.

— L'équipe Yéki
"""

    message_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
    .container {{ max-width: 480px; margin: 40px auto; background: white;
                  border-radius: 16px; overflow: hidden;
                  box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #2884A9, #2A657D);
               padding: 32px 24px; text-align: center; }}
    .header h1 {{ color: white; margin: 0; font-size: 22px; }}
    .header p  {{ color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 14px; }}
    .body   {{ padding: 32px 24px; text-align: center; }}
    .greeting {{ color: #1E293B; font-size: 15px; margin-bottom: 24px; }}
    .grade-box {{ background: #F1F5F9; border-radius: 12px; padding: 20px; margin: 0 auto;
                  display: inline-block; min-width: 200px; text-align: left; }}
    .grade-box div {{ padding: 4px 0; color: #1E293B; }}
    .grade-box strong {{ color: #2884A9; }}
    .note {{ color: #94A3B8; font-size: 11px; margin-top: 28px;
             border-top: 1px solid #E2E8F0; padding-top: 16px; }}
    .footer {{ background: #F8FAFC; padding: 16px; text-align: center;
               color: #94A3B8; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>📋 Grade mis à jour</h1>
      <p>Votre rôle sur la plateforme a changé</p>
    </div>
    <div class="body">
      <p class="greeting">Bonjour <strong>{nom}</strong>,<br>
      L'administrateur Yéki a modifié votre grade.</p>

      <div class="grade-box">
        <div><strong>Ancien grade :</strong> {ancien_label}</div>
        <div><strong>Nouveau grade :</strong> {nouveau_label}</div>
      </div>

      <p class="note">
        Connectez-vous pour découvrir les nouvelles fonctionnalités accessibles.
      </p>
    </div>
    <div class="footer">© Yeki — Plateforme éducative</div>
  </div>
</body>
</html>
"""

    send_mail(
        subject=sujet,
        message=message_texte,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@yeki.app'),
        recipient_list=[user.email],
        html_message=message_html,
        fail_silently=False,
    )

# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Liste des enseignants en attente d'activation
# GET /api/admin-general/enseignants/attente/
# ───────────────────────────────────────────────────────────────────────────
class AdminGeneralEnseignantsAttenteView(APIView):
    """
    Retourne la liste des enseignants (tous types confondus) dont le compte
    est en attente d'activation (is_active=False).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'admin':
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Récupérer tous les profils enseignants inactifs (is_active=False)
        enseignants = Profile.objects.filter(
            user_type__in=['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin'],
            is_active=False
        ).select_related('user').order_by('-user__date_joined')

        data = []
        for e in enseignants:
            data.append({
                "id": e.id,
                "username": e.user.username,
                "email": e.user.email,
                "nom": f"{e.user.first_name} {e.user.last_name}".strip() or e.user.username,
                "user_type": e.user_type,
                "date_joined": e.user.date_joined.isoformat(),
                "bio": e.bio or '',
                "phone": e.phone or '',
            })

        return Response(data, status=status.HTTP_200_OK)


# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Activer un compte enseignant
# POST /api/admin-general/enseignants/<profile_id>/activer/
# ───────────────────────────────────────────────────────────────────────────
class AdminGeneralActiverEnseignantView(APIView):
    """
    Active un compte enseignant (is_active=True) et envoie un email de confirmation.
    L'enseignant reçoit un email avec son mot de passe (si disponible) et ses identifiants.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, profile_id):
        try:
            profile_admin = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile_admin.user_type != 'admin':
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN
            )

        enseignant = get_object_or_404(Profile, pk=profile_id)

        # Vérifier que c'est bien un enseignant
        if enseignant.user_type not in ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']:
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if enseignant.is_active:
            return Response(
                {"detail": "Ce compte est déjà actif."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Activer le compte
        enseignant.is_active = True
        enseignant.save(update_fields=['is_active'])

        # Envoyer l'email de confirmation
        try:
            _envoyer_email_activation_enseignant(enseignant)
        except Exception as e:
            # Log l'erreur mais ne pas bloquer l'activation
            import logging
            logging.getLogger(__name__).error(f"Erreur envoi email activation: {e}")

        # Enregistrer dans l'historique
        enregistrer_activite(
            user=request.user,
            action='teacher_activated',
            description=f"Compte enseignant « {_nom_profil(enseignant)} » activé ({enseignant.user_type})",
            data={
                'enseignant_id': enseignant.id,
                'enseignant_nom': _nom_profil(enseignant),
                'enseignant_email': enseignant.user.email,
                'user_type': enseignant.user_type,
            },
            objet_id=enseignant.id,
            objet_type='Profile',
        )

        return Response({
            "detail": "Compte enseignant activé avec succès. Un email de confirmation a été envoyé.",
            "enseignant_id": enseignant.id,
            "nom": _nom_profil(enseignant),
            "email": enseignant.user.email,
            "user_type": enseignant.user_type,
        }, status=status.HTTP_200_OK)


def _envoyer_email_activation_enseignant(profile):
    """
    Envoie un email de confirmation à l'enseignant après activation.
    """
    user = profile.user
    nom = f"{user.first_name} {user.last_name}".strip() or user.username

    sujet = "✅ Votre compte Yéki est activé"

    message_texte = f"""
Bonjour {nom},

Félicitations ! Votre compte enseignant a été activé par l'administrateur Yéki.

Vous pouvez maintenant vous connecter à la plateforme avec vos identifiants.

Identifiant : {user.username}
Email : {user.email}

Si vous avez oublié votre mot de passe, utilisez la fonction "Mot de passe oublié" sur la page de connexion.

— L'équipe Yéki
"""

    message_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
    .container {{ max-width: 480px; margin: 40px auto; background: white;
                  border-radius: 16px; overflow: hidden;
                  box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #2884A9, #2A657D);
               padding: 32px 24px; text-align: center; }}
    .header h1 {{ color: white; margin: 0; font-size: 22px; }}
    .header p  {{ color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 14px; }}
    .body   {{ padding: 32px 24px; text-align: center; }}
    .greeting {{ color: #1E293B; font-size: 15px; margin-bottom: 24px; }}
    .credentials {{ background: #F1F5F9; border-radius: 12px; padding: 20px; margin: 0 auto;
                    display: inline-block; min-width: 200px; text-align: left; }}
    .credentials div {{ padding: 4px 0; color: #1E293B; }}
    .credentials strong {{ color: #2884A9; }}
    .note {{ color: #94A3B8; font-size: 11px; margin-top: 28px;
             border-top: 1px solid #E2E8F0; padding-top: 16px; }}
    .footer {{ background: #F8FAFC; padding: 16px; text-align: center;
               color: #94A3B8; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>✅ Compte activé</h1>
      <p>Vous pouvez maintenant accéder à Yéki</p>
    </div>
    <div class="body">
      <p class="greeting">Bonjour <strong>{nom}</strong>,<br>
      Votre compte enseignant a été activé par l'administrateur Yéki.</p>

      <div class="credentials">
        <div><strong>Identifiant :</strong> {user.username}</div>
        <div><strong>Email :</strong> {user.email}</div>
      </div>

      <p class="note">
        Si vous avez oublié votre mot de passe, utilisez la fonction "Mot de passe oublié"
        sur la page de connexion.
      </p>
    </div>
    <div class="footer">© Yeki — Plateforme éducative</div>
  </div>
</body>
</html>
"""

    send_mail(
        subject=sujet,
        message=message_texte,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@yeki.app'),
        recipient_list=[user.email],
        html_message=message_html,
        fail_silently=False,
    )


# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Changer le type d'un enseignant
# PATCH /api/admin-general/enseignants/<profile_id>/changer-type/
# Body: { "user_type": "enseignant_principal" }
# ───────────────────────────────────────────────────────────────────────────
class AdminGeneralChangerTypeEnseignantView(APIView):
    """
    Change le type d'un enseignant (enseignant → enseignant_principal, etc.)
    Valide que le compte est actif (is_active=True).
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, profile_id):
        try:
            profile_admin = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile_admin.user_type != 'admin':
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN
            )

        enseignant = get_object_or_404(Profile, pk=profile_id)

        # Vérifier que c'est bien un enseignant
        if enseignant.user_type not in ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']:
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not enseignant.is_active:
            return Response(
                {"detail": "Le compte enseignant doit d'abord être activé."},
                status=status.HTTP_400_BAD_REQUEST
            )

        nouveau_type = request.data.get('user_type', '').strip()
        types_valides = ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']

        if nouveau_type not in types_valides:
            return Response(
                {"detail": f"Type invalide. Valeurs: {types_valides}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        ancien_type = enseignant.user_type
        enseignant.user_type = nouveau_type
        enseignant.save(update_fields=['user_type'])

        # Enregistrer dans l'historique
        enregistrer_activite(
            user=request.user,
            action='teacher_type_changed',
            description=f"Type enseignant modifié : {ancien_type} → {nouveau_type} pour {_nom_profil(enseignant)}",
            data={
                'enseignant_id': enseignant.id,
                'enseignant_nom': _nom_profil(enseignant),
                'ancien_type': ancien_type,
                'nouveau_type': nouveau_type,
                'email': enseignant.user.email,
            },
            objet_id=enseignant.id,
            objet_type='Profile',
        )

        return Response({
            "detail": "Type enseignant modifié avec succès.",
            "enseignant_id": enseignant.id,
            "nom": _nom_profil(enseignant),
            "ancien_type": ancien_type,
            "nouveau_type": nouveau_type,
        }, status=status.HTTP_200_OK)


# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Modifier un parcours
# PATCH /api/parcours/<parcours_id>/modifier/
# Body: { "nom": "Nouveau nom", "description": "Nouvelle description", "type_parcours": "cursus" }
# ───────────────────────────────────────────────────────────────────────────
class AdminGeneralModifierParcoursView(APIView):
    """
    Modifie un parcours (nom, description, type_parcours).
    Réservé à l'administrateur général.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, parcours_id):
        try:
            profile_admin = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile_admin.user_type != 'admin':
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN
            )

        parcours = get_object_or_404(Parcours, pk=parcours_id)

        data = request.data
        updates = {}
        message = []

        # Nom
        if 'nom' in data:
            nouveau_nom = data['nom'].strip()
            if not nouveau_nom:
                return Response(
                    {"detail": "Le nom ne peut pas être vide."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if nouveau_nom != parcours.nom:
                updates['nom'] = nouveau_nom
                message.append(f"Nom: {parcours.nom} → {nouveau_nom}")

        # Description
        if 'description' in data:
            nouvelle_desc = data['description'].strip()
            if nouvelle_desc != parcours.description:
                updates['description'] = nouvelle_desc
                message.append("Description modifiée")

        # Type de parcours
        if 'type_parcours' in data:
            nouveau_type = data['type_parcours'].strip()
            types_valides = ['cursus', 'prepa', 'formation', 'autre']
            if nouveau_type not in types_valides:
                return Response(
                    {"detail": f"Type de parcours invalide. Valeurs: {types_valides}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if nouveau_type != parcours.type_parcours:
                updates['type_parcours'] = nouveau_type
                message.append(f"Type: {parcours.type_parcours} → {nouveau_type}")

        if not updates:
            return Response(
                {"detail": "Aucune modification spécifiée."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Appliquer les modifications
        for key, value in updates.items():
            setattr(parcours, key, value)
        parcours.save()

        # Enregistrer dans l'historique
        enregistrer_activite(
            user=request.user,
            action='parcours_modified',
            description=f"Parcours « {parcours.nom} » modifié",
            data={
                'parcours_id': parcours.id,
                'parcours_nom': parcours.nom,
                'modifications': message,
            },
            objet_id=parcours.id,
            objet_type='Parcours',
        )

        return Response({
            "detail": "Parcours modifié avec succès.",
            "parcours": {
                "id": parcours.id,
                "nom": parcours.nom,
                "description": parcours.description,
                "type_parcours": parcours.type_parcours,
            },
            "modifications": message,
        }, status=status.HTTP_200_OK)
    

class RepetiteursSearchView(APIView):
    """
    GET /api/repetiteurs/search/?matiere=maths&ville=Yaounde&niveau=Terminale
    Recherche des enseignants (principaux et secondaires) par matière.
    
    Retourne :
    - nom, matière, tarif (5000 FCFA/mois), numéro WhatsApp, ville
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        matiere = request.query_params.get('matiere', '').strip().lower()
        ville = request.query_params.get('ville', '').strip().lower()
        niveau = request.query_params.get('niveau', '').strip().lower()
        
        if not matiere:
            return Response(
                {"detail": "Le paramètre 'matiere' est requis."},
                status=400
            )
        
        # Rechercher les enseignants (principaux et secondaires)
        # qui enseignent dans des cours correspondant à la matière
        profils = Profile.objects.filter(
            user_type__in=['enseignant_principal', 'enseignant'],
            is_active=True
        ).select_related('user')
        
        resultats = []
        for profil in profils:
            # Vérifier si l'enseignant enseigne la matière recherchée
            enseigne_matiere = False
            
            # Cours en tant que principal
            cours_principaux = Cours.objects.filter(
                enseignant_principal=profil,
                matiere__iexact=matiere
            )
            
            # Cours en tant que secondaire
            cours_secondaires = profil.cours_secondaires.filter(
                matiere__iexact=matiere
            )
            
            if cours_principaux.exists() or cours_secondaires.exists():
                enseigne_matiere = True
            
            # Filtrer par ville si spécifiée
            if ville and enseigne_matiere:
                profil_ville = (profil.ville or '').strip().lower()
                if profil_ville and ville not in profil_ville:
                    # Si la ville ne correspond pas, on vérifie si l'enseignant a des cours dans cette ville
                    cours_ville = Cours.objects.filter(
                        departement__ville__iexact=ville,
                        enseignant_principal=profil
                    )
                    if not cours_ville.exists():
                        enseigne_matiere = False
            
            if enseigne_matiere:
                # Numéro WhatsApp (à stocker dans le profil)
                whatsapp = getattr(profil, 'whatsapp', None) or profil.phone or ''
                if not whatsapp.startswith('+237') and whatsapp:
                    whatsapp = f"+237{whatsapp}"
                
                # Récupérer les matières enseignées
                matieres_enseignees = []
                for c in cours_principaux:
                    if c.matiere and c.matiere not in matieres_enseignees:
                        matieres_enseignees.append(c.matiere)
                for c in cours_secondaires:
                    if c.matiere and c.matiere not in matieres_enseignees:
                        matieres_enseignees.append(c.matiere)
                
                resultats.append({
                    "id": profil.id,
                    "nom": _nom_profil(profil),
                    "username": profil.user.username,
                    "matiere": matiere.capitalize(),
                    "matieres": matieres_enseignees,
                    "tarif": 5000,  # 5000 FCFA par mois
                    "whatsapp": whatsapp,
                    "avatar": request.build_absolute_uri(profil.avatar.url) if profil.avatar else None,
                    "ville": profil.ville or '',
                    "disponible": True,
                    "niveau": profil.niveau or '',
                })
        
        return Response({
            "matiere": matiere,
            "total": len(resultats),
            "repetiteurs": resultats,
            "tarif_mensuel": 5000,
            "message_whatsapp_template": f"Bonjour, je souhaite prendre des cours de {matiere} avec vous à domicile.",
        }, status=200)


def repetiteurs_page(request):
    """
    Page de recherche de répétiteurs
    """
    return render(request, 'repetiteurs.html')


class PrincipalDashboardAPIView(APIView):
    """
    GET /api/principal/dashboard_stats/
    Retourne les statistiques du dashboard pour l'enseignant principal.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_principal':
            return Response(
                {"detail": "Accès réservé aux enseignants principaux."},
                status=403
            )

        # Récupérer les cours du principal
        cours = Cours.objects.filter(enseignant_principal=profile)
        cours_ids = cours.values_list('id', flat=True)

        # Statistiques de base
        nb_cours = cours.count()
        nb_lecons = Lecon.objects.filter(cours__in=cours_ids).count()
        nb_devoirs = Devoir.objects.filter(cours_lie__in=cours_ids).count()
        
        # Apprenants uniques - CORRECTION : utiliser Profile.objects.filter avec cursus
        # Récupérer les noms de parcours des départements des cours
        parcours_noms = Departement.objects.filter(
            cours__in=cours_ids
        ).values_list('parcours__nom', flat=True).distinct()
        
        apprenants = Profile.objects.filter(
            user_type='apprenant',
            cursus__in=parcours_noms,
            is_active=True
        ).distinct().count()

        # Taux de rendu global
        total_rendus = SoumissionDevoir.objects.filter(
            devoir__cours_lie__in=cours_ids,
            statut__in=['soumis', 'corrige', 'en_retard']
        ).count()
        total_attendu = nb_devoirs * apprenants if apprenants > 0 else 1
        taux_rendu = (total_rendus / total_attendu * 100) if total_attendu > 0 else 0

        # Moyenne globale
        moyenne_globale = SoumissionDevoir.objects.filter(
            devoir__cours_lie__in=cours_ids,
            note__isnull=False
        ).aggregate(Avg('note'))['note__avg'] or 0

        # Retards
        retards = SoumissionDevoir.objects.filter(
            devoir__cours_lie__in=cours_ids,
            soumis_le__gt=F('devoir__date_limite')
        ).count()

        # Apprenants à risque (ceux avec taux de rendu < 50%)
        apprenants_risque = []
        for p in Profile.objects.filter(
            user_type='apprenant',
            cursus__in=parcours_noms,
            is_active=True
        ).select_related('user'):
            # Compter les soumissions de cet apprenant pour les cours du principal
            soumissions = SoumissionDevoir.objects.filter(
                devoir__cours_lie__in=cours_ids,
                utilisateur=p.user
            )
            nb_rendus = soumissions.filter(
                statut__in=['soumis', 'corrige', 'en_retard']
            ).count()
            nb_devoirs_total = Devoir.objects.filter(cours_lie__in=cours_ids).count()
            
            if nb_devoirs_total > 0:
                taux = (nb_rendus / nb_devoirs_total * 100)
                if taux < 50:
                    moyenne = soumissions.filter(
                        note__isnull=False
                    ).aggregate(Avg('note'))['note__avg'] or 0
                    
                    raison = "Taux de rendu faible" if taux < 30 else "Taux de rendu moyen"
                    
                    apprenants_risque.append({
                        'id': p.id,
                        'nom': p.user.last_name or '',
                        'prenom': p.user.first_name or '',
                        'email': p.user.email or '',
                        'taux_rendu': round(taux, 1),
                        'moyenne': round(moyenne, 1),
                        'raison': raison,
                    })

        # Devoirs par cours
        devoirs_par_cours = []
        for c in cours:
            devoirs = Devoir.objects.filter(cours_lie=c)
            nb_devoirs_cours = devoirs.count()
            
            # Compter les apprenants de ce cours
            apprenants_cours = Profile.objects.filter(
                user_type='apprenant',
                cursus=c.departement.parcours.nom if c.departement and c.departement.parcours else '',
                is_active=True
            ).count()
            
            rendus_cours = SoumissionDevoir.objects.filter(
                devoir__in=devoirs,
                statut__in=['soumis', 'corrige', 'en_retard']
            )
            total_rendus_cours = rendus_cours.count()
            total_attendu_cours = nb_devoirs_cours * apprenants_cours if apprenants_cours > 0 else 1
            taux_cours = (total_rendus_cours / total_attendu_cours * 100) if total_attendu_cours > 0 else 0
            
            # Détails des devoirs
            details_devoirs = []
            for devoir in devoirs:
                rendus_devoir = rendus_cours.filter(devoir=devoir)
                nb_rendus = rendus_devoir.count()
                nb_retards = rendus_devoir.filter(
                    soumis_le__gt=devoir.date_limite
                ).count()
                note_moyenne = rendus_devoir.filter(
                    note__isnull=False
                ).aggregate(Avg('note'))['note__avg'] or 0
                
                details_devoirs.append({
                    'id': devoir.id,
                    'titre': devoir.titre,
                    'date_limite': devoir.date_limite.isoformat(),
                    'nb_rendus': nb_rendus,
                    'nb_retards': nb_retards,
                    'taux_rendu': (nb_rendus / apprenants_cours * 100) if apprenants_cours > 0 else 0,
                    'note_moyenne': round(note_moyenne, 1) if note_moyenne else 0,
                    'type_correction': getattr(devoir, 'type_correction', 'auto')
                })
            
            devoirs_par_cours.append({
                'cours_id': c.id,
                'cours_titre': c.titre,
                'nb_devoirs': nb_devoirs_cours,
                'taux_rendu': round(taux_cours, 1),
                'details_devoirs': details_devoirs
            })

        # Tendance des rendus (7 derniers jours)
        tendance_rendus = []
        for i in range(6, -1, -1):
            date = timezone.now().date() - timedelta(days=i)
            nb_rendus_jour = SoumissionDevoir.objects.filter(
                devoir__cours_lie__in=cours_ids,
                soumis_le__date=date,
                statut__in=['soumis', 'corrige', 'en_retard']
            ).count()
            tendance_rendus.append({
                'date': date.isoformat(),
                'nb_rendus': nb_rendus_jour
            })

        return Response({
            'nom': f"{profile.user.first_name} {profile.user.last_name}".strip() or profile.user.username,
            'stats': {
                'nb_cours': nb_cours,
                'nb_lecons': nb_lecons,
                'nb_devoirs': nb_devoirs,
                'nb_apprenants': apprenants,
                'taux_rendu_global': round(taux_rendu, 1),
                'moyenne_globale': round(moyenne_globale, 1) if moyenne_globale else 0,
                'nb_retards': retards,
            },
            'devoirs_par_cours': devoirs_par_cours,
            'apprenants_risque': apprenants_risque,
            'tendance_rendus': tendance_rendus
        })


class PrincipalApprenantsCoursAPIView(APIView):
    """
    GET /api/principal/apprenants_cours/
    Query param: ?cours_id=123
    Retourne la liste des apprenants d'un cours avec leurs statistiques.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_principal':
            return Response(
                {"detail": "Accès réservé aux enseignants principaux."},
                status=403
            )

        cours_id = request.query_params.get('cours_id')
        if not cours_id:
            return Response({"detail": "cours_id requis."}, status=400)

        try:
            cours = Cours.objects.get(id=cours_id, enseignant_principal=profile)
        except Cours.DoesNotExist:
            return Response({"detail": "Cours non trouvé ou non assigné."}, status=404)

        # Récupérer les apprenants du cours via le parcours
        apprenants = Profile.objects.filter(
            user_type='apprenant',
            cursus=cours.departement.parcours.nom,
            is_active=True
        ).select_related('user')

        result = []
        for apprenant in apprenants:
            # Récupérer les soumissions de l'apprenant pour ce cours
            soumissions = SoumissionDevoir.objects.filter(
                devoir__cours_lie=cours,
                utilisateur=apprenant.user
            )
            
            nb_rendus = soumissions.filter(
                statut__in=['soumis', 'corrige', 'en_retard']
            ).count()
            nb_devoirs_total = Devoir.objects.filter(cours_lie=cours).count()
            taux_rendu = (nb_rendus / nb_devoirs_total * 100) if nb_devoirs_total > 0 else 0
            
            moyenne = soumissions.filter(
                note__isnull=False
            ).aggregate(Avg('note'))['note__avg'] or 0
            
            dernier_rendu = soumissions.order_by('-soumis_le').first()
            
            nb_retards = soumissions.filter(
                soumis_le__gt=F('devoir__date_limite')
            ).count()
            
            result.append({
                'id': apprenant.id,
                'nom': f"{apprenant.user.first_name} {apprenant.user.last_name}".strip() or apprenant.user.username,
                'email': apprenant.user.email,
                'taux_rendu': round(taux_rendu, 1),
                'moyenne': round(moyenne, 1),
                'dernier_rendu': dernier_rendu.soumis_le.isoformat() if dernier_rendu else None,
                'nb_retards': nb_retards
            })

        return Response(result)


class PrincipalRendusDevoirsAPIView(APIView):
    """
    GET /api/principal/rendus_devoirs/
    Query param: ?devoir_id=123 (ou ?cours_id=123)
    Retourne les détails des rendus pour un devoir ou un cours.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_principal':
            return Response(
                {"detail": "Accès réservé aux enseignants principaux."},
                status=403
            )

        devoir_id = request.query_params.get('devoir_id')
        cours_id = request.query_params.get('cours_id')

        if not devoir_id and not cours_id:
            return Response({"detail": "devoir_id ou cours_id requis."}, status=400)

        soumissions = SoumissionDevoir.objects.all()

        if devoir_id:
            try:
                devoir = Devoir.objects.get(id=devoir_id, cours_lie__enseignant_principal=profile)
                soumissions = soumissions.filter(devoir=devoir)
            except Devoir.DoesNotExist:
                return Response({"detail": "Devoir non trouvé."}, status=404)
        elif cours_id:
            try:
                cours = Cours.objects.get(id=cours_id, enseignant_principal=profile)
                soumissions = soumissions.filter(devoir__cours_lie=cours)
            except Cours.DoesNotExist:
                return Response({"detail": "Cours non trouvé."}, status=404)

        result = []
        for s in soumissions.select_related('utilisateur', 'devoir'):
            result.append({
                'id': s.id,
                'apprenant': f"{s.utilisateur.first_name} {s.utilisateur.last_name}".strip() or s.utilisateur.username,
                'devoir': s.devoir.titre,
                'date_rendu': s.soumis_le.isoformat() if s.soumis_le else None,
                'note': s.note,
                'est_en_retard': s.est_en_retard,
                'statut': s.statut
            })

        return Response({
            'rendus': result,
            'total': len(result)
        })

class ClassementDepartementView(APIView):
    """
    GET /api/classement/departement/<departement_id>/
    Retourne le classement des apprenants d'un département.
    
    Query params:
    - limit: nombre de résultats (défaut 100, max 200)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        departement = get_object_or_404(Departement, pk=departement_id)
        
        # Vérifier que l'utilisateur a accès à ce département
        if profile.user_type == 'apprenant':
            # Vérifier que l'apprenant appartient à ce département
            if profile.cursus != departement.parcours.nom:
                return Response(
                    {"detail": "Vous n'avez pas accès à ce classement."},
                    status=403
                )
        elif profile.user_type == 'enseignant_cadre':
            if departement.cadre != profile:
                return Response(
                    {"detail": "Ce département ne vous appartient pas."},
                    status=403
                )
        elif profile.user_type not in ['admin', 'enseignant_admin']:
            return Response(
                {"detail": "Accès non autorisé."},
                status=403
            )
        
        try:
            limit = min(int(request.query_params.get('limit', 100)), 200)
        except (TypeError, ValueError):
            limit = 100
        
        classement = RankingService.obtenir_classement_departement(departement, limit)
        
        # Ajouter des métadonnées
        stats = {
            'total_apprenants': len(classement),
            'score_min': classement[-1]['score'] if classement else 0,
            'score_max': classement[0]['score'] if classement else 0,
            'score_moyen': round(sum(c['score'] for c in classement) / len(classement), 1) if classement else 0,
        }
        
        return Response({
            'departement': {
                'id': departement.id,
                'nom': departement.nom,
            },
            'mon_rang': None,  # Rempli plus bas si apprenant
            'classement': classement,
            'stats': stats,
        })
    
    def get(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        departement = get_object_or_404(Departement, pk=departement_id)
        
        # Vérifications d'accès
        if profile.user_type == 'apprenant':
            if profile.cursus != departement.parcours.nom:
                return Response(
                    {"detail": "Vous n'avez pas accès à ce classement."},
                    status=403
                )
        elif profile.user_type == 'enseignant_cadre':
            if departement.cadre != profile:
                return Response(
                    {"detail": "Ce département ne vous appartient pas."},
                    status=403
                )
        elif profile.user_type not in ['admin', 'enseignant_admin']:
            return Response(
                {"detail": "Accès non autorisé."},
                status=403
            )
        
        try:
            limit = min(int(request.query_params.get('limit', 100)), 200)
        except (TypeError, ValueError):
            limit = 100
        
        classement = RankingService.obtenir_classement_departement(departement, limit)
        
        # Trouver le rang de l'utilisateur connecté (si apprenant)
        mon_rang = None
        if profile.user_type == 'apprenant':
            for item in classement:
                if item['apprenant_id'] == request.user.id:
                    mon_rang = {
                        'rang': item['rang'],
                        'score': item['score'],
                        'progression': item['progression'],
                    }
                    break
        
        stats = {
            'total': len(classement),
            'moyenne': round(sum(c['score'] for c in classement) / len(classement), 1) if classement else 0,
            'meilleur': classement[0]['score'] if classement else 0,
        }
        
        return Response({
            'departement': {
                'id': departement.id,
                'nom': departement.nom,
            },
            'mon_rang': mon_rang,
            'classement': classement,
            'stats': stats,
        })


class MonScoreGlobalView(APIView):
    """
    GET /api/classement/mon-score/
    Retourne le score et le rang de l'apprenant dans son département principal.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)
        
        if profile.user_type != 'apprenant':
            return Response({"detail": "Réservé aux apprenants."}, status=403)
        
        if not profile.cursus:
            return Response({"detail": "Aucun cursus assigné."}, status=404)
        
        # Récupérer le département principal du parcours de l'apprenant
        try:
            parcours = Departement.objects.filter(
                parcours__nom=profile.cursus,
                parcours__type_parcours='cursus'
            ).first()
        except Exception:
            parcours = None
        
        if not parcours:
            return Response({"detail": "Aucun département trouvé pour votre cursus."}, status=404)
        
        # Récupérer le rang
        rang = RangApprenant.objects.filter(
            apprenant=request.user,
            departement=parcours
        ).first()
        
        # Scores par catégorie
        scores_categorie = {}
        if rang:
            details = rang.details.all()
            scores_categorie = {d.categorie: round(d.score, 1) for d in details}
        
        return Response({
            'score': round(rang.score, 1) if rang else 0,
            'rang': rang.rang if rang else None,
            'total_apprenants': RangApprenant.objects.filter(departement=parcours, rang__isnull=False).count(),
            'progression': round(rang.progression_semaine, 1) if rang else 0,
            'scores_categorie': scores_categorie,
            'departement': {
                'id': parcours.id,
                'nom': parcours.nom,
            }
        })


class RecalculerClassementView(APIView):
    """
    POST /api/classement/recalculer/
    Body: { "departement_id": 123 }  (optionnel)
    Force le recalcul des rangs. Réservé aux admins.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)
        
        if profile.user_type not in ['admin', 'enseignant_admin']:
            return Response({"detail": "Accès réservé aux administrateurs."}, status=403)
        
        departement_id = request.data.get('departement_id')
        
        if departement_id:
            departement = get_object_or_404(Departement, pk=departement_id)
            count = RankingService.mettre_a_jour_rangs_departement(departement)
            message = f"Classement recalculé pour {departement.nom}: {count} apprenants"
        else:
            count = RankingService.mettre_a_jour_tous_les_rangs()
            message = f"Classement global recalculé: {count} apprenants"
        
        return Response({
            'detail': message,
            'apprenants_traites': count,
        })


# ═══════════════════════════════════════════════════════════════
# ENDPOINT : Liste des niveaux disponibles
# GET /api/niveaux/
# ═══════════════════════════════════════════════════════════════

class ListeNiveauxView(APIView):
    """
    GET /api/niveaux/
    Retourne la liste des niveaux uniques déjà enregistrés en base.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Récupérer tous les niveaux distincts depuis les cours existants
        niveaux = Cours.objects.values_list('niveau', flat=True).distinct().order_by('niveau')
        
        resultats = list(niveaux)
        
        return Response(sorted(resultats))


# ═══════════════════════════════════════════════════════════════
# ENDPOINT : Olympiades du cadre connecté
# GET /api/olympiades/mes-olympiades/
# ═══════════════════════════════════════════════════════════════

class MesOlympiadesCadreView(APIView):
    """
    GET /api/olympiades/mes-olympiades/
    Retourne toutes les olympiades créées par le cadre connecté.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_cadre':
            return Response({"detail": "Accès réservé aux cadres."}, status=403)

        olympiades = Olympiade.objects.filter(
            organisateur=profile
        ).select_related('devoir').order_by('-date_debut_olympiade')

        data = []
        for o in olympiades:
            data.append({
                "id": o.id,
                "titre": o.titre,
                "matiere": o.matiere,
                "niveau": o.niveau,
                "edition": o.edition,
                "statut": o.statut_auto,
                "date_debut_olympiade": o.date_debut_olympiade.isoformat(),
                "date_fin_olympiade": o.date_fin_olympiade.isoformat(),
                "nb_inscrits": o.inscriptions.count(),
                "devoir_id": o.devoir.id if o.devoir else None,
                "est_publiee": o.devoir.est_publie if o.devoir else False,
                "prix_1er": o.prix_1er,
                "prix_2eme": o.prix_2eme,
                "prix_3eme": o.prix_3eme,
            })

        return Response(data)


class LatestVersionView(APIView):
    """
    GET /api/latest-version/
    Retourne la dernière version disponible pour une plateforme.
    
    Paramètres query:
    - platform: 'android' | 'ios' | 'web' (défaut: 'android')
    - current_version: int (optionnel, pour vérifier si une mise à jour est disponible)
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        platform = request.query_params.get('platform', 'android')
        current_version = request.query_params.get('current_version')
        
        try:
            # Récupérer la dernière version active
            version = AppVersion.objects.filter(
                platform=platform,
                is_active=True
            ).latest('version_code')
            
            # Si current_version est fourni, vérifier si une mise à jour est nécessaire
            is_update_available = False
            if current_version:
                try:
                    current = int(current_version)
                    is_update_available = version.version_code > current
                except (ValueError, TypeError):
                    is_update_available = True
            
            data = AppVersionSerializer(version).data
            data['is_update_available'] = is_update_available
            
            return Response(data, status=status.HTTP_200_OK)
            
        except AppVersion.DoesNotExist:
            # Version par défaut si rien n'existe
            return Response({
                'platform': platform,
                'version_code': 1,
                'version_name': 'v1.0.0',
                'download_url': '',
                'changelog': 'Version initiale',
                'min_version_code': 1,
                'force_update': False,
                'is_active': True,
                'is_update_available': False,
            }, status=status.HTTP_200_OK)

class AdminVersionCreateView(APIView):
    """
    POST /api/admin/versions/
    Crée une nouvelle version (réservé admin)
    """
    #authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Vérifier que l'utilisateur est admin
        if not request.user.is_staff:
            return Response(
                {'detail': 'Permission refusée. Admin requis.'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = AppVersionCreateSerializer(data=request.data)
        if serializer.is_valid():
            # Désactiver les anciennes versions de la même plateforme
            platform = serializer.validated_data['platform']
            AppVersion.objects.filter(platform=platform, is_active=True).update(is_active=False)
            
            version = serializer.save()
            return Response(
                AppVersionSerializer(version).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AdminVersionListView(APIView):
    """
    GET /api/admin/versions/
    Liste toutes les versions (réservé admin)
    """
    #authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        if not request.user.is_staff:
            return Response(
                {'detail': 'Permission refusée. Admin requis.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        versions = AppVersion.objects.all().order_by('-version_code')
        serializer = AppVersionSerializer(versions, many=True)
        return Response(serializer.data)

class CheckUpdateView(APIView):
    """
    GET /api/check-update/
    Vérifie si une mise à jour est disponible pour la version actuelle.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        platform = request.query_params.get('platform', 'android')
        current_version = request.query_params.get('current_version')
        
        if not current_version:
            return Response(
                {'detail': 'current_version est requis'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            current = int(current_version)
            version = AppVersion.objects.filter(
                platform=platform,
                is_active=True
            ).latest('version_code')
            
            if version.version_code > current:
                return Response({
                    'update_available': True,
                    'version': AppVersionSerializer(version).data,
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'update_available': False,
                    'message': 'Vous utilisez déjà la dernière version.'
                }, status=status.HTTP_200_OK)
                
        except AppVersion.DoesNotExist:
            return Response({
                'update_available': False,
                'message': 'Version non trouvée.'
            }, status=status.HTTP_200_OK)
        except ValueError:
            return Response(
                {'detail': 'current_version doit être un entier'},
                status=status.HTTP_400_BAD_REQUEST
            )


def _progression_cours(user, cours_qs):
    """Calcule le % de progression par cours pour cet apprenant."""
    progressions = ProgressionLecon.objects.filter(
        apprenant=user, cours__in=cours_qs,
    ).values('cours_id', 'terminee')

    prog_map = {}
    for c in cours_qs:
        total = c.nb_lecons or Lecon.objects.filter(cours=c).count()
        if total == 0:
            prog_map[c.id] = 0.0
            continue
        terminees = sum(1 for p in progressions if p['cours_id'] == c.id and p['terminee'])
        prog_map[c.id] = round((terminees / total) * 100, 1)
    return prog_map


# views_paiement.py

# Configuration CinetPay
CINETPAY_API_KEY = settings.CINETPAY_API_KEY
CINETPAY_SITE_ID = settings.CINETPAY_SITE_ID
CINETPAY_API_URL = "https://api-checkout.cinetpay.com/v2/payment"


def _serialise_cours(c, prog_map):
    """Sérialise un Cours au format attendu par Flutter."""
    ep_nom = '—'
    if c.enseignant_principal:
        ep = c.enseignant_principal
        ep_nom = f"{ep.user.first_name} {ep.user.last_name}".strip() or ep.user.username
    dept = c.departement
    return {
        'id':                   c.id,
        'title':                c.titre,
        'description':          c.description_brief or '',
        'enseignant_principal': ep_nom,
        'lessons':              c.nb_lecons,
        'assignments':          c.nb_devoirs,
        'icon':                 c.icon_name or 'school',
        'color':                c.color_code or '#2884A0',
        'progression':          prog_map.get(c.id, 0.0),
        # Infos département (= concours/formation)
        'departement_id':       dept.id,
        'departement_nom':      dept.nom,
        'parcours_nom':         dept.parcours.nom if dept.parcours else '',
    }

# ---------------------------
# Utilitaire : vérification de rôle
# ---------------------------
def check_role(user, allowed_roles):
    """
    Raise PermissionDenied si user.user_type n'est pas dans allowed_roles.
    """
    if not hasattr(user, "user_type"):
        raise PermissionDenied("Utilisateur non valide.")
    if user.user_type not in allowed_roles:
        raise PermissionDenied("Vous n’avez pas les permissions nécessaires.")


# ---------------------------
# Ajout / retrait enseignant secondaire
# ---------------------------


class AddEnseignantSecondaireView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, cours_id):
        # 1️⃣ Récupération du cours
        cours = get_object_or_404(Cours, pk=cours_id)

        # 2️⃣ Profil du demandeur
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            raise PermissionDenied("Profil utilisateur introuvable.")

        # 3️⃣ Vérification : enseignant principal du cours
        if cours.enseignant_principal != profile:
            raise PermissionDenied(
                "Action réservée à l’enseignant principal de ce cours."
            )

        # 4️⃣ Récupération de l'enseignant secondaire
        enseignant_id = request.data.get("enseignant_id")
        if not enseignant_id:
            return Response(
                {"detail": "L'id de l'enseignant est requis."},
                status=status.HTTP_400_BAD_REQUEST
            )

        enseignant = get_object_or_404(Profile, pk=enseignant_id)

        # 5️⃣ Vérification du rôle
        if enseignant.user_type != "enseignant":
            return Response(
                {"detail": "L'utilisateur choisi n'est pas un enseignant secondaire."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 6️⃣ Vérification doublon
        if cours.enseignants.filter(pk=enseignant.pk).exists():
            return Response(
                {"detail": "Enseignant déjà présent dans ce cours."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 7️⃣ Ajout via la logique métier
        cours.enseignants.add(enseignant)

        enregistrer_activite(
       user=request.user,
       action='secondary_added',
       description=f"{enseignant.user.get_full_name() or enseignant.user.username} ajouté comme enseignant secondaire dans « {cours.titre} »",
       data={
           'enseignant': enseignant.user.get_full_name() or enseignant.user.username,
           'cours':      cours.titre,
       },
       objet_id=cours.id,
       objet_type='Cours',
   )

        return Response(
            CoursSerializer(cours).data,
            status=status.HTTP_200_OK
        )


class RemoveEnseignantSecondaireView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        profile = request.user.profile
        if cours.enseignant_principal != profile:
            raise PermissionDenied("Action réservée à l’enseignant principal du cours.")

        enseignant_id = request.data.get('enseignant_id')
        if not enseignant_id:
            return Response({"detail": "L'id de l'enseignant est requis."}, status=status.HTTP_400_BAD_REQUEST)

        enseignant = get_object_or_404(Profile, pk=enseignant_id, user_type="enseignant")
        if enseignant not in cours.enseignants.all():
            return Response({"detail": "Enseignant non présent dans le cours."}, status=status.HTTP_400_BAD_REQUEST)

        cours.enseignants.remove(enseignant)
        cours.save()
        return Response(CoursSerializer(cours).data, status=status.HTTP_200_OK)


class ApprenantCursusAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        if profile.user_type != 'apprenant':
            return Response({"detail": "Accès réservé aux apprenants"}, status=403)

        if not profile.cursus:
            return Response([], status=200)

        # Récupérer le parcours du cursus
        try:
            parcours = Parcours.objects.get(nom=profile.cursus, type_parcours='cursus')
        except Parcours.DoesNotExist:
            return Response([], status=200)

        # Utiliser le niveau enregistré dans le profil
        niveau_apprenant = profile.niveau or ''
        
        # Récupérer les départements du cursus
        depts = Departement.objects.filter(parcours=parcours, est_actif=True)
        
        # Récupérer les cours du niveau EXACT de l'apprenant (pas inférieur, pas supérieur)
        cours_qs = Cours.objects.filter(
            departement__in=depts,
            niveau=niveau_apprenant  # ← Filtre exact sur le niveau
        ).select_related('enseignant_principal__user')
        
        # Calculer les progressions
        prog_map = _progression_cours(request.user, cours_qs)
        
        result = []
        for c in cours_qs:
            ep_nom = '—'
            if c.enseignant_principal:
                ep = c.enseignant_principal
                ep_nom = f"{ep.user.first_name} {ep.user.last_name}".strip() or ep.user.username

            result.append({
                'id': c.id,
                'title': c.titre,
                'description': c.description_brief or '',
                'enseignant_principal': ep_nom,
                'lessons': c.nb_lecons,
                'assignments': c.nb_devoirs,
                'icon': c.icon_name or 'school',
                'color': c.color_code or '#2884A0',
                'progression': prog_map.get(c.id, 0.0),
                'niveau': c.niveau,
            })

        return Response(result, status=200)


# ---------------------------
# Créer / Mettre à jour un cours
# ---------------------------
class CoursCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        # Ici, la logique de création est déléguée au serializer ou au manager métier
        serializer = CoursCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            cours = serializer.save()
            from .models import enregistrer_activite
            enregistrer_activite(
                user=request.user,
                action='course_created',
                description=f"Cours « {cours.titre} » créé dans le département {cours.departement.nom}",
                data={
                    'titre':       cours.titre,
                    'niveau':      cours.niveau,
                    'departement': cours.departement.nom,
                },
                objet_id=cours.id,
                objet_type='Cours',
            )
            return Response(CoursSerializer(cours).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CoursUpdateView(generics.RetrieveAPIView, generics.UpdateAPIView):
    queryset = Cours.objects.select_related(
        'departement',
        'enseignant_principal'
    )
    serializer_class = CoursSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch']

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        cours = self.get_object()
        profile = request.user.profile
        payload = request.data

        # 🔐 Permissions
        if profile.user_type == "enseignant_principal":
            allowed_fields = {
                "titre", "niveau",
                "description_brief",
                "color_code",
                "icon_name",
            }
        elif profile.user_type == "enseignant_cadre":
            allowed_fields = "__all__"
        else:
            raise PermissionDenied("Accès interdit.")

        # 📝 Titre
        if 'titre' in payload:
            cours.titre = payload['titre'].strip()

        # 🎓 Niveau
        if 'niveau' in payload:
            cours.niveau = payload['niveau'].strip()

        # 🧾 Description courte
        if 'description_brief' in payload:
            cours.description_brief = payload['description_brief']

        # 🎨 Couleur
        if 'color_code' in payload:
            cours.color_code = payload['color_code']

        # 🧩 Icône
        if 'icon_name' in payload:
            cours.icon_name = payload['icon_name']

        # 👨‍🏫 Enseignant principal (cadre seulement)
        if profile.user_type == "enseignant_cadre" and 'enseignant_principal' in payload:
            principal_id = payload['enseignant_principal']
            if principal_id:
                principal = get_object_or_404(
                    Profile,
                    pk=principal_id,
                    user_type="enseignant_principal"
                )
                cours.enseignant_principal = principal
            else:
                cours.enseignant_principal = None

        # 🏫 Département (cadre seulement)
        if profile.user_type == "enseignant_cadre" and 'departement' in payload:
            dep = get_object_or_404(Departement, pk=payload['departement'])
            cours.departement = dep

        cours.save()
        return Response(CoursSerializer(cours).data, status=status.HTTP_200_OK)


class ModuleListByCoursView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        cours = get_object_or_404(Cours, id=cours_id)

        modules = (
            Module.objects
            .filter(cours=cours)
            .prefetch_related('lecons')
            .order_by('ordre')
        )

        serializer = ModuleAvecLeconsSerializer(modules, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class DepartementNiveauxAPIView(APIView):
    def get(self, request, departement_id):
        niveaux = (
            Cours.objects
            .filter(departement_id=departement_id)
            .values_list("niveau", flat=True)
            .distinct()
        )
        return Response(niveaux)

# ---------------------------
# Lister les cours selon le rôle
# ---------------------------
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def liste_cours(request):
    user = request.user

    if getattr(user, "user_type", None) in ['admin', 'enseignant_admin']:
        qs = Cours.objects.all()
    elif getattr(user, "user_type", None) == 'enseignant_cadre':
        qs = Cours.objects.filter(departement__cadre=user)
    elif getattr(user, "user_type", None) == 'enseignant_principal':
        qs = Cours.objects.filter(enseignant_principal=user)
    elif getattr(user, "user_type", None) == 'enseignant':
        # relation ManyToMany 'cours_secondaires' supposée exister sur le modèle
        qs = user.cours_secondaires.all()
    else:
        return Response({'error': 'Rôle non géré'}, status=status.HTTP_403_FORBIDDEN)

    serializer = CoursSerializer(qs, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

#Lecons
class AjouterLeconView(APIView):
    permission_classes = [IsAuthenticated]
    #parser_classes = [MultiPartParser, FormParser]


    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)

        if cours.enseignant_principal != request.user.profile:
            raise PermissionDenied("Seul l’enseignant principal peut ajouter une leçon.")

        serializer = LeconCreateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(
                cours=cours,
                created_by=request.user.profile
            )
            lecon = serializer.instance
            enregistrer_activite(
       user=request.user,
       action='lesson_created',
       description=f"Leçon « {lecon.titre} » ajoutée au cours « {cours.titre} »",
       data={'lecon': lecon.titre, 'cours': cours.titre},
       objet_id=lecon.id,
       objet_type='Lecon',
   )

            cours.nb_lecons += 1
            cours.save(update_fields=['nb_lecons'])

            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

class LecturesRecentesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            limit = min(int(request.query_params.get('limit', 5)), 10)
        except (TypeError, ValueError):
            limit = 5

        # ── Avec le modèle ProgressionLecon ──────────────────────
        try:
            from .models import ProgressionLecon
            progressions = ProgressionLecon.objects.filter(
                apprenant=request.user,
                terminee=False,   # Seulement les leçons non terminées
            ).select_related(
                'lecon__cours__enseignant_principal__user',
                'lecon__module',
            ).order_by('-derniere_vue')[:limit]

            result = []
            for p in progressions:
                lecon = p.lecon
                cours = lecon.cours
                module_titre = lecon.module.titre if lecon.module else ''

                # Estimer le temps restant (supposons ~5 min par leçon)
                mins_total = 5
                mins_restants = max(1, round(mins_total * (1 - p.pourcentage / 100)))

                result.append({
                    'lecon_id':       lecon.id,
                    'lecon_titre':    lecon.titre,
                    'cours_id':       cours.id,
                    'cours_titre':    cours.titre,
                    'cours_color':    cours.color_code or '#2884A0',
                    'cours_icon':     cours.icon_name or 'school',
                    'module_titre':   module_titre,
                    'pourcentage':    p.pourcentage,
                    'derniere_vue':   p.derniere_vue.isoformat(),
                    'mins_restants':  mins_restants,
                })

            return Response(result, status=status.HTTP_200_OK)

        except Exception:
            # Si ProgressionLecon n'existe pas encore, retourner vide
            return Response([], status=status.HTTP_200_OK)


class MarquerLeconVueView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        lecon_id    = request.data.get('lecon_id')
        pourcentage = request.data.get('pourcentage', 0)

        if not lecon_id:
            return Response(
                {"detail": "lecon_id est requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            pourcentage = max(0, min(100, int(pourcentage)))
        except (TypeError, ValueError):
            pourcentage = 0

        lecon = get_object_or_404(Lecon, pk=lecon_id)

        try:
            from .models import ProgressionLecon
            prog, created = ProgressionLecon.objects.update_or_create(
                apprenant=request.user,
                lecon=lecon,
                defaults={
                    'cours':       lecon.cours,
                    'pourcentage': pourcentage,
                    'terminee':    pourcentage >= 90,
                },
            )

            return Response({
                'lecon_id':    lecon.id,
                'pourcentage': prog.pourcentage,
                'terminee':    prog.terminee,
                'created':     created,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"detail": f"Erreur : {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ModuleCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, id=cours_id)

        # 🔐 Sécurité : seul l’enseignant principal
        if cours.enseignant_principal != request.user.profile:
            raise PermissionDenied(
                "Seul l'enseignant principal peut créer un module."
            )

        serializer = ModuleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        module = serializer.save(cours=cours)
        enregistrer_activite(
       user=request.user,
       action='module_created',
       description=f"Module « {module.titre} » créé dans le cours « {cours.titre} »",
       data={'module': module.titre, 'cours': cours.titre, 'ordre': module.ordre},
       objet_id=module.id,
       objet_type='Module',
   )

        return Response(
            {
                "id": module.id,
                "titre": module.titre,
                "ordre": module.ordre,
                "cours": cours.id
            },
            status=status.HTTP_201_CREATED
        )


class ModuleUpdateView(APIView):
    """
    PATCH /api/modules/<module_id>/modifier/
    Modifie le titre, la description et/ou l'ordre d'un module.
    Réservé à l'enseignant principal du cours lié.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, module_id):
        module = get_object_or_404(Module, pk=module_id)
        cours  = module.cours

        # 🔐 Seul l'enseignant principal peut modifier
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut modifier un module."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ModuleUpdateSerializer(module, data=request.data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            enregistrer_activite(
       user=request.user,
       action='module_modified',
       description=f"Module « {updated.titre} » modifié",
       data={'module': updated.titre, 'cours': updated.cours.titre},
       objet_id=updated.id,
       objet_type='Module',
   )
            return Response(
                ModuleAvecLeconsSerializer(updated, context={"request": request}).data,
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ModuleDeleteView(APIView):
    """
    DELETE /api/modules/<module_id>/supprimer/
    Supprime un module et toutes ses leçons (cascade Django).
    Réservé à l'enseignant principal du cours lié.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def delete(self, request, module_id):
        module = get_object_or_404(Module, pk=module_id)
        cours  = module.cours

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut supprimer un module."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Décrémenter nb_lecons du cours
        nb_lecons_module = module.lecons.count()
        enregistrer_activite(
       user=request.user,
       action='module_deleted',
       description=f"Module « {module.titre} » supprimé du cours « {cours.titre} »",
       data={'module': module.titre, 'cours': cours.titre},
       objet_type='Module',
   )
        module.delete()

        if nb_lecons_module > 0:
            cours.nb_lecons = max(0, cours.nb_lecons - nb_lecons_module)
            cours.save(update_fields=["nb_lecons"])

        return Response(status=status.HTTP_204_NO_CONTENT)


# ═══════════════════════════════════════════════════════════════
#  LEÇON — Modifier et Supprimer
# ═══════════════════════════════════════════════════════════════

class LeconUpdateView(APIView):
    """
    PATCH /api/lecons/<lecon_id>/modifier/
    Modifie une leçon (titre, description, module, fichier_pdf, video).
    Réservé à l'enseignant principal du cours OU au créateur de la leçon.
    Accepte multipart/form-data pour les fichiers.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @transaction.atomic
    def patch(self, request, lecon_id):
        lecon = get_object_or_404(Lecon, pk=lecon_id)
        cours = lecon.cours

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        # 🔐 Enseignant principal OU créateur de la leçon
        if cours.enseignant_principal != profile and lecon.created_by != profile:
            return Response(
                {"detail": "Vous n'avez pas la permission de modifier cette leçon."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = LeconUpdateSerializer(lecon, data=request.data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(
                LeconSerializer(updated, context={"request": request}).data,
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LeconDeleteView(APIView):
    """
    DELETE /api/lecons/<lecon_id>/supprimer/
    Supprime une leçon.
    Réservé à l'enseignant principal du cours OU au créateur.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def delete(self, request, lecon_id):
        lecon = get_object_or_404(Lecon, pk=lecon_id)
        cours = lecon.cours

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile and lecon.created_by != profile:
            return Response(
                {"detail": "Vous n'avez pas la permission de supprimer cette leçon."},
                status=status.HTTP_403_FORBIDDEN,
            )
        enregistrer_activite(
       user=request.user,
       action='lesson_deleted',
       description=f"Leçon « {lecon.titre} » supprimée du cours « {cours.titre} »",
       data={'lecon': lecon.titre, 'cours': cours.titre},
       objet_type='Lecon',
   )
        lecon.delete()

        cours.nb_lecons = max(0, cours.nb_lecons - 1)
        cours.save(update_fields=["nb_lecons"])

        return Response(status=status.HTTP_204_NO_CONTENT)


# views.py - Ajoutez cette classe après les autres vues

class LeconLikeView(APIView):
    """
    POST /api/apprenant/lecon/<lecon_id>/like/
    Gère les likes d'une leçon par un apprenant.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, lecon_id):
        lecon = get_object_or_404(Lecon, pk=lecon_id)
        user = request.user

        # Vérifier que l'utilisateur est un apprenant
        try:
            profile = user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'apprenant':
            return Response({"detail": "Seuls les apprenants peuvent liker des leçons."}, status=403)

        # Récupérer ou créer l'objet like (vous devez créer ce modèle si ce n'est pas fait)
        # Si vous n'avez pas de modèle Like, créez-le :
        # class LeconLike(models.Model):
        #     user = models.ForeignKey(User, on_delete=models.CASCADE)
        #     lecon = models.ForeignKey(Lecon, on_delete=models.CASCADE)
        #     created_at = models.DateTimeField(auto_now_add=True)
        #     
        #     class Meta:
        #         unique_together = ('user', 'lecon')

        try:
            like = LeconLike.objects.get(user=user, lecon=lecon)
            like.delete()
            liked = False
            message = "Like retiré"
        except LeconLike.DoesNotExist:
            LeconLike.objects.create(user=user, lecon=lecon)
            liked = True
            message = "Like ajouté"

        # Récupérer le nombre total de likes
        total_likes = LeconLike.objects.filter(lecon=lecon).count()

        return Response({
            "liked": liked,
            "total_likes": total_likes,
            "message": message
        }, status=status.HTTP_200_OK)

    def get(self, request, lecon_id):
        """Vérifie si l'utilisateur a liké la leçon"""
        lecon = get_object_or_404(Lecon, pk=lecon_id)
        user = request.user

        liked = LeconLike.objects.filter(user=user, lecon=lecon).exists()
        total_likes = LeconLike.objects.filter(lecon=lecon).count()

        return Response({
            "liked": liked,
            "total_likes": total_likes
        }, status=status.HTTP_200_OK)


class ListeExercicesCoursView(APIView):
    """
    GET /api/cours/<cours_id>/exercices/
    Paramètres optionnels :
    - module_id: filtrer par module
    - lecon_id: filtrer par leçon
    - type: general, module, lecon, epreuve
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        
        # Base queryset
        exercices = Exercice.objects.filter(cours=cours)
        
        # Filtres
        module_id = request.query_params.get('module_id')
        if module_id:
            exercices = exercices.filter(module_id=module_id)
        
        lecon_id = request.query_params.get('lecon_id')
        if lecon_id:
            exercices = exercices.filter(lecon_id=lecon_id)
        
        type_exercice = request.query_params.get('type')
        if type_exercice:
            exercices = exercices.filter(type_exercice=type_exercice)
        else:
            # Par défaut, afficher tous les types sauf les épreuves (sauf si demandé)
            if request.query_params.get('include_epreuves') != 'true':
                exercices = exercices.exclude(est_epreuve=True)
        
        # CORRECTION : Ne pas annoter avec nb_questions, le serializer le calcule
        exercices = exercices.order_by('-id')
        
        serializer = ExerciceSerializer(exercices, many=True, context={'request': request})
        return Response(serializer.data)


class AjouterExerciceView(APIView):
    """
    POST /api/cours/<cours_id>/exercices/ajouter/
    Body: { "titre": "...", "enonce": "...", "etoiles": 3, ... }
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut ajouter un exercice."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Copier les données pour les modifier
        data = request.data.copy()
        
        # Gérer l'énoncé image
        if 'enonce_image' in request.FILES:
            data['enonce_image'] = request.FILES['enonce_image']
        
        serializer = ExerciceCreateSerializer(data=data)
        if serializer.is_valid():
            exercice = serializer.save(cours=cours)
            
            # Enregistrer dans l'historique
            enregistrer_activite(
                user=request.user,
                action='exercise_created',
                description=f"Exercice « {exercice.titre} » ajouté au cours « {cours.titre} »",
                data={
                    'exercice': exercice.titre,
                    'cours': cours.titre,
                    'etoiles': exercice.etoiles,
                    'type': exercice.type_exercice,
                },
                objet_id=exercice.id,
                objet_type='Exercice',
            )
            
            cours.nb_devoirs += 1
            cours.save(update_fields=['nb_devoirs'])
            
            # Retourner l'exercice créé avec ses données enrichies
            return Response(
                ExerciceSerializer(exercice, context={'request': request}).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ModifierExerciceView(APIView):
    """
    PATCH /api/exercices/<exercice_id>/modifier/
    Modifie un exercice existant.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @transaction.atomic
    def patch(self, request, exercice_id):
        exercice = get_object_or_404(Exercice, pk=exercice_id)
        cours = exercice.cours

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut modifier un exercice."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Copier les données
        data = request.data.copy()
        
        # Gérer l'énoncé image
        if 'enonce_image' in request.FILES:
            data['enonce_image'] = request.FILES['enonce_image']
        
        # Si enonce_image est null, supprimer l'image existante
        if data.get('enonce_image') == 'null':
            data['enonce_image'] = None

        serializer = ExerciceCreateSerializer(exercice, data=data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            
            enregistrer_activite(
                user=request.user,
                action='exercise_modified',
                description=f"Exercice « {updated.titre} » modifié",
                data={
                    'exercice': updated.titre,
                    'cours': cours.titre,
                },
                objet_id=updated.id,
                objet_type='Exercice',
            )
            
            return Response(
                ExerciceSerializer(updated, context={'request': request}).data,
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SupprimerExerciceView(APIView):
    """
    DELETE /api/exercices/<exercice_id>/supprimer/
    Supprime un exercice.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def delete(self, request, exercice_id):
        exercice = get_object_or_404(Exercice, pk=exercice_id)
        cours = exercice.cours

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut supprimer un exercice."},
                status=status.HTTP_403_FORBIDDEN,
            )

        enregistrer_activite(
            user=request.user,
            action='exercise_deleted',
            description=f"Exercice « {exercice.titre} » supprimé du cours « {cours.titre} »",
            data={
                'exercice': exercice.titre,
                'cours': cours.titre,
            },
            objet_type='Exercice',
        )
        
        exercice.delete()
        
        # Mettre à jour le compteur
        cours.nb_devoirs = max(0, cours.nb_devoirs - 1)
        cours.save(update_fields=['nb_devoirs'])

        return Response(status=status.HTTP_204_NO_CONTENT)


class SoumettreEvaluationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, exercice_id):
        user = request.user
        exercice = get_object_or_404(Exercice, id=exercice_id)

        # Récupérer la session en cours
        session = SessionExercice.objects.filter(
            user=user,
            exercice=exercice,
            termine=False
        ).first()

        # Si pas de session, en créer une
        if not session:
            # Vérifier les tentatives
            tentatives = EvaluationExercice.objects.filter(
                user=user, exercice=exercice
            ).count()
            
            if tentatives >= exercice.tentatives_max:
                return Response(
                    {"detail": f"Nombre maximum de tentatives atteint ({exercice.tentatives_max})."},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            session = SessionExercice.objects.create(
                user=user,
                exercice=exercice
            )

        # Vérifier si le temps est écoulé
        temps_restant = session.temps_restant()
        if temps_restant <= 0:
            session.termine = True
            session.save()
            return Response(
                {"detail": "Temps écoulé. Examen terminé.", "auto_soumis": True},
                status=status.HTTP_200_OK
            )

        # Récupérer les réponses
        reponses = request.data.get("reponses", {})
        
        # Calculer le score
        score = 0
        total = 0
        details = []

        for question in exercice.questions.all():
            points = question.points
            total += points
            
            # Récupérer la réponse de l'utilisateur
            user_rep = reponses.get(str(question.id), "").strip().lower()
            bonne_rep = question.bonne_reponse.strip().lower()
            
            is_correct = (user_rep == bonne_rep)
            
            if is_correct:
                score += points
            
            details.append({
                "question_id": question.id,
                "question": question.text,
                "reponse_utilisateur": user_rep,
                "bonne_reponse": question.bonne_reponse,
                "correct": is_correct,
                "points_obtenus": points if is_correct else 0,
                "points_max": points
            })

        # Sauvegarder l'évaluation
        evaluation = EvaluationExercice.objects.create(
            user=user,
            exercice=exercice,
            score=score,
            total=total
        )

        # Marquer la session comme terminée
        session.termine = True
        session.save()

        # Calculer la note sur 20
        note_sur_20 = (score / total) * 20 if total > 0 else 0

        return Response({
            "score": score,
            "total": total,
            "note": round(note_sur_20, 1),
            "note_sur": 20,
            "detail": details,
            "message": "Examen soumis avec succès",
            "auto_soumis": False
        }, status=status.HTTP_200_OK)


class ResultatExerciceView(APIView):
    """
    GET /api/evaluations/exercice/<exercice_id>/
    Retourne le dernier résultat de l'utilisateur pour un exercice donné.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, exercice_id):
        exercice = get_object_or_404(Exercice, id=exercice_id)
        user = request.user

        # Récupérer la dernière évaluation
        evaluation = EvaluationExercice.objects.filter(
            user=user,
            exercice=exercice
        ).order_by('-date').first()

        if not evaluation:
            return Response(
                {"detail": "Aucun résultat trouvé pour cet exercice."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Récupérer les détails des questions
        details = []
        for question in exercice.questions.all():
            # Pour récupérer la réponse de l'utilisateur, il faudrait stocker les réponses
            # Dans une table séparée. Pour l'instant, on retourne juste le score par question
            details.append({
                "question_id": question.id,
                "question": question.text,
                "points_max": question.points,
                "bonne_reponse": question.bonne_reponse
            })

        return Response({
            "exercice_id": exercice.id,
            "exercice_titre": exercice.titre,
            "note": evaluation.score,
            "note_sur": evaluation.total,
            "score": evaluation.score,
            "total": evaluation.total,
            "date": evaluation.date,
            "detail": details
        }, status=status.HTTP_200_OK)


class HistoriqueEvaluationsView(APIView):
    #permission_classes = [IsAuthenticated]

    def get(self, request):
        evaluations = EvaluationExercice.objects.filter(user=request.user).order_by("-date")
        serializer = EvaluationSerializer(evaluations, many=True)
        return Response(serializer.data)


class DemarrerExerciceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, exercice_id):
        user = request.user
        exercice = get_object_or_404(Exercice, id=exercice_id)

        # Vérifier les tentatives déjà faites
        tentatives = EvaluationExercice.objects.filter(
            user=user, exercice=exercice
        ).count()
        
        if tentatives >= exercice.tentatives_max:
            return Response(
                {
                    "detail": f"Nombre maximum de tentatives atteint ({exercice.tentatives_max}).",
                    "tentatives_restantes": 0
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # Vérifier si une session non terminée existe déjà
        session = SessionExercice.objects.filter(
            user=user, 
            exercice=exercice, 
            termine=False
        ).first()

        if session:
            # Si la session existe mais que le temps est écoulé
            if session.temps_restant() <= 0:
                session.termine = True
                session.save()
                session = None

        # Créer une nouvelle session si nécessaire
        if not session:
            session = SessionExercice.objects.create(
                user=user,
                exercice=exercice
            )

        duree_totale = exercice.duree_minutes * 60
        temps_restant = session.temps_restant()

        return Response({
            "session_id": session.id,
            "debut": session.debut.isoformat(),
            "duree_totale": duree_totale,
            "temps_restant": temps_restant,
            "tentatives_restantes": exercice.tentatives_max - tentatives
        }, status=status.HTTP_200_OK)


class ExerciceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, exercice_id):
        user = request.user
        exercice = get_object_or_404(
            Exercice.objects.prefetch_related("questions__choix"),
            id=exercice_id
        )

        # Vérifier si une session est en cours
        session = SessionExercice.objects.filter(
            user=user,
            exercice=exercice,
            termine=False
        ).first()

        # Calculer le temps restant
        duree_totale = exercice.duree_minutes * 60
        temps_restant = duree_totale
        
        if session:
            temps_restant = session.temps_restant()
            # Si le temps est écoulé, marquer la session comme terminée
            if temps_restant <= 0:
                session.termine = True
                session.save()
                temps_restant = 0

        # Compter les tentatives déjà faites
        tentatives = EvaluationExercice.objects.filter(
            user=user, exercice=exercice
        ).count()
        
        tentatives_restantes = max(0, exercice.tentatives_max - tentatives)

        # Sérialiser les questions
        questions_data = []
        for q in exercice.questions.all():
            q_data = {
                "id": q.id,
                "text": q.text,
                "type": q.type_question,
                "points": q.points,
                "bonne_reponse": q.bonne_reponse,  # À ne pas exposer en prod
                "choix": [c.texte for c in q.choix.all()] if q.type_question == "qcm" else []
            }
            questions_data.append(q_data)

        return Response({
            "id": exercice.id,
            "titre": exercice.titre,
            "enonce": exercice.enonce,
            "etoiles": exercice.etoiles,
            "duree_minutes": exercice.duree_minutes,
            "duree_totale": duree_totale,
            "temps_restant": temps_restant,
            "tentatives_max": exercice.tentatives_max,
            "tentatives_restantes": tentatives_restantes,
            "questions": questions_data
        }, status=status.HTTP_200_OK)


class AjouterQuestionView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request, exercice_id):
        exercice = get_object_or_404(Exercice, pk=exercice_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if exercice.cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut ajouter des questions."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = QuestionCreateSerializer(data=request.data)
        if serializer.is_valid():
            question = serializer.save(exercice=exercice)
            return Response(
                QuestionSerializer(question).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ListeQuestionsExerciceView(APIView):
    """
    GET /api/exercices/<exercice_id>/questions/
    Retourne toutes les questions d'un exercice avec leurs choix.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, exercice_id):
        exercice  = get_object_or_404(Exercice, pk=exercice_id)
        questions = Question.objects.filter(
            exercice=exercice
        ).prefetch_related('choix')
        return Response(
            QuestionSerializer(questions, many=True).data
        )
    

# ─────────────────────────────────────────────────────
# ENDPOINT 1 : GET /api/profil/me/
# Retourne le profil complet de l'utilisateur connecté
# ─────────────────────────────────────────────────────
class ProfilMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        serializer = ProfilDetailSerializer(profile, context={"request": request})
        return Response(serializer.data, status=200)


# ─────────────────────────────────────────────────────
# ENDPOINT 2 : PATCH /api/profil/update/
# Modifier les infos du profil (y compris avatar en multipart)
# ─────────────────────────────────────────────────────
class ProfilUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def patch(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        data = request.data

        # Champs User Django
        user = request.user
        if "first_name" in data:
            user.first_name = data["first_name"]
        if "last_name" in data:
            user.last_name = data["last_name"]
        if "email" in data:
            user.email = data["email"]
        user.save()

        # Champs Profile
        for field in ["phone", "bio", "cursus", "sub_cursus", "niveau", "filiere", "licence"]:
            if field in data:
                setattr(profile, field, data[field])

        # Avatar (fichier image)
        if "avatar" in request.FILES:
            profile.avatar = request.FILES["avatar"]

        profile.save()

        serializer = ProfilDetailSerializer(profile, context={"request": request})
        return Response(serializer.data, status=200)


# ─────────────────────────────────────────────────────
# ENDPOINT 3 : DELETE /api/profil/delete/
# Supprimer définitivement le compte
# ─────────────────────────────────────────────────────
class ProfilDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user
        try:
            user.auth_token.delete()
        except Exception:
            pass
        user.delete()
        return Response({"detail": "Compte supprimé avec succès."}, status=200)


# ─────────────────────────────────────────────────────
# ENDPOINT 4 : GET /api/profil/stats/
# Stats personnalisées selon le rôle
# ─────────────────────────────────────────────────────
class ProfilStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        role = profile.user_type
        stats = {}

        if role == "apprenant":
            # Nombre de cours disponibles dans son cursus
            nb_cours = Cours.objects.filter(
                departement__parcours__nom=profile.cursus
            ).count() if profile.cursus else 0
            # Devoirs : tous les devoirs (on peut filtrer plus tard)
            nb_devoirs = SoumissionDevoir.objects.filter(
                utilisateur=request.user
            ).count()
            # Évaluations : score moyen
            evals = EvaluationExercice.objects.filter(user=request.user)
            if evals.exists():
                moyenne = sum(
                    (e.score / e.total * 20) for e in evals if e.total > 0
                ) / evals.count()
            else:
                moyenne = 0.0
            stats = {
                "nb_cours": nb_cours,
                "nb_devoirs": nb_devoirs,
                "moyenne": round(moyenne, 1),
            }

        elif role in ["enseignant_principal", "enseignant"]:
            if role == "enseignant_principal":
                nb_cours = Cours.objects.filter(enseignant_principal=profile).count()
            else:
                nb_cours = profile.cours_secondaires.count()
            nb_lecons = Lecon.objects.filter(created_by=profile).count()
            stats = {
                "nb_cours": nb_cours,
                "nb_lecons": nb_lecons,
                "nb_devoirs": 0,
            }

        elif role == "enseignant_cadre":
            nb_departements = Departement.objects.filter(cadre=profile).count()
            nb_cours = Cours.objects.filter(departement__cadre=profile).count()
            stats = {
                "nb_departements": nb_departements,
                "nb_cours": nb_cours,
                "nb_devoirs": 0,
            }

        else:
            stats = {"nb_cours": 0, "nb_devoirs": 0, "moyenne": 0.0}

        return Response(stats, status=200)


# ─────────────────────────────────────────────────────
# ENDPOINT 5 : POST /api/auth/change-password/
# Changer le mot de passe (ancien + nouveau requis)
# ─────────────────────────────────────────────────────
class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        old_password = request.data.get("old_password", "")
        new_password = request.data.get("new_password", "")

        if not old_password or not new_password:
            return Response(
                {"detail": "Les deux champs sont requis."},
                status=400
            )

        if not check_password(old_password, user.password):
            return Response(
                {"detail": "Ancien mot de passe incorrect."},
                status=400
            )

        if len(new_password) < 8:
            return Response(
                {"detail": "Le nouveau mot de passe doit contenir au moins 8 caractères."},
                status=400
            )

        user.set_password(new_password)
        user.save()

        # Renouveler le token après changement de mdp
        try:
            user.auth_token.delete()
        except Exception:
            pass
        token, _ = Token.objects.get_or_create(user=user)

        return Response(
            {"detail": "Mot de passe modifié avec succès.", "token": token.key},
            status=200
        )

    
# ============================================================
#  views_devoirs.py
# ============================================================
class DevoirsCoursView(APIView):
    """
    GET /api/cours/<cours_id>/devoirs/
    Retourne les devoirs liés à un cours spécifique.
    Inclut la soumission de l'utilisateur connecté.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        # Import ici pour éviter les imports circulaires
        from .models import Devoir, SoumissionDevoir

        # Devoirs liés à ce cours via le bon champ FK cours_lie
        devoirs = Devoir.objects.filter(
            cours_lie_id=cours_id,
            est_publie=True,
        ).order_by('date_limite')

        result = []
        for devoir in devoirs:
            # Chercher la soumission de l'utilisateur
            soumission = SoumissionDevoir.objects.filter(
                devoir=devoir,
                utilisateur=request.user,
            ).first()

            soumission_data = None
            if soumission:
                soumission_data = {
                    'id':     soumission.id,
                    'statut': soumission.statut,
                    'note':   float(soumission.note) if soumission.note is not None else None,
                    'soumis_le': soumission.soumis_le.isoformat() if soumission.soumis_le else None,
                }

            result.append({
                'id':           devoir.id,
                'titre':        devoir.titre,
                'description':  devoir.description,
                'date_debut':   devoir.date_debut.isoformat() if devoir.date_debut else None,
                'date_limite':  devoir.date_limite.isoformat() if devoir.date_limite else None,
                'est_ouvert':   devoir.est_ouvert,
                'est_expire':   devoir.est_expire,
                'nb_questions': devoir.questions.count(),
                'note_sur':     float(devoir.note_sur) if hasattr(devoir, 'note_sur') else 20,
                'ma_soumission': soumission_data,
            })

        return Response(result)

# ═══════════════════════════════════════════════════════════════
#  DEVOIRS GÉNÉRAUX
# ═══════════════════════════════════════════════════════════════

class ListeDevoirsView(APIView):
    """
    GET /api/devoirs/
    Paramètres query optionnels :
      - type_devoir   : cursus | concours | formation_classique | formation_metier | olympiade
      - matiere       : Mathématiques | Physique | …
      - niveau        : Terminale | Licence 1 | …
      - statut        : non_commence | en_cours | soumis | corrige
      - cours_id      : filtrer par cours lié
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Devoir.objects.filter(est_publie=True).order_by("-date_limite")

        # ── Filtres ──────────────────────────────────────────────
        type_devoir = request.query_params.get("type_devoir")
        matiere     = request.query_params.get("matiere")
        niveau      = request.query_params.get("niveau")
        statut_filtre = request.query_params.get("statut")
        cours_id    = request.query_params.get("cours_id")

        if type_devoir:
            qs = qs.filter(type_devoir=type_devoir)
        if matiere:
            qs = qs.filter(matiere=matiere)
        if niveau:
            qs = qs.filter(niveau=niveau)
        if cours_id:
            qs = qs.filter(cours_lie_id=cours_id)

        # Filtre par statut apprenant (post-queryset)
        if statut_filtre:
            soumissions = SoumissionDevoir.objects.filter(
                utilisateur=request.user
            ).values_list("devoir_id", "statut")
            soum_map = {d_id: s for d_id, s in soumissions}

            if statut_filtre == "non_commence":
                ids_soumis = set(soum_map.keys())
                qs = qs.exclude(id__in=ids_soumis)
            else:
                ids = [d_id for d_id, s in soum_map.items() if s == statut_filtre]
                qs = qs.filter(id__in=ids)

        serializer = DevoirListSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)


class DetailDevoirView(APIView):
    """GET /api/devoirs/<id>/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id, est_publie=True)

        # Vérifier que le devoir est ouvert (ou déjà commencé par l'apprenant)
        soum = SoumissionDevoir.objects.filter(
            utilisateur=request.user, devoir=devoir
        ).first()

        if not devoir.est_ouvert and not soum:
            return Response(
                {"detail": "Ce devoir n'est pas encore accessible."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = DevoirDetailSerializer(devoir, context={"request": request})
        return Response(serializer.data)


class DemarrerDevoirView(APIView):
    """POST /api/devoirs/<id>/demarrer/"""
    permission_classes = [IsAuthenticated]

    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id, est_publie=True)

        if not devoir.est_ouvert:
            return Response(
                {"detail": "Le devoir n'est plus accessible."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Vérifier tentatives
        nb_tentatives = SoumissionDevoir.objects.filter(
            utilisateur=request.user,
            devoir=devoir,
            statut__in=["soumis", "corrige", "en_retard"]
        ).count()

        if nb_tentatives >= devoir.tentatives_max:
            return Response(
                {"detail": f"Nombre maximum de tentatives atteint ({devoir.tentatives_max})."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Créer ou récupérer la soumission
        soum, created = SoumissionDevoir.objects.get_or_create(
            utilisateur=request.user,
            devoir=devoir,
            defaults={
                "statut": "en_cours",
                "ip_address": self._get_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:500],
            }
        )

        if not created and soum.statut in ["soumis", "corrige"]:
            return Response(
                {"detail": "Vous avez déjà soumis ce devoir."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = SoumissionDetailSerializer(soum, context={"request": request})
        return Response({
            "soumission": serializer.data,
            "temps_restant_secondes": soum.temps_restant_secondes(),
        })

    def _get_ip(self, request):
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded:
            return x_forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


class SoumettreDevoirView(APIView):
    """POST /api/devoirs/<id>/soumettre/"""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)
        soum = get_object_or_404(
            SoumissionDevoir, devoir=devoir,
            utilisateur=request.user
        )

        if soum.statut in ["soumis", "corrige"]:
            return Response(
                {"detail": "Devoir déjà soumis."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Vérifier chrono
        if soum.temps_restant_secondes() <= 0:
            soum.statut = "soumis"
            soum.soumis_le = timezone.now()
            soum.save()
            return Response({"detail": "Temps écoulé. Devoir auto-soumis."})

        serializer_in = ReponseSubmitSerializer(data=request.data)
        serializer_in.is_valid(raise_exception=True)
        reponses = serializer_in.validated_data["reponses"]

        # ── Enregistrer les réponses & corriger les QCM ──────────
        score = 0.0
        total = 0.0
        has_texte = False

        for question in devoir.questions.prefetch_related("choix").all():
            total += question.points
            user_rep = reponses.get(str(question.id), "").strip()

            repobj, _ = ReponseDevoir.objects.get_or_create(
                soumission=soum, question=question
            )

            if question.type_question == "qcm":
                choix_correct = question.choix.filter(est_correct=True).first()
                choix_selectionne = question.choix.filter(texte=user_rep).first()
                repobj.reponse    = user_rep
                repobj.choix      = choix_selectionne
                if choix_selectionne and choix_selectionne.est_correct:
                    repobj.est_correct     = True
                    repobj.points_obtenus  = question.points
                    score += question.points
                else:
                    repobj.est_correct    = False
                    repobj.points_obtenus = 0
            else:
                repobj.reponse   = user_rep
                repobj.est_correct = None   # correction manuelle
                has_texte = True

            repobj.save()

        # ── Mise à jour soumission ────────────────────────────────
        now = timezone.now()
        soum.soumis_le = now
        soum.statut    = "en_retard" if soum.est_en_retard else "soumis"

        if not has_texte:
            # 100% QCM → correction auto
            note = round((score / total) * devoir.note_sur, 2) if total > 0 else 0
            soum.note    = note
            soum.statut  = "corrige"
            soum.corrige_le = now

        soum.save()

        return Response({
            "statut":     soum.statut,
            "note":       soum.note,
            "note_sur":   devoir.note_sur,
            "en_retard":  soum.est_en_retard,
            "message":    "Devoir soumis avec succès.",
        })


class SignalerFocusDevoirView(APIView):
    """
    POST /api/devoirs/<id>/focus-perdu/
    Appelé par Flutter quand l'apprenant quitte l'app pendant la composition.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, devoir_id):
        soum = get_object_or_404(
            SoumissionDevoir,
            devoir_id=devoir_id,
            utilisateur=request.user,
            statut="en_cours"
        )
        soum.nb_focus_perdu += 1

        # Marquer suspect si trop de sorties
        if soum.nb_focus_perdu >= 5:
            soum.est_suspecte = True

        soum.save(update_fields=["nb_focus_perdu", "est_suspecte"])
        return Response({"nb_focus_perdu": soum.nb_focus_perdu})


class MesSoumissionsView(APIView):
    """GET /api/devoirs/mes-soumissions/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        soumissions = SoumissionDevoir.objects.filter(
            utilisateur=request.user
        ).select_related("devoir").order_by("-debut")

        serializer = SoumissionDetailSerializer(
            soumissions, many=True, context={"request": request}
        )
        return Response(serializer.data)


class ResultatDevoirView(APIView):
    """GET /api/devoirs/<id>/resultat/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, devoir_id):
        soum = get_object_or_404(
            SoumissionDevoir,
            devoir_id=devoir_id,
            utilisateur=request.user
        )
        # "corrige"   → correction auto (QCM) ou manuelle faite
        # "en_retard" → soumis hors délai, peut être auto-corrigé (QCM)
        # "soumis"    → en attente de correction manuelle
        if soum.statut == "en_cours":
            return Response(
                {"detail": "Devoir encore en cours de composition."},
                status=status.HTTP_404_NOT_FOUND
            )
        if soum.statut == "soumis":
            return Response(
                {"detail": "Résultat en attente de correction par l'enseignant."},
                status=status.HTTP_202_ACCEPTED
            )
        if soum.statut not in ["corrige", "en_retard"]:
            return Response(
                {"detail": "Résultat pas encore disponible."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Construire le détail par question
        detail = []
        for rep in soum.reponses.select_related("question", "choix").all():
            detail.append({
                "question":       rep.question.texte,
                "reponse":        rep.reponse,
                "est_correct":    rep.est_correct,
                "points_obtenus": rep.points_obtenus,
                "points_max":     rep.question.points,
            })

        return Response({
            "devoir":      soum.devoir.titre,
            "note":        soum.note,
            "note_sur":    soum.devoir.note_sur,
            "commentaire": soum.commentaire,
            "soumis_le":   soum.soumis_le,
            "corrige_le":  soum.corrige_le,
            "en_retard":   soum.est_en_retard,
            "detail":      detail,
        })

# ─────────────────────────────────────────────────────────────────────────────
# 1. CRÉER UN DEVOIR LIÉ À UN COURS
#    POST /api/cours/<cours_id>/devoirs/creer/
# ─────────────────────────────────────────────────────────────────────────────

class DevoirsCoursView(APIView):
    """
    GET /api/cours/<cours_id>/devoirs/
    Retourne les devoirs liés à un cours spécifique avec le statut de l'apprenant.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        
        # Récupérer tous les devoirs du cours, publiés ou non selon le rôle
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        # Vérifier si l'utilisateur est enseignant principal du cours
        is_enseignant = (profile.user_type in ['enseignant_principal', 'enseignant_cadre', 'enseignant_admin', 'admin'] and 
                         (cours.enseignant_principal == profile or 
                          profile.user_type in ['enseignant_cadre', 'enseignant_admin', 'admin']))

        # Base queryset
        if is_enseignant:
            # Enseignant: voir tous les devoirs (publiés ou non)
            devoirs = Devoir.objects.filter(cours_lie=cours).order_by('-date_creation')
        else:
            # Apprenant: voir seulement les devoirs publiés
            devoirs = Devoir.objects.filter(cours_lie=cours, est_publie=True).order_by('-date_creation')

        result = []
        for devoir in devoirs:
            # Chercher la soumission de l'utilisateur
            soumission = SoumissionDevoir.objects.filter(
                devoir=devoir,
                utilisateur=request.user,
            ).first()

            soumission_data = None
            if soumission:
                soumission_data = {
                    'id': soumission.id,
                    'statut': soumission.statut,
                    'note': float(soumission.note) if soumission.note is not None else None,
                    'soumis_le': soumission.soumis_le.isoformat() if soumission.soumis_le else None,
                    'est_corrige': soumission.statut == 'corrige',
                    'commentaire': soumission.commentaire or '',
                }

            # Pour l'enseignant: compter le nombre de soumissions
            stats = None
            if is_enseignant:
                nb_soumissions = SoumissionDevoir.objects.filter(devoir=devoir).count()
                nb_corriges = SoumissionDevoir.objects.filter(devoir=devoir, statut='corrige').count()
                
                # Moyenne des notes
                notes = SoumissionDevoir.objects.filter(
                    devoir=devoir, 
                    note__isnull=False
                ).values_list('note', flat=True)
                moyenne = sum(notes) / len(notes) if notes else 0.0

                stats = {
                    'nb_soumissions': nb_soumissions,
                    'nb_corriges': nb_corriges,
                    'moyenne': round(moyenne, 2),
                }

            result.append({
                'id': devoir.id,
                'titre': devoir.titre,
                'description': devoir.description,
                'date_debut': devoir.date_debut.isoformat() if devoir.date_debut else None,
                'date_limite': devoir.date_limite.isoformat() if devoir.date_limite else None,
                'est_ouvert': devoir.est_ouvert,
                'est_expire': devoir.est_expire,
                'nb_questions': devoir.questions.count(),
                'note_sur': float(devoir.note_sur),
                'duree_minutes': devoir.duree_minutes,
                'tentatives_max': devoir.tentatives_max,
                'est_publie': devoir.est_publie,
                'type_correction': getattr(devoir, 'type_correction', 'auto'),
                'ma_soumission': soumission_data,
                'stats': stats,
            })

        return Response(result)


# serializers.py - Améliorer ReponseSerializer

class ReponseSerializer(serializers.ModelSerializer):
    auteur_nom = serializers.SerializerMethodField()
    auteur_username = serializers.CharField(source="auteur.username", read_only=True)
    auteur_est_enseignant = serializers.SerializerMethodField()
    nb_likes = serializers.SerializerMethodField()
    mon_like = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = ReponseQuestion
        fields = [
            "id", "contenu", "cree_le", "est_solution",
            "auteur_nom", "auteur_username", "auteur_est_enseignant",
            "nb_likes", "mon_like", "image_url", "audio_url"
        ]

    def get_auteur_nom(self, obj):
        user = obj.auteur
        nom = f"{user.first_name} {user.last_name}".strip()
        return nom if nom else user.username

    def get_auteur_est_enseignant(self, obj):
        try:
            profile = obj.auteur.profile
            return profile.user_type in ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']
        except:
            return False

    def get_nb_likes(self, obj):
        return obj.likes.count()

    def get_mon_like(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(utilisateur=request.user).exists()
        return False

    def get_image_url(self, obj):
        # Si la réponse a une image (modèle à étendre si nécessaire)
        return None

    def get_audio_url(self, obj):
        # Si la réponse a un audio (modèle à étendre si nécessaire)
        return None


class QuestionForumDetailSerializer(serializers.ModelSerializer):
    auteur_nom = serializers.SerializerMethodField()
    auteur_username = serializers.CharField(source="auteur.username", read_only=True)
    auteur_est_enseignant = serializers.SerializerMethodField()
    nb_reponses = serializers.IntegerField(read_only=True)
    reponses = ReponseSerializer(many=True, read_only=True)
    image_url = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = QuestionForum
        fields = [
            "id", "contenu", "source", "cree_le", "est_resolue", "nb_vues",
            "nb_reponses", "reponses",
            "lecon_id", "lecon_titre", "cours_id", "cours_titre",
            "exercice_id", "exercice_titre",
            "devoir_id", "devoir_titre",
            "auteur_nom", "auteur_username", "auteur_est_enseignant",
            "image_url", "audio_url",
        ]

    def get_auteur_nom(self, obj):
        user = obj.auteur
        nom = f"{user.first_name} {user.last_name}".strip()
        return nom if nom else user.username

    def get_auteur_est_enseignant(self, obj):
        try:
            profile = obj.auteur.profile
            return profile.user_type in ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']
        except:
            return False

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

    def get_audio_url(self, obj):
        if obj.audio:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.audio.url)
            return obj.audio.url
        return None


class CreerDevoirCoursView(APIView):
    """
    POST /api/cours/<cours_id>/devoirs/creer/
    Permet à l'enseignant principal de créer un devoir pour son cours.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        # Vérifier que l'utilisateur est l'enseignant principal du cours
        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut créer un devoir pour ce cours."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy()
        data['cours_lie'] = cours.id
        
        # Définir les valeurs par défaut si non fournies
        if 'type_devoir' not in data:
            data['type_devoir'] = 'cursus'
        if 'est_publie' not in data:
            data['est_publie'] = False
        if 'date_debut' not in data:
            data['date_debut'] = timezone.now().isoformat()
        if 'date_limite' not in data:
            # Par défaut, 7 jours à partir de maintenant
            data['date_limite'] = (timezone.now() + timedelta(days=7)).isoformat()
        if 'duree_minutes' not in data:
            data['duree_minutes'] = 60
        if 'note_sur' not in data:
            data['note_sur'] = 20
        if 'tentatives_max' not in data:
            data['tentatives_max'] = 1
        if 'coefficient' not in data:
            data['coefficient'] = 1.0
        if 'type_correction' not in data:
            data['type_correction'] = 'auto'

        serializer = DevoirCreateSerializer(data=data)
        if serializer.is_valid():
            devoir = serializer.save(cree_par=profile)
            
            # Stocker type_correction (si champ existe dans le modèle)
            type_correction = data.get('type_correction', 'auto')
            if hasattr(devoir, 'type_correction'):
                devoir.type_correction = type_correction
                devoir.save(update_fields=['type_correction'])

            # MAJ compteur
            cours.nb_devoirs = Devoir.objects.filter(
                cours_lie=cours, est_publie=True
            ).count()
            cours.save(update_fields=['nb_devoirs'])

            enregistrer_activite(
                user=request.user,
                action='homework_created',
                description=f"Devoir « {devoir.titre} » créé pour le cours « {cours.titre} »",
                data={
                    'devoir': devoir.titre,
                    'cours': cours.titre,
                    'date_limite': devoir.date_limite.strftime('%d/%m/%Y') if devoir.date_limite else '',
                },
                objet_id=devoir.id,
                objet_type='Devoir',
            )

            return Response({
                'id': devoir.id,
                'titre': devoir.titre,
                'description': devoir.description,
                'date_debut': devoir.date_debut.isoformat() if devoir.date_debut else None,
                'date_limite': devoir.date_limite.isoformat() if devoir.date_limite else None,
                'est_publie': devoir.est_publie,
                'nb_questions': devoir.questions.count(),
                'note_sur': float(devoir.note_sur),
                'duree_minutes': devoir.duree_minutes,
                'tentatives_max': devoir.tentatives_max,
                'type_correction': getattr(devoir, 'type_correction', 'auto'),
                'detail': 'Devoir créé avec succès.',
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ModifierDevoirView(APIView):
    """
    PATCH /api/devoirs/<devoir_id>/modifier/
    Permet à l'enseignant principal de modifier un devoir.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        cours = devoir.cours_lie
        if cours is None or cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal du cours peut modifier ce devoir."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy()
        type_correction = data.pop('type_correction', None)

        # Champs modifiables
        updatable_fields = [
            'titre', 'description', 'type_devoir', 'matiere', 'niveau',
            'enonce', 'date_debut', 'date_limite', 'duree_minutes',
            'note_sur', 'coefficient', 'tentatives_max', 'est_publie',
            'acces_restreint', 'concours_lie', 'formation_liee'
        ]
        
        updates = {}
        for field in updatable_fields:
            if field in data:
                updates[field] = data[field]

        if not updates and type_correction is None:
            return Response(
                {"detail": "Aucune modification spécifiée."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Appliquer les modifications
        for key, value in updates.items():
            setattr(devoir, key, value)
        
        if type_correction and hasattr(devoir, 'type_correction'):
            devoir.type_correction = type_correction
        
        devoir.save()

        enregistrer_activite(
            user=request.user,
            action='homework_modified',
            description=f"Devoir « {devoir.titre} » modifié",
            data={
                'devoir': devoir.titre,
                'cours': cours.titre,
                'modifications': list(updates.keys()),
            },
            objet_id=devoir.id,
            objet_type='Devoir',
        )

        return Response({
            'id': devoir.id,
            'titre': devoir.titre,
            'description': devoir.description,
            'date_debut': devoir.date_debut.isoformat() if devoir.date_debut else None,
            'date_limite': devoir.date_limite.isoformat() if devoir.date_limite else None,
            'est_publie': devoir.est_publie,
            'nb_questions': devoir.questions.count(),
            'note_sur': float(devoir.note_sur),
            'detail': 'Devoir modifié avec succès.',
        }, status=status.HTTP_200_OK)

# a verifier
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def enseignant_principal_cours(request):
    """
    GET /api/enseignant_principal/cours/
    Retourne la liste des cours de l'enseignant principal connecté.
    """
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        return Response({"detail": "Profil introuvable."}, status=404)

    if profile.user_type != 'enseignant_principal':
        return Response(
            {"detail": "Accès réservé aux enseignants principaux."},
            status=status.HTTP_403_FORBIDDEN
        )

    cours = Cours.objects.filter(
        enseignant_principal=profile
    ).select_related(
        'departement',
        'enseignant_principal__user'
    ).prefetch_related(
        'enseignants__user'
    )

    data = []
    for c in cours:
        enseignants_data = []
        for e in c.enseignants.all():
            enseignants_data.append({
                'id': e.id,
                'username': e.user.username,
                'email': e.user.email,
                'user': {
                    'username': e.user.username,
                    'email': e.user.email,
                }
            })
        
        data.append({
            'id': c.id,
            'titre': c.titre,
            'niveau': c.niveau,
            'description_brief': c.description_brief,
            'color_code': c.color_code,
            'icon_name': c.icon_name,
            'nb_lecons': c.nb_lecons,
            'nb_devoirs': c.nb_devoirs,
            'nb_apprenants': c.nb_apprenants,
            'departement': {
                'id': c.departement.id,
                'nom': c.departement.nom,
            } if c.departement else None,
            'enseignant_principal': {
                'id': c.enseignant_principal.id,
                'nom': f"{c.enseignant_principal.user.first_name} {c.enseignant_principal.user.last_name}".strip() or c.enseignant_principal.user.username,
                'username': c.enseignant_principal.user.username,
            } if c.enseignant_principal else None,
            'enseignants': enseignants_data,
        })

    return Response(data, status=status.HTTP_200_OK)


class DetailQuestionView(APIView):
    """
    GET /api/forum/questions/<pk>/ - Détail d'une question avec ses réponses
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            # Utiliser select_related et prefetch_related pour optimiser
            question = QuestionForum.objects.select_related(
                'auteur__profile'
            ).prefetch_related(
                'reponses__auteur__profile',
                'reponses__likes'
            ).annotate(
                nb_reponses=Count("reponses")
            ).get(pk=pk)
        except QuestionForum.DoesNotExist:
            return Response({"detail": "Question introuvable."}, status=404)

        # Incrémenter les vues de manière atomique
        QuestionForum.objects.filter(pk=pk).update(nb_vues=F('nb_vues') + 1)

        # Forcer le rafraîchissement pour obtenir le nouveau nb_vues
        question.refresh_from_db()

        # Sérialiser
        serializer = QuestionForumDetailSerializer(question, context={"request": request})
        
        # Vérifier que les réponses sont bien chargées
        data = serializer.data
        if 'reponses' in data:
            # Trier les réponses par date (plus récentes en premier)
            data['reponses'] = sorted(
                data['reponses'],
                key=lambda r: r.get('cree_le', ''),
                reverse=True
            )

        return Response(data)

    def delete(self, request, pk):
        try:
            question = QuestionForum.objects.get(pk=pk, auteur=request.user)
        except QuestionForum.DoesNotExist:
            return Response({"detail": "Question introuvable ou non autorisée."}, status=404)
        question.delete()
        return Response(status=204)


class SoumettreDevoirFichierView(APIView):
    """
    POST /api/devoirs/<devoir_id>/soumettre-fichier/
    Permet à un apprenant de soumettre un fichier PDF pour un devoir
    de type correction manuelle.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        if not devoir.est_ouvert:
            return Response(
                {"detail": "Le devoir n'est plus accessible."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Vérifier les tentatives
        nb_tentatives = SoumissionDevoir.objects.filter(
            utilisateur=request.user,
            devoir=devoir,
            statut__in=["soumis", "corrige", "en_retard"]
        ).count()

        if nb_tentatives >= devoir.tentatives_max:
            return Response(
                {"detail": f"Nombre maximum de tentatives atteint ({devoir.tentatives_max})."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Récupérer ou créer la soumission
        soum, created = SoumissionDevoir.objects.get_or_create(
            utilisateur=request.user,
            devoir=devoir,
            defaults={
                "statut": "en_cours",
                "ip_address": _get_client_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:500],
            }
        )

        if not created and soum.statut in ["soumis", "corrige"]:
            return Response(
                {"detail": "Vous avez déjà soumis ce devoir."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Traiter le fichier uploadé
        fichier = request.FILES.get('fichier')
        if not fichier:
            return Response(
                {"detail": "Aucun fichier fourni."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not fichier.name.lower().endswith('.pdf'):
            return Response(
                {"detail": "Seuls les fichiers PDF sont acceptés."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Stocker le fichier dans la soumission
        if hasattr(soum, 'fichier_soumis'):
            soum.fichier_soumis = fichier
        else:
            # Fallback si le champ n'existe pas
            from django.core.files.base import ContentFile
            soum.fichier_soumis = fichier

        now = timezone.now()
        soum.statut    = 'en_retard' if soum.est_en_retard else 'soumis'
        soum.soumis_le = now
        soum.save()

        return Response({
            "statut":    soum.statut,
            "message":   "Fichier soumis avec succès. En attente de correction.",
            "soumis_le": soum.soumis_le.isoformat(),
            "devoir_titre": devoir.titre,
        })

# ─────────────────────────────────────────────────────────────────────────────
# 2. MODIFIER UN DEVOIR
#    PATCH /api/devoirs/<devoir_id>/modifier/
# ─────────────────────────────────────────────────────────────────────────────
class ModifierDevoirView(APIView):
    """
    Modification partielle d'un devoir.
    Réservé à l'enseignant principal du cours lié.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        cours = devoir.cours_lie
        if cours is None or cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal du cours peut modifier ce devoir."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy()
        type_correction = data.pop('type_correction', None)

        serializer = DevoirCreateSerializer(devoir, data=data, partial=True)
        if serializer.is_valid():
            devoir = serializer.save()
            if type_correction and hasattr(devoir, 'type_correction'):
                devoir.type_correction = type_correction
                devoir.save(update_fields=['type_correction'])

            return Response(
                _devoir_to_dict(devoir, request.user),
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────────────────────────────────────────
# 3. AJOUTER UNE QUESTION À UN DEVOIR
#    POST /api/devoirs/<devoir_id>/questions/ajouter/
# ─────────────────────────────────────────────────────────────────────────────
class AjouterQuestionDevoirView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        cours = devoir.cours_lie
        if cours is None or cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut ajouter des questions."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data       = request.data.copy()
        type_q     = data.get('type_question', 'qcm')
        choix_data = data.pop('choix', [])
        bonne_rep  = data.pop('bonne_reponse', '')

        # Créer la question
        question = QuestionDevoir.objects.create(
            devoir        = devoir,
            texte         = data.get('texte', ''),
            type_question = type_q,
            points        = int(data.get('points', 1)),
            ordre         = int(data.get('ordre', devoir.questions.count() + 1)),
        )

        # Bonne réponse pour texte libre
        if type_q == 'texte' and bonne_rep:
            if hasattr(question, 'bonne_reponse'):
                question.bonne_reponse = bonne_rep
                question.save(update_fields=['bonne_reponse'])

        # Choix pour QCM
        if type_q == 'qcm' and choix_data:
            for c in choix_data:
                ChoixReponse.objects.create(
                    question   = question,
                    texte      = c.get('texte', ''),
                    est_correct= c.get('est_correct', False),
                )

        # Sérialiser la réponse
        choix_out = [
            {"id": c.id, "texte": c.texte, "est_correct": c.est_correct}
            for c in question.choix.all()
        ] if type_q == 'qcm' else []

        return Response({
            "id":            question.id,
            "texte":         question.texte,
            "type_question": question.type_question,
            "points":        question.points,
            "ordre":         question.ordre,
            "choix":         choix_out,
        }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# 4. LISTER LES QUESTIONS D'UN DEVOIR
#    GET /api/devoirs/<devoir_id>/questions/
# ─────────────────────────────────────────────────────────────────────────────
class ListeQuestionsDevoirView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, devoir_id):
        devoir    = get_object_or_404(Devoir, pk=devoir_id)
        questions = devoir.questions.prefetch_related('choix').order_by('ordre')

        result = []
        for q in questions:
            choix = [
                {"id": c.id, "texte": c.texte, "est_correct": c.est_correct}
                for c in q.choix.all()
            ]
            result.append({
                "id":            q.id,
                "texte":         q.texte,
                "type_question": q.type_question,
                "points":        q.points,
                "ordre":         q.ordre,
                "choix":         choix,
            })

        return Response(result)


# ─────────────────────────────────────────────────────────────────────────────
# 5. LISTER LES SOUMISSIONS D'UN DEVOIR (vue enseignant)
#    GET /api/devoirs/<devoir_id>/soumissions/
# ─────────────────────────────────────────────────────────────────────────────
class SoumissionsDevoirEnseignantView(APIView):
    """
    Retourne toutes les soumissions d'un devoir.
    Réservé à l'enseignant principal du cours lié.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        cours = devoir.cours_lie
        if cours is None or cours.enseignant_principal != profile:
            return Response(
                {"detail": "Accès réservé à l'enseignant principal."},
                status=status.HTTP_403_FORBIDDEN,
            )

        soumissions = SoumissionDevoir.objects.filter(
            devoir=devoir
        ).select_related('utilisateur').order_by('-debut')

        result = []
        for s in soumissions:
            u = s.utilisateur
            nom = f"{u.first_name} {u.last_name}".strip()
            result.append({
                "id":                  s.id,
                "apprenant_nom":       nom,
                "apprenant_username":  u.username,
                "statut":              s.statut,
                "note":                float(s.note) if s.note is not None else None,
                "soumis_le":           s.soumis_le.isoformat() if s.soumis_le else "",
                "est_suspecte":        s.est_suspecte,
                "nb_focus_perdu":      s.nb_focus_perdu,
                "commentaire":         s.commentaire or "",
            })

        return Response(result)


# ─────────────────────────────────────────────────────────────────────────────
# 6. CORRIGER UNE SOUMISSION MANUELLEMENT
#    PATCH /api/soumissions/<soumission_id>/corriger/
# ─────────────────────────────────────────────────────────────────────────────
class CorrigerSoumissionView(APIView):
    """
    Attribue une note et un commentaire à une soumission.
    Réservé à l'enseignant principal du cours lié.

    Body JSON :
    {
        "note":        15.5,
        "commentaire": "Bon travail, mais…"
    }
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, soumission_id):
        soum = get_object_or_404(SoumissionDevoir, pk=soumission_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        cours = soum.devoir.cours_lie
        if cours is None or cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut corriger cette soumission."},
                status=status.HTTP_403_FORBIDDEN,
            )

        note_raw = request.data.get('note')
        if note_raw is None:
            return Response(
                {"detail": "Le champ 'note' est requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            note = float(note_raw)
        except (TypeError, ValueError):
            return Response(
                {"detail": "La note doit être un nombre."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        note_sur = float(soum.devoir.note_sur)
        if note < 0 or note > note_sur:
            return Response(
                {"detail": f"La note doit être entre 0 et {note_sur}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        soum.note        = note
        soum.statut      = 'corrige'
        soum.commentaire = request.data.get('commentaire', '')
        soum.corrige_le  = timezone.now()
        soum.save(update_fields=['note', 'statut', 'commentaire', 'corrige_le'])
        enregistrer_activite(
       user=request.user,
       action='submission_graded',
       description=f"Soumission de {soum.utilisateur.get_full_name() or soum.utilisateur.username} corrigée — note: {soum.note}/{soum.devoir.note_sur}",
       data={
           'apprenant': soum.utilisateur.get_full_name() or soum.utilisateur.username,
           'devoir':    soum.devoir.titre,
           'note':      str(soum.note),
           'note_sur':  str(soum.devoir.note_sur),
       },
       objet_id=soum.id,
       objet_type='Soumission',
   )

        return Response({
            "id":          soum.id,
            "note":        float(soum.note),
            "statut":      soum.statut,
            "commentaire": soum.commentaire,
            "corrige_le":  soum.corrige_le.isoformat(),
        }, status=status.HTTP_200_OK)

# ─────────────────────────────────────────────────────────────────────────────
# 8. DÉTAIL D'UNE SOUMISSION AVEC SES RÉPONSES (pour l'enseignant)
#    GET /api/soumissions/<soumission_id>/detail/
# ─────────────────────────────────────────────────────────────────────────────
class DetailSoumissionEnseignantView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, soumission_id):
        soum = get_object_or_404(SoumissionDevoir, pk=soumission_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        cours = soum.devoir.cours_lie
        if cours is None or cours.enseignant_principal != profile:
            return Response(
                {"detail": "Accès réservé à l'enseignant principal."},
                status=status.HTTP_403_FORBIDDEN,
            )

        u   = soum.utilisateur
        nom = f"{u.first_name} {u.last_name}".strip()

        reponses = []
        for rep in soum.reponses.select_related('question', 'choix').all():
            reponses.append({
                "question_id":    rep.question.id,
                "question_texte": rep.question.texte,
                "type_question":  rep.question.type_question,
                "reponse":        rep.reponse,
                "est_correct":    rep.est_correct,
                "points_obtenus": rep.points_obtenus,
                "points_max":     rep.question.points,
            })

        fichier_url = None
        if hasattr(soum, 'fichier_soumis') and soum.fichier_soumis:
            fichier_url = request.build_absolute_uri(soum.fichier_soumis.url)

        return Response({
            "id":                  soum.id,
            "apprenant_nom":       nom or u.username,
            "apprenant_username":  u.username,
            "statut":              soum.statut,
            "note":                float(soum.note) if soum.note is not None else None,
            "note_sur":            float(soum.devoir.note_sur),
            "commentaire":         soum.commentaire or "",
            "soumis_le":           soum.soumis_le.isoformat() if soum.soumis_le else "",
            "corrige_le":          soum.corrige_le.isoformat() if soum.corrige_le else "",
            "en_retard":           soum.est_en_retard,
            "est_suspecte":        soum.est_suspecte,
            "nb_focus_perdu":      soum.nb_focus_perdu,
            "reponses":            reponses,
            "fichier_soumis":      fichier_url,
        })


# ─────────────────────────────────────────────────────────────────────────────
# 9. STATS D'UN DEVOIR (pour l'enseignant)
#    GET /api/devoirs/<devoir_id>/stats/
# ─────────────────────────────────────────────────────────────────────────────
class StatsDevoirEnseignantView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, devoir_id):
        devoir = get_object_or_404(Devoir, pk=devoir_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        cours = devoir.cours_lie
        if cours is None or cours.enseignant_principal != profile:
            return Response(
                {"detail": "Accès réservé à l'enseignant principal."},
                status=status.HTTP_403_FORBIDDEN,
            )

        soumissions = SoumissionDevoir.objects.filter(devoir=devoir)
        total       = soumissions.count()
        corriges    = soumissions.filter(statut='corrige').count()
        en_attente  = soumissions.filter(
            statut__in=['soumis', 'en_retard']
        ).count()
        suspects    = soumissions.filter(est_suspecte=True).count()

        notes = list(soumissions.filter(
            note__isnull=False
        ).values_list('note', flat=True))

        moyenne = sum(notes) / len(notes) if notes else 0
        note_max = max(notes) if notes else 0
        note_min = min(notes) if notes else 0

        return Response({
            "total_soumissions": total,
            "corriges":          corriges,
            "en_attente":        en_attente,
            "suspects":          suspects,
            "moyenne":           round(moyenne, 2),
            "note_max":          float(note_max),
            "note_min":          float(note_min),
            "note_sur":          float(devoir.note_sur),
        })


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaire helper
# ─────────────────────────────────────────────────────────────────────────────
def _devoir_to_dict(devoir, user=None):
    """Sérialise un Devoir en dictionnaire pour les réponses API."""
    soumission_data = None
    if user:
        soum = SoumissionDevoir.objects.filter(
            devoir=devoir, utilisateur=user
        ).first()
        if soum:
            soumission_data = {
                'id':     soum.id,
                'statut': soum.statut,
                'note':   float(soum.note) if soum.note is not None else None,
                'soumis_le': soum.soumis_le.isoformat() if soum.soumis_le else None,
            }

    return {
        'id':              devoir.id,
        'titre':           devoir.titre,
        'description':     devoir.description,
        'date_debut':      devoir.date_debut.isoformat() if devoir.date_debut else None,
        'date_limite':     devoir.date_limite.isoformat() if devoir.date_limite else None,
        'est_ouvert':      devoir.est_ouvert,
        'est_expire':      devoir.est_expire,
        'nb_questions':    devoir.questions.count(),
        'note_sur':        float(devoir.note_sur) if hasattr(devoir, 'note_sur') else 20,
        'duree_minutes':   devoir.duree_minutes,
        'tentatives_max':  devoir.tentatives_max,
        'est_publie':      devoir.est_publie,
        'type_correction': getattr(devoir, 'type_correction', 'auto'),
        'ma_soumission':   soumission_data,
    }


def _get_client_ip(request):
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ═══════════════════════════════════════════════════════════════
#  OLYMPIADES
# ═══════════════════════════════════════════════════════════════

class ListeOlympiadesView(APIView):
    """GET /api/olympiades/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Olympiade.objects.all().order_by("-date_debut_olympiade")

        matiere = request.query_params.get("matiere")
        niveau  = request.query_params.get("niveau")
        statut  = request.query_params.get("statut")

        if matiere:
            qs = qs.filter(matiere=matiere)
        if niveau:
            qs = qs.filter(niveau=niveau)

        serializer = OlympiadeListSerializer(qs, many=True, context={"request": request})
        data = serializer.data

        # Filtre statut post-sérialisation
        if statut:
            data = [d for d in data if d["statut"] == statut]

        return Response(data)


class DetailOlympiadeView(APIView):
    """GET /api/olympiades/<id>/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)
        serializer = OlympiadeDetailSerializer(olympiade, context={"request": request})
        return Response(serializer.data)


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
                status=status.HTTP_403_FORBIDDEN
            )
        if now > olympiade.date_cloture_inscription:
            return Response(
                {"detail": "Les inscriptions sont clôturées."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Vérifier si l'olympiade est payante pour les participants
        if olympiade.demande_paiement_participants and olympiade.prix_participation > 0:
            # Vérifier si l'apprenant a déjà payé
            paiement = PaiementOlympiade.objects.filter(
                apprenant=request.user,
                olympiade=olympiade,
                statut='paye'
            ).first()
            
            if not paiement:
                return Response({
                    "detail": "Cette olympiade requiert un paiement de participation.",
                    "prix_participation": olympiade.prix_participation,
                    "olympiade_id": olympiade.id,
                    "need_payment": True,
                }, status=status.HTTP_402_PAYMENT_REQUIRED)

        inscription, created = InscriptionOlympiade.objects.get_or_create(
            olympiade=olympiade,
            apprenant=request.user,
            defaults={
                "ip_inscription": self._get_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:500],
            }
        )

        if not created:
            return Response(
                {"detail": "Vous êtes déjà inscrit à cette olympiade."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = InscriptionOlympiadeSerializer(inscription, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def _get_ip(self, request):
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded:
            return x_forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


# 4. Vue pour payer une olympiade
class PayerOlympiadeView(APIView):
    """
    POST /api/olympiades/<id>/payer/
    Body: {"montant": 500}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)
        
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Seuls les enseignants cadres peuvent payer pour une olympiade."},
                status=403
            )

        # Vérifier que le cadre est l'organisateur
        if olympiade.organisateur != profile:
            return Response(
                {"detail": "Vous n'êtes pas l'organisateur de cette olympiade."},
                status=403
            )

        # Vérifier que l'olympiade n'est pas déjà payée
        if olympiade.devoir.est_publie:
            return Response(
                {"detail": "Cette olympiade est déjà payée et publiée."},
                status=400
            )

        montant = request.data.get('montant', 0)
        try:
            montant = int(montant)
        except (TypeError, ValueError):
            return Response({"detail": "Montant invalide."}, status=400)

        # Vérifier le montant minimum
        if montant < olympiade.prix_global:
            return Response({
                "detail": f"Le montant minimum est de {olympiade.prix_global} FCFA.",
                "prix_global": olympiade.prix_global
            }, status=400)

        # Simuler un paiement (à intégrer avec CinetPay)
        # Pour l'instant, on valide directement
        olympiade.devoir.est_publie = True
        olympiade.devoir.save(update_fields=['est_publie'])
        olympiade.est_validee = True
        olympiade.save(update_fields=['est_validee'])

        # Enregistrer le paiement
        Paiement.objects.create(
            utilisateur=request.user,
            type_paiement='olympiade',
            moyen='wallet',
            montant=montant,
            statut='succes',
            olympiade_liee=olympiade,
            commission_yeki=int(montant * 0.15),
        )

        enregistrer_activite(
            user=request.user,
            action='olympiad_paid',
            description=f"Paiement de {montant} FCFA pour l'olympiade « {olympiade.titre} »",
            objet_id=olympiade.id,
            objet_type='Olympiade',
        )

        return Response({
            "detail": "Paiement effectué avec succès. L'olympiade est maintenant publiée.",
            "montant": montant,
            "olympiade_id": olympiade.id,
        }, status=200)


# 5. Vue pour payer la participation à une olympiade (apprenant)
class PayerParticipationOlympiadeView(APIView):
    """
    POST /api/olympiades/<id>/payer-participation/
    Body: {"montant": 100}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)
        
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'apprenant':
            return Response(
                {"detail": "Seuls les apprenants peuvent payer leur participation."},
                status=403
            )

        if not olympiade.demande_paiement_participants:
            return Response(
                {"detail": "Cette olympiade ne demande pas de paiement de participation."},
                status=400
            )

        if olympiade.prix_participation <= 0:
            return Response(
                {"detail": "Le prix de participation est invalide."},
                status=400
            )

        # Vérifier que l'apprenant n'a pas déjà payé
        if PaiementOlympiade.objects.filter(
            apprenant=request.user,
            olympiade=olympiade,
            statut='paye'
        ).exists():
            return Response(
                {"detail": "Vous avez déjà payé pour cette olympiade."},
                status=400
            )

        montant = request.data.get('montant', olympiade.prix_participation)
        try:
            montant = int(montant)
        except (TypeError, ValueError):
            return Response({"detail": "Montant invalide."}, status=400)

        if montant < olympiade.prix_participation:
            return Response({
                "detail": f"Le montant minimum est de {olympiade.prix_participation} FCFA.",
                "prix_participation": olympiade.prix_participation
            }, status=400)

        # Créer le paiement
        paiement = PaiementOlympiade.objects.create(
            apprenant=request.user,
            olympiade=olympiade,
            montant=montant,
            statut='paye',
            paye_le=timezone.now(),
        )

        # Enregistrer dans Paiement global
        Paiement.objects.create(
            utilisateur=request.user,
            type_paiement='olympiade_participation',
            moyen='wallet',
            montant=montant,
            statut='succes',
            olympiade_liee=olympiade,
        )

        return Response({
            "detail": "Paiement de participation effectué avec succès.",
            "montant": montant,
            "reference": paiement.reference,
        }, status=200)

class DemarrerOlympiadeView(APIView):
    """
    POST /api/olympiades/<id>/demarrer/
    Démarre la session de composition.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)
        now = timezone.now()

        if olympiade.statut_auto != "en_cours":
            return Response(
                {"detail": "L'olympiade n'est pas en cours actuellement."},
                status=status.HTTP_403_FORBIDDEN
            )

        inscription = get_object_or_404(
            InscriptionOlympiade,
            olympiade=olympiade,
            apprenant=request.user,
            statut="inscrit"
        )

        if inscription.soumis:
            return Response(
                {"detail": "Vous avez déjà soumis votre composition."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Si une session unique est imposée et déjà démarrée
        if olympiade.une_seule_session and inscription.session_demarree:
            return Response(
                {"detail": "Vous ne pouvez pas reprendre une session interrompue."},
                status=status.HTTP_403_FORBIDDEN
            )

        inscription.session_demarree  = True
        inscription.heure_debut_compo = inscription.heure_debut_compo or now
        inscription.ip_composition    = self._get_ip(request)
        inscription.save(update_fields=[
            "session_demarree", "heure_debut_compo", "ip_composition"
        ])

        serializer = InscriptionOlympiadeSerializer(inscription, context={"request": request})
        return Response({
            "inscription":          serializer.data,
            "temps_restant_secondes": inscription.temps_restant_secondes(),
        })

    def _get_ip(self, request):
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded:
            return x_forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


class SoumettreOlympiadeView(APIView):
    """POST /api/olympiades/<id>/soumettre/"""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        inscription = get_object_or_404(
            InscriptionOlympiade,
            olympiade=olympiade,
            apprenant=request.user,
            session_demarree=True
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
                        repobj.est_correct    = True
                        repobj.points_obtenus = question.points
                        score += question.points
                    else:
                        repobj.est_correct    = False
                        repobj.points_obtenus = 0
                    repobj.save()

        # ── Finaliser inscription ────────────────────────────────
        note = round((score / total) * olympiade.note_sur, 2) if total > 0 else 0
        now  = timezone.now()

        inscription.soumis              = True
        inscription.soumis_automatique  = auto
        inscription.heure_fin_compo     = now
        inscription.note                = note
        inscription.save()

        return Response({
            "message":       "Composition soumise." if not auto else "Temps écoulé — soumission automatique.",
            "note":          note,
            "note_sur":      olympiade.note_sur,
            "auto_soumis":   auto,
        })


class FocusPeduOlympiadeView(APIView):
    """
    POST /api/olympiades/<id>/focus-perdu/
    Flutter appelle cet endpoint à chaque perte de focus.
    Si le seuil est atteint → soumission automatique.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        inscription = get_object_or_404(
            InscriptionOlympiade,
            olympiade=olympiade,
            apprenant=request.user,
            session_demarree=True,
            soumis=False
        )

        inscription.nb_focus_perdu += 1

        if inscription.nb_focus_perdu >= olympiade.max_focus_perdu:
            inscription.est_suspecte   = True
            inscription.soumis         = True
            inscription.soumis_automatique = True
            inscription.raison_suspicion = (
                f"Trop de pertes de focus ({inscription.nb_focus_perdu})"
            )
            inscription.heure_fin_compo = timezone.now()
            # Calculer le score avec ce qui a été soumis jusqu'ici
            inscription.save()
            return Response({
                "detail":       "Composition soumise automatiquement pour comportement suspect.",
                "force_submit": True,
            }, status=status.HTTP_200_OK)

        inscription.save(update_fields=["nb_focus_perdu", "est_suspecte"])

        return Response({
            "nb_focus_perdu":   inscription.nb_focus_perdu,
            "max_focus_perdu":  olympiade.max_focus_perdu,
            "restants":         olympiade.max_focus_perdu - inscription.nb_focus_perdu,
            "force_submit":     False,
        })


class ClassementOlympiadeView(APIView):
    """GET /api/olympiades/<id>/classement/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        if olympiade.statut_auto not in ["terminee"]:
            # Résultats visibles seulement après la fin
            return Response(
                {"detail": "Le classement sera disponible à la fin de l'olympiade."},
                status=status.HTTP_403_FORBIDDEN
            )

        classement = ClassementOlympiade.objects.filter(
            olympiade=olympiade
        ).select_related("apprenant").order_by("rang")

        serializer = ClassementOlympiadeSerializer(classement, many=True)
        return Response(serializer.data)


class CalculerClassementView(APIView):
    """
    POST /api/olympiades/<id>/calculer-classement/
    Réservé admin / organisateur — calcule et sauvegarde le classement final.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, olympiade_id):
        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        # Vérifier que l'organisateur ou admin fait la requête
        try:
            profile = request.user.profile
        except Exception:
            return Response({"detail": "Profil introuvable."}, status=400)

        if profile.user_type not in ["admin", "enseignant_admin"] and \
           olympiade.organisateur != profile:
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
       action='ranking_computed',
       description=f"Classement calculé pour l'olympiade « {olympiade.titre} » ({inscriptions.count()} participants)",
       data={
           'olympiade':    olympiade.titre,
           'participants': inscriptions.count(),
       },
       objet_id=olympiade.id,
       objet_type='Olympiade',
   )

        return Response({
            "detail": f"Classement calculé pour {inscriptions.count()} participants.",
            "nb": inscriptions.count(),
        })


class MonInscriptionOlympiadeView(APIView):
    """GET /api/olympiades/<id>/mon-inscription/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, olympiade_id):
        inscription = get_object_or_404(
            InscriptionOlympiade,
            olympiade_id=olympiade_id,
            apprenant=request.user
        )
        serializer = InscriptionOlympiadeSerializer(inscription, context={"request": request})
        return Response(serializer.data)
    

# ─────────────────────────────────────────────────────────────────
# GET  /api/forum/questions/          → liste des questions
# POST /api/forum/questions/          → créer une question
# ─────────────────────────────────────────────────────────────────

# views.py - Mettre à jour la classe ListeQuestionsView

class ListeQuestionsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        qs = QuestionForum.objects.select_related('auteur__profile').all()
        
        # Filtres
        source = request.query_params.get("source")
        lecon_id = request.query_params.get("lecon_id")
        exercice_id = request.query_params.get("exercice_id")
        devoir_id = request.query_params.get("devoir_id")
        cours_id = request.query_params.get("cours_id")
        resolue = request.query_params.get("resolue")
        since = request.query_params.get("since")

        if source:
            qs = qs.filter(source=source)
        if lecon_id:
            qs = qs.filter(lecon_id=lecon_id)
        if exercice_id:
            qs = qs.filter(exercice_id=exercice_id)
        if devoir_id:
            qs = qs.filter(devoir_id=devoir_id)
        if cours_id:
            qs = qs.filter(cours_id=cours_id)
        if resolue is not None:
            qs = qs.filter(est_resolue=(resolue == "true"))
        if since:
            qs = qs.filter(cree_le__gt=since)

        from django.db.models import Count
        qs = qs.annotate(nb_reponses=Count("reponses", distinct=True))
        qs = qs.order_by("-cree_le")

        serializer = QuestionForumListSerializer(
            qs, many=True, context={"request": request}
        )
        return Response(serializer.data)

    def post(self, request):
        # ⭐ CRITIQUE : Extraire les données du request.data (qui peut être QueryDict pour multipart)
        data = {}
        
        # Copier les champs texte
        for key in ['contenu', 'source', 'lecon_id', 'lecon_titre', 
                    'cours_id', 'cours_titre', 'exercice_id', 'exercice_titre',
                    'devoir_id', 'devoir_titre']:
            if key in request.data:
                data[key] = request.data[key]
        
        # Gérer les fichiers
        if 'image' in request.FILES:
            data['image'] = request.FILES['image']
        if 'audio' in request.FILES:
            data['audio'] = request.FILES['audio']
        
        serializer = QuestionForumCreateSerializer(
            data=data, context={"request": request}
        )
        
        if serializer.is_valid():
            question = serializer.save()
            
            # Recharger avec les annotations
            from django.db.models import Count
            question = QuestionForum.objects.annotate(
                nb_reponses=Count("reponses")
            ).get(pk=question.pk)
            
            return Response(
                QuestionForumListSerializer(question, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )
        
        # ⭐ Afficher les erreurs détaillées
        print("Serializer errors:", serializer.errors)
        return Response(
            {"detail": "Erreur de validation", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )

# ─────────────────────────────────────────────────────────────────
# PATCH /api/forum/questions/<pk>/resoudre/  → marquer comme résolue
# ─────────────────────────────────────────────────────────────────
class ResoudreQuestionView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            question = QuestionForum.objects.get(pk=pk, auteur=request.user)
        except QuestionForum.DoesNotExist:
            return Response(status=404)
        question.est_resolue = not question.est_resolue
        question.save()
        return Response({"est_resolue": question.est_resolue})


# ─────────────────────────────────────────────────────────────────
# POST /api/forum/questions/<pk>/repondre/   → ajouter une réponse
# ─────────────────────────────────────────────────────────────────
class RepondreQuestionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            question = QuestionForum.objects.get(pk=pk)
        except QuestionForum.DoesNotExist:
            return Response({"detail": "Question introuvable."}, status=404)

        contenu = request.data.get('contenu', '').strip()
        if not contenu:
            return Response({"detail": "Le contenu de la réponse est requis."}, status=400)

        reponse = ReponseQuestion.objects.create(
            question=question,
            auteur=request.user,
            contenu=contenu,
            est_solution=False,
        )

        serializer = ReponseSerializer(reponse, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────
# POST /api/forum/reponses/<pk>/liker/   → liker/unliker une réponse
# ─────────────────────────────────────────────────────────────────
class LikerReponseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            reponse = ReponseQuestion.objects.get(pk=pk)
        except ReponseQuestion.DoesNotExist:
            return Response(status=404)

        like, created = LikeReponse.objects.get_or_create(
            reponse=reponse, utilisateur=request.user
        )
        if not created:
            like.delete()
            liked = False
        else:
            liked = True

        return Response({"liked": liked, "nb_likes": reponse.likes.count()})


# ─────────────────────────────────────────────────────────────────
# PATCH /api/forum/reponses/<pk>/solution/  → marquer comme solution
# ─────────────────────────────────────────────────────────────────
class MarquerSolutionView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            reponse = ReponseQuestion.objects.get(pk=pk)
            # Seul l'auteur de la question ou un enseignant peut marquer comme solution
            if reponse.question.auteur != request.user:
                # Vérifier si l'utilisateur est enseignant (adapter selon ton modèle)
                # Pour l'instant on vérifie juste l'auteur de la question
                return Response(status=403)
        except ReponseQuestion.DoesNotExist:
            return Response(status=404)

        reponse.est_solution = not reponse.est_solution
        reponse.save()

        # Résoudre la question automatiquement si une solution est marquée
        if reponse.est_solution:
            reponse.question.est_resolue = True
            reponse.question.save()

        return Response({"est_solution": reponse.est_solution})


# ─────────────────────────────────────────────────────────────────
# GET /api/forum/stats/   → statistiques pour la page forum
# ─────────────────────────────────────────────────────────────────
class StatsForumView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        total     = QuestionForum.objects.count()
        resolues  = QuestionForum.objects.filter(est_resolue=True).count()
        lecons    = QuestionForum.objects.filter(source="lecon").count()
        exercices = QuestionForum.objects.filter(source="exercice").count()
        devoirs   = QuestionForum.objects.filter(source="devoir").count()

        return Response({
            "total":     total,
            "resolues":  resolues,
            "lecons":    lecons,
            "exercices": exercices,
            "devoirs":   devoirs,
        })


# ───────────────────────────────────────────────────────────────────────────
# ENDPOINT 1 : GET /api/enseignant/cadre/dashboard/
#
# Retourne tout ce dont la page CadreDashboardPage a besoin :
#   - nom          : prénom + nom du cadre connecté
#   - departement  : { id, nom, description, parcours, nb_cours, nb_apprenants }
#   - cours        : liste des cours du département
#   - enseignants_principaux : EP distincts dans ces cours + leurs stats
#   - stats        : { nb_cours, nb_apprenants, nb_enseignants, taux_moyen }
# ───────────────────────────────────────────────────────────────────────────

def _nb_apprenants_pour_parcours(nom_parcours: str) -> int:
    """
    Calcule dynamiquement le nombre d'apprenants inscrits dans un parcours.
    Un apprenant est "dans" un parcours si profile.cursus == nom_parcours.
    Beaucoup plus fiable que le compteur nb_apprenants (jamais mis à jour).
    """
    return Profile.objects.filter(
        user_type='apprenant',
        cursus=nom_parcours,
        is_active=True,
    ).count()


class EnseignantCadreDashboardView(APIView):
    """
    GET /api/enseignant/cadre/dashboard/
    
    Retourne tous les départements gérés par l'enseignant cadre,
    avec leurs cours, enseignants principaux et statistiques.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=status.HTTP_403_FORBIDDEN
            )

        # ✅ Récupérer TOUS les départements du cadre
        departements = Departement.objects.filter(
            cadre=profile,
            est_actif=True
        ).select_related('parcours').prefetch_related(
            'cours__enseignant_principal__user',
            'cours__enseignants__user'
        )

        nom_complet = (
            f"{profile.user.first_name} {profile.user.last_name}".strip()
            or profile.user.username
        )

        # Si aucun département, retourner une structure vide
        if not departements.exists():
            return Response({
                "nom": nom_complet,
                "departements": [],
                "stats": {
                    "nb_departements": 0,
                    "nb_cours": 0,
                    "nb_apprenants": 0,
                    "nb_enseignants": 0,
                    "taux_moyen": 0,
                },
            }, status=status.HTTP_200_OK)

        # ── Construire les données pour chaque département ──
        departements_data = []
        stats_globales = {
            "nb_departements": departements.count(),
            "nb_cours": 0,
            "nb_apprenants": 0,
            "nb_enseignants": 0,
            "taux_moyen": 0,
        }
        
        # Pour éviter les doublons d'enseignants
        enseignants_ids = set()
        total_taux = 0

        for dept in departements:
            # Récupérer les cours du département
            cours_qs = Cours.objects.filter(
                departement=dept
            ).select_related('enseignant_principal__user')
            
            cours_data = []
            for c in cours_qs:
                ep_data = None
                if c.enseignant_principal:
                    ep = c.enseignant_principal
                    ep_data = {
                        "id": ep.id,
                        "nom": f"{ep.user.first_name} {ep.user.last_name}".strip() or ep.user.username,
                        "username": ep.user.username,
                        "photo": request.build_absolute_uri(ep.avatar.url) if ep.avatar else None,
                    }
                    enseignants_ids.add(ep.id)
                
                # Calcul du taux de complétion moyen du cours
                taux_completion = self._calculer_taux_completion_cours(c, request.user)
                
                cours_data.append({
                    "id": c.id,
                    "titre": c.titre,
                    "niveau": c.niveau,
                    "nb_apprenants": c.nb_apprenants,
                    "taux_completion": taux_completion,
                    "color_code": c.color_code,
                    "icon_name": c.icon_name,
                    "enseignant_principal": ep_data,
                    "nb_lecons": c.nb_lecons,
                    "nb_devoirs": c.nb_devoirs,
                })
                
                stats_globales["nb_cours"] += 1
                total_taux += taux_completion

            # Récupérer les apprenants du parcours (calcul dynamique)
            parcours_nom = dept.parcours.nom if dept.parcours else ''
            nb_apprenants = Profile.objects.filter(
                user_type='apprenant',
                cursus=parcours_nom,
                is_active=True
            ).count()
            stats_globales["nb_apprenants"] += nb_apprenants

            # Données du département
            dept_data = {
                "id": dept.id,
                "nom": dept.nom,
                "description": getattr(dept, 'description', ''),
                "parcours": dept.parcours.nom if dept.parcours else "",
                "parcours_id": dept.parcours.id if dept.parcours else None,
                "couleur": dept.couleur,
                "prix": dept.prix,
                "est_actif": dept.est_actif,
                "type_departement": dept.type_departement,
                "image_url": request.build_absolute_uri(dept.image.url) if dept.image else None,
                # Champs spécifiques
                "est_prepa_concours": dept.est_prepa_concours,
                "nom_concours": dept.nom_concours,
                "organisme_concours": dept.organisme_concours,
                "date_limite_inscription": dept.date_limite_inscription,
                "date_examen": dept.date_examen,
                "est_formation_metier": dept.est_formation_metier,
                "est_formation_classique": dept.est_formation_classique,
                "duree_formation": dept.duree_formation,
                "mode": dept.mode,
                "certificat_delivre": dept.certificat_delivre,
                "ville": dept.ville,
                "domaine": dept.domaine,
                "est_certifiante": dept.est_certifiante,
                # Statistiques
                "nb_cours": cours_qs.count(),
                "nb_apprenants": nb_apprenants,
                "taux_moyen": self._calculer_taux_moyen_departement(cours_qs, request.user),
                "cours": cours_data,
            }
            departements_data.append(dept_data)

        # ── Enseignants principaux distincts ──
        enseignants_data = []
        for ep_id in enseignants_ids:
            try:
                ep = Profile.objects.get(id=ep_id)
                nb_cours_ep = Cours.objects.filter(
                    enseignant_principal=ep,
                    departement__in=departements
                ).count()
                nb_app_ep = sum(
                    c.nb_apprenants
                    for c in Cours.objects.filter(
                        enseignant_principal=ep,
                        departement__in=departements
                    )
                )
                
                # Score moyen à partir des évaluations
                from django.db.models import Avg
                avg = EvaluationExercice.objects.filter(
                    exercice__cours__enseignant_principal=ep,
                    exercice__cours__departement__in=departements
                ).aggregate(moy=Avg('score'))['moy']
                score_moyen = round((avg or 0) / 20 * 20, 1)
                
                enseignants_data.append({
                    "id": ep.id,
                    "nom": f"{ep.user.first_name} {ep.user.last_name}".strip() or ep.user.username,
                    "username": ep.user.username,
                    "email": ep.user.email,
                    "photo": request.build_absolute_uri(ep.avatar.url) if ep.avatar else None,
                    "nb_cours": nb_cours_ep,
                    "nb_apprenants": nb_app_ep,
                    "score_moyen": score_moyen,
                })
            except Profile.DoesNotExist:
                pass

        # Calcul des moyennes globales
        if stats_globales["nb_cours"] > 0:
            stats_globales["taux_moyen"] = round(total_taux / stats_globales["nb_cours"], 1)
        stats_globales["nb_enseignants"] = len(enseignants_data)

        return Response({
            "nom": nom_complet,
            "departements": departements_data,
            "enseignants_principaux": enseignants_data,
            "stats": stats_globales,
        }, status=status.HTTP_200_OK)

    def _calculer_taux_completion_cours(self, cours, user):
        """Calcule le taux de complétion d'un cours pour un apprenant donné."""
        total_lecons = Lecon.objects.filter(cours=cours).count()
        if total_lecons == 0:
            return 0.0
        terminees = ProgressionLecon.objects.filter(
            apprenant=user,
            cours=cours,
            terminee=True
        ).count()
        return round((terminees / total_lecons) * 100, 1)

    def _calculer_taux_moyen_departement(self, cours_qs, user):
        """Calcule le taux de complétion moyen d'un département."""
        if not cours_qs.exists():
            return 0.0
        total = 0
        count = 0
        for cours in cours_qs:
            taux = self._calculer_taux_completion_cours(cours, user)
            total += taux
            count += 1
        return round(total / count, 1) if count > 0 else 0.0


# views.py - Ajouter

class EnseignantCadreDepartementDetailView(APIView):
    """
    GET /api/enseignant/cadre/departement/<departement_id>/
    
    Retourne les détails complets d'un département pour l'enseignant cadre.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=status.HTTP_403_FORBIDDEN
            )

        departement = get_object_or_404(Departement, pk=departement_id, cadre=profile)

        cours_qs = Cours.objects.filter(
            departement=departement
        ).select_related('enseignant_principal__user')

        cours_data = []
        for c in cours_qs:
            ep_data = None
            if c.enseignant_principal:
                ep = c.enseignant_principal
                ep_data = {
                    "id": ep.id,
                    "nom": f"{ep.user.first_name} {ep.user.last_name}".strip() or ep.user.username,
                }
            cours_data.append({
                "id": c.id,
                "titre": c.titre,
                "niveau": c.niveau,
                "description_brief": c.description_brief,
                "color_code": c.color_code,
                "icon_name": c.icon_name,
                "nb_lecons": c.nb_lecons,
                "nb_devoirs": c.nb_devoirs,
                "nb_apprenants": c.nb_apprenants,
                "enseignant_principal": ep_data,
            })

        return Response({
            "id": departement.id,
            "nom": departement.nom,
            "description": departement.description,
            "parcours": departement.parcours.nom if departement.parcours else "",
            "couleur": departement.couleur,
            "prix": departement.prix,
            "type_departement": departement.type_departement,
            "cours": cours_data,
            "nb_cours": cours_qs.count(),
        }, status=status.HTTP_200_OK)


class EnseignantCadreDepartementUpdateView(APIView):
    """
    PATCH /api/enseignant/cadre/departement/<departement_id>/update/
    
    Met à jour les informations d'un département.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=status.HTTP_403_FORBIDDEN
            )

        departement = get_object_or_404(Departement, pk=departement_id, cadre=profile)

        data = request.data
        updates = {}

        if 'nom' in data:
            updates['nom'] = data['nom'].strip()
        if 'description' in data:
            updates['description'] = data['description'].strip()
        if 'couleur' in data:
            updates['couleur'] = data['couleur']
        if 'prix' in data:
            updates['prix'] = int(data['prix'])
        if 'est_actif' in data:
            updates['est_actif'] = data['est_actif']

        if updates:
            for key, value in updates.items():
                setattr(departement, key, value)
            departement.save()

        return Response({
            "detail": "Département mis à jour avec succès.",
            "departement": {
                "id": departement.id,
                "nom": departement.nom,
                "description": departement.description,
                "couleur": departement.couleur,
                "prix": departement.prix,
                "est_actif": departement.est_actif,
            }
        }, status=status.HTTP_200_OK)


# ───────────────────────────────────────────────────────────────────────────
# ENDPOINT 2 : PATCH /api/cours/<cours_id>/changer-enseignant-principal/
#
# Body  : { "enseignant_principal_id": <int> }
# Accès : enseignant_cadre du département auquel appartient le cours
# ───────────────────────────────────────────────────────────────────────────
class ChangerEnseignantPrincipalView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, cours_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=status.HTTP_403_FORBIDDEN
            )

        cours = get_object_or_404(Cours, pk=cours_id)

        # Sécurité : le cadre ne peut modifier que les cours de son département
        if cours.departement.cadre != profile:
            return Response(
                {"detail": "Ce cours n'appartient pas à votre département."},
                status=status.HTTP_403_FORBIDDEN
            )

        ep_id = request.data.get('enseignant_principal_id')
        if not ep_id:
            return Response(
                {"detail": "enseignant_principal_id est requis."},
                status=status.HTTP_400_BAD_REQUEST
            )

        ep = get_object_or_404(Profile, pk=ep_id)
        if ep.user_type != 'enseignant_principal':
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant principal."},
                status=status.HTTP_400_BAD_REQUEST
            )

        cours.enseignant_principal = ep
        cours.save(update_fields=['enseignant_principal'])
        enregistrer_activite(
        user=request.user,
        action='teacher_changed',
        description=f"Enseignant principal de « {cours.titre} » changé pour {ep.user.get_full_name() or ep.user.username}",
        data={
            'cours':       cours.titre,
            'enseignant':  ep.user.get_full_name() or ep.user.username,
            'departement': cours.departement.nom,
        },
        objet_id=cours.id,
        objet_type='Cours',
    )

        return Response(
            {"detail": "Enseignant principal mis à jour avec succès."},
            status=status.HTTP_200_OK
        )


class ModifierCoursParCadreView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, cours_id):
        # ── Récupérer le profil ──────────────────────────────────
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        # ── Vérifier le rôle ─────────────────────────────────────
        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Récupérer le cours ───────────────────────────────────
        cours = get_object_or_404(Cours, pk=cours_id)

        # ── Sécurité : le cours doit appartenir au département du cadre ──
        if cours.departement.cadre != profile:
            return Response(
                {"detail": "Ce cours n'appartient pas à votre département."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data

        # ── Titre ────────────────────────────────────────────────
        if 'titre' in data:
            titre = data['titre'].strip()
            if not titre:
                return Response(
                    {"detail": "Le titre ne peut pas être vide."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            cours.titre = titre

        # ── Niveau ───────────────────────────────────────────────
        if 'niveau' in data:
            niveau = data['niveau'].strip()
            if not niveau:
                return Response(
                    {"detail": "Le niveau ne peut pas être vide."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            cours.niveau = niveau

        # ── Description courte ───────────────────────────────────
        if 'description_brief' in data:
            cours.description_brief = (data['description_brief'] or '').strip()

        # ── Couleur ──────────────────────────────────────────────
        if 'color_code' in data:
            color = data['color_code'].strip()
            if color and not color.startswith('#'):
                color = f'#{color}'
            if len(color) not in [4, 7]:   # #RGB ou #RRGGBB
                return Response(
                    {"detail": "Format de couleur invalide. Utilisez #RRGGBB."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            cours.color_code = color

        # ── Icône ─────────────────────────────────────────────────
        if 'icon_name' in data:
            cours.icon_name = (data['icon_name'] or 'school').strip()

        cours.save()

        enregistrer_activite(
        user=request.user,
        action='course_modified',
        description=f"Cours « {cours.titre} » modifié",
        data={'titre': cours.titre, 'niveau': cours.niveau, 'color_code': cours.color_code},
        objet_id=cours.id,
        objet_type='Cours',
    )

        # ── Réponse ───────────────────────────────────────────────
        ep_data = None
        if cours.enseignant_principal:
            ep = cours.enseignant_principal
            ep_data = {
                "id":       ep.id,
                "nom":      f"{ep.user.first_name} {ep.user.last_name}".strip()
                            or ep.user.username,
                "username": ep.user.username,
            }

        return Response({
            "id":               cours.id,
            "titre":            cours.titre,
            "niveau":           cours.niveau,
            "description_brief": cours.description_brief,
            "color_code":       cours.color_code,
            "icon_name":        cours.icon_name,
            "nb_apprenants":    cours.nb_apprenants,
            "nb_lecons":        cours.nb_lecons,
            "nb_devoirs":       cours.nb_devoirs,
            "enseignant_principal": ep_data,
            "detail":           "Cours modifié avec succès.",
        }, status=status.HTTP_200_OK)


class CreerOlympiadeParCadreView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Seuls les enseignants cadres peuvent créer des olympiades."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data

        # ── Validation des champs obligatoires ───────────────────
        titre = (data.get('titre') or '').strip()
        if not titre:
            return Response({"detail": "Le titre est obligatoire."}, status=400)

        matiere = (data.get('matiere') or '').strip()
        if not matiere:
            return Response({"detail": "La matière est obligatoire."}, status=400)

        niveau = (data.get('niveau') or '').strip()
        if not niveau:
            return Response({"detail": "Le niveau est obligatoire."}, status=400)

        # ── Validation du département ─────────────────────────────
        departement_id = data.get('departement_id')
        if not departement_id:
            return Response({"detail": "departement_id est obligatoire."}, status=400)

        departement = get_object_or_404(Departement, pk=departement_id)

        if departement.cadre != profile:
            return Response({"detail": "Ce département ne vous appartient pas."}, status=403)

        parcours = departement.parcours

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

        date_ouv_insc, err = _parse_date('date_ouverture_inscription')
        if err:
            return Response({"detail": err}, status=400)

        date_clo_insc, err = _parse_date('date_cloture_inscription')
        if err:
            return Response({"detail": err}, status=400)

        date_debut, err = _parse_date('date_debut_olympiade')
        if err:
            return Response({"detail": err}, status=400)

        date_fin, err = _parse_date('date_fin_olympiade')
        if err:
            return Response({"detail": err}, status=400)

        # ── Cohérence des dates ───────────────────────────────────
        if date_clo_insc >= date_debut:
            return Response({"detail": "La clôture des inscriptions doit être avant le début de l'olympiade."}, status=400)

        if date_debut >= date_fin:
            return Response({"detail": "Le début de l'olympiade doit être avant sa fin."}, status=400)

        if date_ouv_insc >= date_clo_insc:
            return Response({"detail": "L'ouverture des inscriptions doit être avant leur clôture."}, status=400)

        # ── Paramètres de composition ─────────────────────────────
        try:
            duree_minutes = int(data.get('duree_minutes', 120))
            if duree_minutes < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"detail": "duree_minutes doit être un entier positif."}, status=400)

        try:
            nb_questions = int(data.get('nb_questions', 30))
            if nb_questions < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"detail": "nb_questions doit être un entier positif."}, status=400)

        try:
            max_focus = int(data.get('max_focus_perdu', 3))
            if max_focus < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"detail": "max_focus_perdu doit être un entier positif."}, status=400)

        melanger_questions = bool(data.get('melanger_questions', True))
        melanger_choix = bool(data.get('melanger_choix', True))
        une_seule_session = bool(data.get('une_seule_session', True))

        # ── Niveaux accessibles ────────────────────────────────────
        niveaux_accessibles = data.get('niveaux_accessibles', [])
        if isinstance(niveaux_accessibles, str):
            try:
                niveaux_accessibles = json.loads(niveaux_accessibles)
            except:
                niveaux_accessibles = [n.strip() for n in niveaux_accessibles.split(',') if n.strip()]
        elif not isinstance(niveaux_accessibles, list):
            niveaux_accessibles = []

        # ── Prix et récompenses ───────────────────────────────────
        prix_1er = (data.get('prix_1er') or '').strip()
        prix_2eme = (data.get('prix_2eme') or '').strip()
        prix_3eme = (data.get('prix_3eme') or '').strip()
        recompense = (data.get('recompense') or '').strip()
        
        # Prix de participation par apprenant
        demande_paiement = data.get('demande_paiement_participants', False)
        prix_participation = int(data.get('prix_participation', 0))
        
        if demande_paiement and prix_participation <= 0:
            return Response(
                {"detail": "Veuillez entrer un prix de participation valide."},
                status=400
            )
        
        if prix_participation > 200:
            return Response(
                {"detail": "Le prix de participation ne peut pas dépasser 200 FCFA."},
                status=400
            )

        # ── Calcul du prix global (tarification progressive) ─────────────────
        nb_apprenants = Profile.objects.filter(
            user_type='apprenant',
            cursus=departement.parcours.nom,
            is_active=True
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

        # ── Création de l'olympiade ───────────────────────────────
        olympiade = Olympiade.objects.create(
            titre=titre,
            description=(data.get('description') or '').strip(),
            edition=(data.get('edition') or '').strip(),
            matiere=matiere,
            niveau=niveau,
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
            prix_1er=prix_1er,
            prix_2eme=prix_2eme,
            prix_3eme=prix_3eme,
            recompense=recompense,
            prix_participation=prix_participation,
            demande_paiement_participants=demande_paiement,
            prix_global=prix_global,
            note_sur=20,
            organisateur=profile,
            cree_par=request.user,
            niveaux_accessibles=','.join(niveaux_accessibles) if niveaux_accessibles else '',
        )

        # ── Créer automatiquement un Devoir lié ──────────────────
        devoir_lie = Devoir.objects.create(
            titre=f"[Olympiade] {titre}",
            description=f"Devoir lié à l'olympiade : {titre}",
            type_devoir='olympiade',
            matiere=matiere,
            niveau=niveau,
            enonce=f"Questions de l'olympiade {titre}",
            date_debut=date_debut,
            date_limite=date_fin,
            duree_minutes=duree_minutes,
            note_sur=20,
            est_publie=False,
            cree_par=profile,
        )
        olympiade.devoir = devoir_lie
        olympiade.save(update_fields=['devoir'])

        # ── Gestion de la validation ─────────────────────────────
        message_detail = ""
        besoin_validation = False
        
        # Si prix_global = 0 (pas d'apprenants) → validation admin requise
        if prix_global == 0:
            besoin_validation = True
            devoir_lie.est_publie = False
            devoir_lie.save(update_fields=['est_publie'])
            message_detail = (
                "Olympiade créée avec succès. "
                "Aucun apprenant n'est inscrit dans ce département. "
                "L'administrateur du parcours doit valider l'olympiade avant qu'elle ne soit visible."
            )
        else:
            # Prix global > 0 → demande de paiement au cadre
            devoir_lie.est_publie = False
            devoir_lie.save(update_fields=['est_publie'])
            message_detail = (
                f"Olympiade créée avec succès. "
                f"Un paiement de {prix_global} FCFA est requis pour valider l'olympiade.\n"
                f"Référence : {olympiade.id}\n"
                f"Pour payer, utilisez le portefeuille Yeki ou Mobile Money."
            )

        enregistrer_activite(
            user=request.user,
            action='olympiad_created',
            description=f"Olympiade « {olympiade.titre} » créée",
            data={
                'titre': olympiade.titre,
                'matiere': olympiade.matiere,
                'niveau': olympiade.niveau,
                'edition': olympiade.edition,
                'prix_global': prix_global,
            },
            objet_id=olympiade.id,
            objet_type='Olympiade',
        )

        return Response({
            "id": olympiade.id,
            "titre": olympiade.titre,
            "edition": olympiade.edition,
            "matiere": olympiade.matiere,
            "niveau": olympiade.niveau,
            "statut": olympiade.statut_auto,
            "date_ouverture_inscription": olympiade.date_ouverture_inscription.isoformat(),
            "date_cloture_inscription": olympiade.date_cloture_inscription.isoformat(),
            "date_debut_olympiade": olympiade.date_debut_olympiade.isoformat(),
            "date_fin_olympiade": olympiade.date_fin_olympiade.isoformat(),
            "duree_minutes": olympiade.duree_minutes,
            "nb_questions": olympiade.nb_questions,
            "devoir_id": devoir_lie.id,
            "prix_1er": olympiade.prix_1er,
            "prix_2eme": olympiade.prix_2eme,
            "prix_3eme": olympiade.prix_3eme,
            "recompense": olympiade.recompense,
            "prix_global": prix_global,
            "prix_participation": olympiade.prix_participation,
            "demande_paiement_participants": olympiade.demande_paiement_participants,
            "en_attente_validation": besoin_validation or prix_global > 0,
            "detail": message_detail,
        }, status=status.HTTP_201_CREATED)

# views.py - Ajouter CadreModifierOlympiadeView

class CadreModifierOlympiadeView(APIView):
    """
    PATCH /api/olympiades/<olympiade_id>/modifier/
    Modifie une olympiade qui n'a pas encore de devoir lié.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, olympiade_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=403
            )

        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        # Vérifier que le cadre est l'organisateur
        if olympiade.organisateur != profile:
            return Response(
                {"detail": "Vous n'êtes pas l'organisateur de cette olympiade."},
                status=403
            )

        # Vérifier que l'olympiade n'a pas de devoir lié
        if olympiade.devoir:
            return Response(
                {"detail": "Cette olympiade a déjà un devoir lié. Elle ne peut plus être modifiée."},
                status=400
            )

        # Vérifier que l'olympiade n'est pas validée
        if olympiade.est_validee:
            return Response(
                {"detail": "Cette olympiade est déjà validée. Elle ne peut plus être modifiée."},
                status=400
            )

        data = request.data
        updates = {}

        # Champs modifiables
        if 'titre' in data:
            updates['titre'] = data['titre'].strip()
        if 'description' in data:
            updates['description'] = data['description'].strip()
        if 'matiere' in data:
            updates['matiere'] = data['matiere'].strip()
        if 'niveau' in data:
            updates['niveau'] = data['niveau'].strip()
        if 'edition' in data:
            updates['edition'] = data['edition'].strip()
        if 'date_ouverture_inscription' in data:
            from django.utils.dateparse import parse_datetime
            updates['date_ouverture_inscription'] = parse_datetime(data['date_ouverture_inscription'])
        if 'date_cloture_inscription' in data:
            from django.utils.dateparse import parse_datetime
            updates['date_cloture_inscription'] = parse_datetime(data['date_cloture_inscription'])
        if 'date_debut_olympiade' in data:
            from django.utils.dateparse import parse_datetime
            updates['date_debut_olympiade'] = parse_datetime(data['date_debut_olympiade'])
        if 'date_fin_olympiade' in data:
            from django.utils.dateparse import parse_datetime
            updates['date_fin_olympiade'] = parse_datetime(data['date_fin_olympiade'])
        if 'duree_minutes' in data:
            updates['duree_minutes'] = int(data['duree_minutes'])
        if 'nb_questions' in data:
            updates['nb_questions'] = int(data['nb_questions'])
        if 'max_focus_perdu' in data:
            updates['max_focus_perdu'] = int(data['max_focus_perdu'])
        if 'melanger_questions' in data:
            updates['melanger_questions'] = data['melanger_questions']
        if 'melanger_choix' in data:
            updates['melanger_choix'] = data['melanger_choix']
        if 'une_seule_session' in data:
            updates['une_seule_session'] = data['une_seule_session']
        if 'prix_1er' in data:
            updates['prix_1er'] = data['prix_1er'].strip()
        if 'prix_2eme' in data:
            updates['prix_2eme'] = data['prix_2eme'].strip()
        if 'prix_3eme' in data:
            updates['prix_3eme'] = data['prix_3eme'].strip()
        if 'recompense' in data:
            updates['recompense'] = data['recompense'].strip()
        if 'niveaux_accessibles' in data:
            niveaux = data['niveaux_accessibles']
            if isinstance(niveaux, list):
                updates['niveaux_accessibles'] = ','.join(niveaux)
            else:
                updates['niveaux_accessibles'] = niveaux
        if 'demande_paiement_participants' in data:
            updates['demande_paiement_participants'] = data['demande_paiement_participants']
        if 'prix_participation' in data:
            updates['prix_participation'] = int(data['prix_participation'])

        if not updates:
            return Response(
                {"detail": "Aucune modification spécifiée."},
                status=400
            )

        # Appliquer les modifications
        for key, value in updates.items():
            setattr(olympiade, key, value)
        olympiade.save()

        enregistrer_activite(
            user=request.user,
            action='olympiad_modified',
            description=f"Olympiade « {olympiade.titre} » modifiée",
            data={'olympiade': olympiade.titre, 'modifications': list(updates.keys())},
            objet_id=olympiade.id,
            objet_type='Olympiade',
        )

        return Response({
            "detail": "Olympiade modifiée avec succès.",
            "id": olympiade.id,
            "titre": olympiade.titre,
            "modifications": list(updates.keys()),
        }, status=200)

# views.py - Ajouter CadreDevoirsView

class CadreDevoirsView(APIView):
    """
    GET /api/devoirs/cadre/mes-devoirs/
    Retourne tous les devoirs créés par le cadre connecté.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=403
            )

        devoirs = Devoir.objects.filter(
            cree_par=profile
        ).order_by('-date_creation')

        data = []
        for d in devoirs:
            data.append({
                "id": d.id,
                "titre": d.titre,
                "description": d.description,
                "type_devoir": d.type_devoir,
                "matiere": d.matiere,
                "niveau": d.niveau,
                "date_debut": d.date_debut.isoformat(),
                "date_limite": d.date_limite.isoformat(),
                "est_publie": d.est_publie,
                "nb_questions": d.questions.count(),
                "note_sur": d.note_sur,
                "est_lie_olympiade": hasattr(d, 'olympiade_config') and d.olympiade_config is not None,
            })

        return Response(data)
    

# ---------------------------
# Liste des enseignants cadres (light)
# ---------------------------
@api_view(["GET"])
#@permission_classes([IsAuthenticated])
def liste_enseignants_cadres(request):
    qs = Profile.objects.filter(user_type="enseignant_cadre")
    data = EnseignantCadreLightSerializer(qs, many=True).data
    return Response(data, status=status.HTTP_200_OK)

# ---------------------------
# Liste des enseignants secondaires
# ---------------------------
@api_view(["GET"])
#@permission_classes([IsAuthenticated])
def liste_enseignants_secondaires(request):
    qs = Profile.objects.filter(user_type="enseignant")
    data = EnseignantSerializer(qs, many=True).data
    return Response(data, status=status.HTTP_200_OK)


@api_view(['GET'])
#@permission_classes([IsAuthenticated])
def liste_enseignants(request):
    qs = Profile.objects.filter(user_type__in=[
        'enseignant', 'enseignant_principal', 'enseignant_admin', 'enseignant_cadre'
    ])
    serializer = EnseignantSerializer(qs, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

# views.py - Ajouter AdminGeneralModifierEnseignantView

class AdminGeneralModifierEnseignantView(APIView):
    """
    PATCH /api/admin-general/enseignants/<profile_id>/modifier/
    Body: { "user_type": "enseignant_principal", "is_active": true/false }

    Modifie le type et/ou l'état d'activation d'un enseignant.
    Envoie un email de confirmation en cas de changement de type.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, profile_id):
        try:
            profile_admin = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile_admin.user_type != 'admin':
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=403
            )

        enseignant = get_object_or_404(Profile, pk=profile_id)

        # Vérifier que c'est bien un enseignant
        if enseignant.user_type not in ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']:
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant."},
                status=400
            )

        data = request.data
        ancien_type = enseignant.user_type
        ancien_actif = enseignant.is_active
        modifications = []

        # ── Changer le type ─────────────────────────────────────
        if 'user_type' in data:
            nouveau_type = data['user_type'].strip()
            types_valides = ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']
            if nouveau_type not in types_valides:
                return Response(
                    {"detail": f"Type invalide. Valeurs: {types_valides}"},
                    status=400
                )
            if nouveau_type != ancien_type:
                enseignant.user_type = nouveau_type
                modifications.append(f"Type: {ancien_type} → {nouveau_type}")
                
                # Envoyer un email de confirmation pour le changement de type
                try:
                    _envoyer_email_changement_type(enseignant, ancien_type, nouveau_type)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"Erreur envoi email changement type: {e}")

        # ── Activer/Désactiver ─────────────────────────────────
        if 'is_active' in data:
            nouvel_actif = bool(data['is_active'])
            if nouvel_actif != ancien_actif:
                enseignant.is_active = nouvel_actif
                if nouvel_actif:
                    modifications.append("Compte activé")
                    try:
                        _envoyer_email_activation_enseignant(enseignant)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).error(f"Erreur envoi email activation: {e}")
                else:
                    modifications.append("Compte désactivé")

        if not modifications:
            return Response(
                {"detail": "Aucune modification spécifiée."},
                status=400
            )

        enseignant.save(update_fields=['user_type', 'is_active'])

        # Enregistrer dans l'historique
        enregistrer_activite(
            user=request.user,
            action='teacher_modified',
            description=f"Enseignant {_nom_profil(enseignant)} modifié : {', '.join(modifications)}",
            data={
                'enseignant_id': enseignant.id,
                'enseignant_nom': _nom_profil(enseignant),
                'modifications': modifications,
                'ancien_type': ancien_type,
                'nouveau_type': enseignant.user_type,
                'ancien_actif': ancien_actif,
                'nouveau_actif': enseignant.is_active,
            },
            objet_id=enseignant.id,
            objet_type='Profile',
        )

        return Response({
            "detail": "Enseignant modifié avec succès.",
            "enseignant_id": enseignant.id,
            "nom": _nom_profil(enseignant),
            "user_type": enseignant.user_type,
            "is_active": enseignant.is_active,
            "modifications": modifications,
        }, status=200)


def _envoyer_email_changement_type(profile, ancien_type, nouveau_type):
    """Envoie un email de confirmation pour le changement de type."""
    user = profile.user
    nom = f"{user.first_name} {user.last_name}".strip() or user.username

    labels = {
        'enseignant': 'Enseignant',
        'enseignant_principal': 'Enseignant Principal',
        'enseignant_cadre': 'Enseignant Cadre',
        'enseignant_admin': 'Enseignant Administrateur',
    }
    ancien_label = labels.get(ancien_type, ancien_type)
    nouveau_label = labels.get(nouveau_type, nouveau_type)

    sujet = "📝 Votre grade d'enseignant a été modifié"

    message_texte = f"""
Bonjour {nom},

L'administrateur général a modifié votre grade d'enseignant sur Yéki.

Ancien grade : {ancien_label}
Nouveau grade : {nouveau_label}

Ce changement vous permet d'accéder à de nouvelles fonctionnalités sur la plateforme.

— L'équipe Yéki
"""

    message_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
    .container {{ max-width: 480px; margin: 40px auto; background: white;
                  border-radius: 16px; overflow: hidden;
                  box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #2884A9, #2A657D);
               padding: 32px 24px; text-align: center; }}
    .header h1 {{ color: white; margin: 0; font-size: 22px; }}
    .header p  {{ color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 14px; }}
    .body   {{ padding: 32px 24px; text-align: center; }}
    .greeting {{ color: #1E293B; font-size: 15px; margin-bottom: 24px; }}
    .grade-box {{ background: #F1F5F9; border-radius: 12px; padding: 20px; margin: 0 auto;
                  display: inline-block; min-width: 200px; text-align: left; }}
    .grade-box div {{ padding: 4px 0; color: #1E293B; }}
    .grade-box strong {{ color: #2884A9; }}
    .note {{ color: #94A3B8; font-size: 11px; margin-top: 28px;
             border-top: 1px solid #E2E8F0; padding-top: 16px; }}
    .footer {{ background: #F8FAFC; padding: 16px; text-align: center;
               color: #94A3B8; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>📝 Grade modifié</h1>
      <p>Votre compte enseignant a été mis à jour</p>
    </div>
    <div class="body">
      <p class="greeting">Bonjour <strong>{nom}</strong>,<br>
      L'administrateur général a modifié votre grade d'enseignant sur Yéki.</p>

      <div class="grade-box">
        <div><strong>Ancien grade :</strong> {ancien_label}</div>
        <div><strong>Nouveau grade :</strong> {nouveau_label}</div>
      </div>

      <p class="note">
        Ce changement vous permet d'accéder à de nouvelles fonctionnalités sur la plateforme.
      </p>
    </div>
    <div class="footer">© Yeki — Plateforme éducative</div>
  </div>
</body>
</html>
"""

    send_mail(
        subject=sujet,
        message=message_texte,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@yeki.app'),
        recipient_list=[user.email],
        html_message=message_html,
        fail_silently=False,
    )

# views.py - Ajouter AdminGeneralSearchEnseignantsView

class AdminGeneralSearchEnseignantsView(APIView):
    """
    GET /api/admin-general/enseignants/search/
    Paramètres query :
    - q: texte de recherche (nom, email, username)
    - user_type: enseignant, enseignant_principal, enseignant_cadre, enseignant_admin
    - is_active: true/false
    - parcours_id: filtrer par parcours (admin du parcours)
    - departement_id: filtrer par département (cadre)
    - cours_id: filtrer par cours (enseignant principal)
    - date_from, date_to: filtrer par date de création
    
    Retourne la liste des enseignants filtrés.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'admin':
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=403
            )

        # Base queryset
        qs = Profile.objects.filter(
            user_type__in=['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']
        ).select_related('user').order_by('-user__date_joined')

        # ── Filtres ──────────────────────────────────────────────
        q = request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(user__username__icontains=q) |
                Q(user__email__icontains=q) |
                Q(user__first_name__icontains=q) |
                Q(user__last_name__icontains=q) |
                Q(bio__icontains=q)
            )

        user_type = request.query_params.get('user_type', '').strip()
        if user_type and user_type in ['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']:
            qs = qs.filter(user_type=user_type)

        is_active = request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == 'true')

        parcours_id = request.query_params.get('parcours_id')
        if parcours_id:
            qs = qs.filter(parcours_admin__id=parcours_id)

        departement_id = request.query_params.get('departement_id')
        if departement_id:
            qs = qs.filter(departements_cadre__id=departement_id)

        cours_id = request.query_params.get('cours_id')
        if cours_id:
            qs = qs.filter(
                Q(cours_principal__id=cours_id) |
                Q(cours_secondaires__id=cours_id)
            )

        date_from = request.query_params.get('date_from')
        if date_from:
            try:
                from datetime import datetime
                qs = qs.filter(user__date_joined__date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
            except ValueError:
                pass

        date_to = request.query_params.get('date_to')
        if date_to:
            try:
                from datetime import datetime
                qs = qs.filter(user__date_joined__date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())
            except ValueError:
                pass

        # ── Pagination ───────────────────────────────────────────
        try:
            limit = min(int(request.query_params.get('limit', 50)), 200)
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = int(request.query_params.get('offset', 0))
        except (TypeError, ValueError):
            offset = 0

        total = qs.count()
        qs = qs[offset:offset+limit]

        data = []
        for e in qs:
            data.append({
                "id": e.id,
                "username": e.user.username,
                "email": e.user.email,
                "nom": _nom_profil(e),
                "user_type": e.user_type,
                "is_active": e.is_active,
                "date_joined": e.user.date_joined.isoformat(),
                "bio": e.bio or '',
                "phone": e.phone or '',
                "avatar": request.build_absolute_uri(e.avatar.url) if e.avatar else None,
            })

        return Response({
            "total": total,
            "offset": offset,
            "limit": limit,
            "results": data,
        }, status=200)

# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Dashboard (VERSION ULTIME CORRIGÉE)
# GET /api/admin-general/dashboard/
# ───────────────────────────────────────────────────────────────────────────

class AdminGeneralDashboardView(APIView):
    """
    GET /api/admin-general/dashboard/
    Dashboard complet pour l'administrateur général avec :
    - Stats globales
    - Liste des parcours
    - Liste des départements
    - Top enseignants
    - Liste complète des enseignants (avec filtres)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'admin':
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=403
            )

        # Parcours
        parcours_qs = Parcours.objects.prefetch_related(
            'departements__cours', 'admin__user'
        ).all()
        
        parcours_data = []
        for p in parcours_qs:
            depts = p.departements.all()
            nb_depts = depts.count()
            nb_app = 0
            nb_cours = 0
            
            for d in depts:
                for c in d.cours.all():
                    nb_app += c.nb_apprenants
                    nb_cours += 1
            
            admin_data = None
            if p.admin:
                admin_data = {
                    "id": p.admin.id,
                    "nom": _nom_profil(p.admin),
                    "username": p.admin.user.username,
                    "email": p.admin.user.email,
                    "user_type": p.admin.user_type,
                }
            
            parcours_data.append({
                "id": p.id,
                "nom": p.nom,
                "type_parcours": p.type_parcours,
                "nb_departements": nb_depts,
                "nb_apprenants": nb_app,
                "nb_cours": nb_cours,
                "taux_moyen": 0,
                "enseignant_admin": admin_data,
            })

        # Départements
        departements_qs = Departement.objects.select_related(
            'parcours', 'cadre__user'
        ).prefetch_related('cours').all()
        
        depts_data = []
        for d in departements_qs:
            nb_cours = d.cours.count()
            nb_app = 0
            for c in d.cours.all():
                nb_app += c.nb_apprenants
            
            depts_data.append({
                "id": d.id,
                "nom": d.nom,
                "parcours": d.parcours.nom if d.parcours else "",
                "parcours_id": d.parcours.id if d.parcours else None,
                "nb_cours": nb_cours,
                "nb_apprenants": nb_app,
                "taux_moyen": 0,
                "cadre": {
                    "id": d.cadre.id,
                    "nom": _nom_profil(d.cadre),
                } if d.cadre else None,
            })

        # Statistiques globales
        stats = {
            "nb_parcours": Parcours.objects.count(),
            "nb_departements": Departement.objects.count(),
            "nb_cours": Cours.objects.count(),
            "nb_apprenants": Profile.objects.filter(user_type='apprenant').count(),
            "nb_enseignants": Profile.objects.filter(
                user_type__in=[
                    'enseignant_admin', 'enseignant_cadre',
                    'enseignant_principal', 'enseignant'
                ]
            ).count(),
            "nb_lecons": Lecon.objects.count(),
        }

        from django.db.models import Avg
        top_enseignants = []
        enseignants_top = Profile.objects.filter(
            user_type__in=['enseignant_principal', 'enseignant']
        ).annotate(
            score_moyen=Avg('cours_principal__exercices__evaluationexercice__score')
        ).order_by('-score_moyen')[:10]
        
        for e in enseignants_top:
            if e.score_moyen:
                top_enseignants.append({
                    "id": e.id,
                    "nom": _nom_profil(e),
                    "role": e.user_type,
                    "score": round(e.score_moyen / 20 * 20, 1) if e.score_moyen else 0,
                })

        # ✅ Liste complète des enseignants (tous types, triés par date de création)
        enseignants = Profile.objects.filter(
            user_type__in=['enseignant', 'enseignant_principal', 'enseignant_cadre', 'enseignant_admin']
        ).select_related('user').order_by('-user__date_joined')

        enseignants_data = []
        for e in enseignants:
            enseignants_data.append({
                "id": e.id,
                "username": e.user.username,
                "email": e.user.email,
                "nom": _nom_profil(e),
                "user_type": e.user_type,
                "is_active": e.is_active,
                "date_joined": e.user.date_joined.isoformat(),
                "bio": e.bio or '',
                "phone": e.phone or '',
                "avatar": request.build_absolute_uri(e.avatar.url) if e.avatar else None,
            })

        nom_complet = _nom_profil(profile)

        return Response({
            "nom": nom_complet,
            "stats": stats,
            "parcours": parcours_data,
            "departements": depts_data,
            "top_enseignants": top_enseignants,
            "enseignants": enseignants_data,
        }, status=200)
    

# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Créer un parcours
# POST /api/parcours/creer/
# Body: { "nom": "Licence Informatique", "description": "..." }
# ───────────────────────────────────────────────────────────────────────────
class CreerParcoursView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'admin':
            return Response(
                {"detail": "Acces reserve a l'administrateur general."},
                status=status.HTTP_403_FORBIDDEN
            )

        nom = request.data.get('nom', '').strip()
        if not nom:
            return Response(
                {"detail": "Le nom du parcours est obligatoire."},
                status=status.HTTP_400_BAD_REQUEST
            )

        type_parcours = request.data.get('type_parcours', 'autre')
        valid_types = ['cursus', 'prepa', 'formation', 'autre']
        if type_parcours not in valid_types:
            type_parcours = 'autre'

        parcours = Parcours.objects.create(
            nom=nom,
            type_parcours=type_parcours,
            description=request.data.get('description', '').strip(),
        )
        return Response(
            {
                "id": parcours.id,
                "nom": parcours.nom,
                "type_parcours": parcours.type_parcours,
                "description": parcours.description,
            },
            status=status.HTTP_201_CREATED
        )


# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Nommer / changer l'enseignant admin d'un parcours
# PATCH /api/parcours/<parcours_id>/nommer-admin/
# Body: { "enseignant_admin_id": 5 }
# ───────────────────────────────────────────────────────────────────────────
class NommerAdminParcoursView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, parcours_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'admin':
            return Response(
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN
            )

        parcours = get_object_or_404(Parcours, pk=parcours_id)

        enseignant_id = request.data.get('enseignant_admin_id')
        if not enseignant_id:
            return Response(
                {"detail": "enseignant_admin_id est requis."},
                status=status.HTTP_400_BAD_REQUEST
            )

        enseignant = get_object_or_404(Profile, pk=enseignant_id)
        if enseignant.user_type != 'enseignant_admin':
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant administrateur."},
                status=status.HTTP_400_BAD_REQUEST
            )

        parcours.admin = enseignant
        parcours.save()
        return Response(
            {"detail": "Enseignant administrateur mis à jour avec succès."},
            status=status.HTTP_200_OK
        )


# ───────────────────────────────────────────────────────────────────────────
# LISTE ENSEIGNANTS PAR RÔLE
# GET /api/enseignants/liste/?role=admin   → enseignant_admin
# GET /api/enseignants/liste/?role=cadre   → enseignant_cadre
# GET /api/enseignants/liste/?role=principal → enseignant_principal
# ───────────────────────────────────────────────────────────────────────────
class ListeEnseignantsParRoleView(APIView):
    permission_classes = [IsAuthenticated]

    ROLE_MAP = {
        'admin':      'enseignant_admin',
        'cadre':      'enseignant_cadre',
        'principal':  'enseignant_principal',
        'enseignant': 'enseignant',
    }

    def get(self, request):
        role_param = request.query_params.get('role', '')
        user_type = self.ROLE_MAP.get(role_param)

        if not user_type:
            return Response(
                {"detail": f"Rôle invalide. Valeurs acceptées : {list(self.ROLE_MAP.keys())}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        profiles = Profile.objects.filter(
            user_type=user_type, is_active=True
        ).select_related('user')

        data = [
            {
                "id": p.id,
                "nom": f"{p.user.first_name} {p.user.last_name}".strip()
                      or p.user.username,
                "username": p.user.username,
                "email": p.user.email,
                "user_type": p.user_type,
            }
            for p in profiles
        ]
        return Response(data, status=status.HTTP_200_OK)

# ───────────────────────────────────────────────────────────────────────────
# ENSEIGNANT ADMIN — Dashboard (VERSION CORRIGÉE)
# GET /api/enseignant/admin/dashboard/
# ───────────────────────────────────────────────────────────────────────────

class EnseignantAdminDashboardView(APIView):
    """
    GET /api/enseignant/admin/dashboard/
    
    Dashboard complet pour l'enseignant_admin incluant :
    - Départements du parcours
    - Cadres du parcours
    - Départements (sans validation)
    - Olympiades en attente de validation (prix_global = 0)
    - Statistiques globales
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_admin':
            return Response(
                {"detail": "Accès réservé aux enseignants administrateurs."},
                status=status.HTTP_403_FORBIDDEN
            )

        # ── Récupérer le parcours de l'admin ────────────────────
        try:
            parcours_qs = Parcours.objects.prefetch_related(
                'departements__cours',
                'departements__cadre__user',
            ).get(admin=profile)
        except Parcours.DoesNotExist:
            return Response({
                "nom": _nom_profil(profile),
                "stats": {},
                "departements": [],
                "cadres": [],
                "olympiades_en_attente": [],
                "nom_parcours": "",
                "id_parcours": 0,
                "type_parcours": "",
            })

        # ── Départements ─────────────────────────────────────────
        departements_data = []
        cadres_dict = {}

        for dept in parcours_qs.departements.all():
            nb_cours = dept.cours.count()
            nb_app = sum(c.nb_apprenants for c in dept.cours.all())

            cadre_data = None
            if dept.cadre:
                cadre_data = {
                    "id": dept.cadre.id,
                    "nom": _nom_profil(dept.cadre),
                    "email": dept.cadre.user.email,
                }
                if dept.cadre.id not in cadres_dict:
                    cadres_dict[dept.cadre.id] = {
                        "id": dept.cadre.id,
                        "nom": cadre_data["nom"],
                        "username": dept.cadre.user.username,
                        "email": dept.cadre.user.email,
                        "nb_cours": nb_cours,
                        "nb_apprenants": nb_app,
                    }
            
            dept_info = {
                "id": dept.id,
                "nom": dept.nom,
                "parcours": parcours_qs.nom,
                "parcours_id": parcours_qs.id,
                "type_dept": dept.type_departement,
                "description": dept.description,
                "nb_cours": nb_cours,
                "nb_apprenants": nb_app,
                "nb_inscrits": nb_app,  # Alias pour le frontend
                "prix": dept.prix,
                "prix_presentiel": dept.prix_presentiel,
                "couleur": dept.couleur,
                "taux_moyen": 0,
                "cadre": cadre_data,
                "est_actif": dept.est_actif,
                "acces_restreint": dept.acces_restreint,
                # Champs spécifiques au type
                "est_prepa_concours": dept.est_prepa_concours,
                "est_formation_metier": dept.est_formation_metier,
                "est_formation_classique": dept.est_formation_classique,
                "nom_concours": dept.nom_concours,
                "organisme_concours": dept.organisme_concours,
                "date_limite_inscription": dept.date_limite_inscription,
                "date_examen": dept.date_examen,
                "duree_formation": dept.duree_formation,
                "mode": dept.mode,
                "certificat_delivre": dept.certificat_delivre,
                "domaine": dept.domaine,
                "ville": dept.ville,
                "est_certifiante": dept.est_certifiante,
                # ✅ Ajout du niveau_formation
                "niveau_formation": dept.niveau_formation if hasattr(dept, 'niveau_formation') else None,
            }
            departements_data.append(dept_info)

        # ── Olympiades en attente (prix_global = 0, non publiées) ────
        olympiades_en_attente = []
        
        olympiades_attente_qs = Olympiade.objects.filter(
            organisateur__departements_cadre__parcours=parcours_qs,
            prix_global=0,
            devoir__est_publie=False,
        ).distinct().select_related('organisateur__user', 'devoir')

        for o in olympiades_attente_qs:
            statut = "refuse" if o.est_refusee else "attente"
            
            olympiades_en_attente.append({
                "id": o.id,
                "titre": o.titre,
                "matiere": o.matiere,
                "niveau": o.niveau,
                "edition": o.edition,
                "statut_validation": statut,
                "motif_refus": o.motif_refus if o.est_refusee else "",
                "cadre": {
                    "id": o.organisateur.id,
                    "nom": _nom_profil(o.organisateur),
                } if o.organisateur else None,
                "date_creation": o.created_at.isoformat() if hasattr(o, 'created_at') else None,
                "niveaux_accessibles": o.get_niveaux_accessibles_list(),
                "prix_global": o.prix_global,
                "est_validee": o.est_validee,
                "est_refusee": o.est_refusee,
            })

        # ── Stats globales ───────────────────────────────────────
        stats = {
            "nb_departements": len(departements_data),
            "nb_cours": sum(d["nb_cours"] for d in departements_data),
            "nb_apprenants": sum(d["nb_apprenants"] for d in departements_data),
            "nb_enseignants": len(cadres_dict),
            "nb_olympiades_attente": len(olympiades_en_attente),
        }

        return Response({
            "nom": _nom_profil(profile),
            "stats": stats,
            "nom_parcours": parcours_qs.nom,
            "id_parcours": parcours_qs.id,
            "type_parcours": parcours_qs.type_parcours,
            "departements": departements_data,
            "cadres": list(cadres_dict.values()),
            "olympiades_en_attente": olympiades_en_attente,
        })

# ───────────────────────────────────────────────────────────────────────────
# ENSEIGNANT ADMIN — Créer un département
# POST /api/departements/creer/
# Body: { "nom": "Mathématiques", "description": "...", "parcours_id": 1 }
#   → parcours_id est OPTIONNEL si l'enseignant admin n'a qu'un seul parcours
# ───────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# HELPER : sérialise un Departement avec tous ses champs enrichis
# ─────────────────────────────────────────────────────────────────────────────
# views.py - Correction de _serialise_departement_detail

def _serialise_departement_detail(dept, prog_map=None, include_cours=False, user=None):
    """Sérialise un Departement avec tous les champs enrichis selon son type."""

    cadre_data = None
    if dept.cadre:
        cadre_data = {
            "id":    dept.cadre.id,
            "nom":   _nom_profil(dept.cadre),
            "email": dept.cadre.user.email,
        }

    image_url = None
    if dept.image:
        try:
            image_url = settings.MEDIA_URL + str(dept.image)
        except Exception:
            image_url = None

    base = {
        "id":              dept.id,
        "nom":             dept.nom,
        "description":     dept.description,
        "image_url":       image_url,
        "couleur":         dept.couleur,
        "prix":            dept.prix,
        "prix_presentiel": dept.prix_presentiel,  # ✅ Ajout
        "type":            dept.type_departement,
        "parcours_id":     dept.parcours_id,
        "parcours_nom":    dept.parcours.nom if dept.parcours else '',
        "parcours_type":   dept.parcours.type_parcours if dept.parcours else '',
        "cadre":           cadre_data,
        "created_at":      dept.created_at.isoformat() if dept.created_at else None,
        "acces_restreint": dept.acces_restreint,
        "est_actif":       dept.est_actif,
    }

    # Champs prépa concours
    if dept.est_prepa_concours:
        base.update({
            "est_prepa_concours":      True,
            "nom_concours":            dept.nom_concours,
            "organisme_concours":      dept.organisme_concours,
            "date_limite_inscription": dept.date_limite_inscription.isoformat() if dept.date_limite_inscription else None,
            "date_examen":             dept.date_examen.isoformat() if dept.date_examen else None,
            "arrete_ministeriel":      dept.arrete_ministeriel,
            "niveaux_cibles":          dept.niveaux_cibles,
            "places_disponibles":      dept.places_disponibles,
            "debouches":               dept.debouches,
        })
    else:
        base["est_prepa_concours"] = False

    # Champs formation
    if dept.est_formation_metier or dept.est_formation_classique:
        base.update({
            "est_formation_metier":    dept.est_formation_metier,
            "est_formation_classique": dept.est_formation_classique,
            "duree_formation":         dept.duree_formation,
            "mode":                    dept.mode,
            "certificat_delivre":      dept.certificat_delivre,
            "prerequis":               dept.prerequis,
            "objectifs":               dept.objectifs,
            "domaine":                 dept.domaine,
            "ville":                   dept.ville,
            "est_certifiante":         dept.est_certifiante,
        })
    else:
        base["est_formation_metier"] = False
        base["est_formation_classique"] = False

    if include_cours:
        cours_qs = Cours.objects.filter(departement=dept).select_related('enseignant_principal__user')
        pm = prog_map or (_progression_cours(user, cours_qs) if user else {})
        base["cours"] = [_serialise_cours(c, pm) for c in cours_qs]
        base["nb_cours"] = cours_qs.count()
        progs = [_serialise_cours(c, pm)['progression'] for c in cours_qs]
        base["progression_moyenne"] = round(sum(progs)/len(progs), 1) if progs else 0.0
    else:
        nb = Cours.objects.filter(departement=dept).count()
        base["nb_cours"] = nb

    return base


# ───────────────────────────────────────────────────────────────────────────
# ENSEIGNANT ADMIN — Nommer / changer le cadre d'un département
# PATCH /api/departements/<departement_id>/changer-cadre/
# Body: { "cadre_id": 7 }
# ───────────────────────────────────────────────────────────────────────────
class ChangerCadreDepartementView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_admin':
            return Response(
                {"detail": "Accès réservé aux enseignants administrateurs."},
                status=status.HTTP_403_FORBIDDEN
            )

        departement = get_object_or_404(Departement, pk=departement_id)

        # SÉCURITÉ : vérifier que ce département appartient à un parcours géré
        if departement.parcours.admin != profile:
            return Response(
                {"detail": "Ce département n'appartient pas à votre parcours."},
                status=status.HTTP_403_FORBIDDEN
            )

        cadre_id = request.data.get('cadre_id')
        if not cadre_id:
            return Response(
                {"detail": "cadre_id est requis."},
                status=status.HTTP_400_BAD_REQUEST
            )

        cadre = get_object_or_404(Profile, pk=cadre_id)
        if cadre.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant cadre."},
                status=status.HTTP_400_BAD_REQUEST
            )

        departement.cadre = cadre
        departement.save()
        enregistrer_activite(
       user=request.user,
       action='cadre_assigned',
       description=f"{cadre.user.get_full_name() or cadre.user.username} nommé cadre du département « {departement.nom} »",
       data={
           'cadre':        cadre.user.get_full_name() or cadre.user.username,
           'departement':  departement.nom,
           'parcours':     departement.parcours.nom if departement.parcours else '',
       },
       objet_id=departement.id,
       objet_type='Departement',
   )
        return Response(
            {"detail": "Enseignant cadre mis à jour avec succès."},
            status=status.HTTP_200_OK
        )


# ───────────────────────────────────────────────────────────────────────────
# Cours d'un département
# GET /api/departements/<departement_id>/cours/
# ───────────────────────────────────────────────────────────────────────────
class CoursParDepartementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, departement_id):
        departement = get_object_or_404(Departement, pk=departement_id)
        cours_qs = Cours.objects.filter(departement=departement).select_related(
            'enseignant_principal__user'
        )
        data = [
            {
                "id": c.id,
                "titre": c.titre,
                "niveau": c.niveau,
                "nb_apprenants": c.nb_apprenants,
                "taux_completion": 0,
                "color_code": c.color_code,
                "icon_name": c.icon_name,
            }
            for c in cours_qs
        ]
        return Response(data, status=status.HTTP_200_OK)



# ---------------------------
# Départements par parcours
# ---------------------------
@api_view(["GET"])
#@permission_classes([IsAuthenticated])
def departements_par_parcours(request, parcours_id):
    parcours = get_object_or_404(Parcours, pk=parcours_id)
    deps = Departement.objects.filter(parcours=parcours).select_related("cadre")
    data = DepartementSerializer(deps, many=True).data
    return Response(data, status=status.HTTP_200_OK)


# 1. Créer la vue pour les demandes d'accès
class DemandeAccesFormationView(APIView):
    """
    POST /api/departements/<departement_id>/demander-acces/
    L'apprenant demande l'accès à une formation à accès restreint.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)
        
        if profile.user_type != 'apprenant':
            return Response(
                {"detail": "Seuls les apprenants peuvent demander l'accès."},
                status=403
            )
        
        departement = get_object_or_404(Departement, pk=departement_id)
        
        if not departement.acces_restreint:
            return Response(
                {"detail": "Cette formation est en accès libre."},
                status=400
            )
        
        message = request.data.get('message', '').strip()
        
        demande, created = DemandeAccesFormation.objects.get_or_create(
            apprenant=request.user,
            departement=departement,
            defaults={'message': message}
        )
        
        if not created:
            if demande.statut == 'en_attente':
                return Response(
                    {"detail": "Votre demande est déjà en attente de traitement."},
                    status=400
                )
            elif demande.statut == 'acceptee':
                return Response(
                    {"detail": "Vous avez déjà accès à cette formation."},
                    status=400
                )
            elif demande.statut == 'refusee':
                # Permettre de refaire une demande après refus
                demande.statut = 'en_attente'
                demande.message = message or demande.message
                demande.traite_le = None
                demande.reponse_cadre = ''
                demande.save()
                return Response({
                    "detail": "Votre nouvelle demande a été envoyée.",
                    "statut": "en_attente"
                })
        
        return Response({
            "detail": "Votre demande d'accès a été envoyée au cadre.",
            "statut": "en_attente"
        }, status=201)


# 2. Vue pour le cadre - Gérer les demandes d'accès
class GererDemandeAccesView(APIView):
    """
    POST /api/departements/<departement_id>/demandes/<demande_id>/traiter/
    Body: { "action": "accepter" | "refuser", "reponse": "..." }
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, departement_id, demande_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)
        
        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Seuls les enseignants cadres peuvent traiter les demandes."},
                status=403
            )
        
        departement = get_object_or_404(Departement, pk=departement_id, cadre=profile)
        demande = get_object_or_404(DemandeAccesFormation, pk=demande_id, departement=departement)
        
        action = request.data.get('action', '').lower()
        reponse = request.data.get('reponse', '').strip()
        
        if action not in ['accepter', 'refuser']:
            return Response(
                {"detail": "L'action doit être 'accepter' ou 'refuser'."},
                status=400
            )
        
        if action == 'accepter':
            demande.statut = 'acceptee'
            departement.apprenants_autorises.add(demande.apprenant)
        else:
            demande.statut = 'refusee'
        
        demande.reponse_cadre = reponse
        demande.traite_le = timezone.now()
        demande.save()
        
        # Optionnel: envoyer une notification à l'apprenant
        # Notification.objects.create(...)
        
        return Response({
            "detail": f"Demande {action}e avec succès.",
            "statut": demande.statut
        }, status=200)


# 3. Vue pour le cadre - Lister les demandes d'accès
class DemandesAccesDepartementView(APIView):
    """
    GET /api/departements/<departement_id>/demandes/
    Retourne les demandes d'accès pour un département.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)
        
        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=403
            )
        
        departement = get_object_or_404(Departement, pk=departement_id, cadre=profile)
        
        statut = request.query_params.get('statut', 'en_attente')
        if statut not in ['en_attente', 'acceptee', 'refusee']:
            statut = 'en_attente'
        
        demandes = DemandeAccesFormation.objects.filter(
            departement=departement,
            statut=statut
        ).select_related('apprenant').order_by('-cree_le')
        
        data = [{
            'id': d.id,
            'apprenant_id': d.apprenant.id,
            'apprenant_nom': f"{d.apprenant.first_name} {d.apprenant.last_name}".strip() or d.apprenant.username,
            'apprenant_username': d.apprenant.username,
            'apprenant_email': d.apprenant.email,
            'message': d.message,
            'reponse_cadre': d.reponse_cadre,
            'cree_le': d.cree_le.isoformat(),
            'traite_le': d.traite_le.isoformat() if d.traite_le else None,
        } for d in demandes]
        
        return Response(data, status=200)


class CreerDepartementView(APIView):
    """
    POST /api/departements/creer/
    Crée un département enrichi selon le type du parcours parent.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_admin':
            return Response(
                {"detail": "Accès réservé aux enseignants administrateurs."},
                status=status.HTTP_403_FORBIDDEN
            )

        nom = request.data.get('nom', '').strip()
        if not nom:
            return Response(
                {"detail": "Le nom du département est obligatoire."},
                status=status.HTTP_400_BAD_REQUEST
            )

        parcours_id = request.data.get('parcours_id')
        if parcours_id:
            parcours = get_object_or_404(Parcours, pk=parcours_id, admin=profile)
        else:
            parcours_qs = Parcours.objects.filter(admin=profile)
            if not parcours_qs.exists():
                return Response({"detail": "Aucun parcours ne vous est assigné."}, status=403)
            if parcours_qs.count() > 1:
                return Response({"detail": "Spécifier parcours_id."}, status=400)
            parcours = parcours_qs.first()

        def _b(key, default=False):
            v = request.data.get(key, default)
            if isinstance(v, str):
                return v.lower() in ('true', '1', 'yes')
            return bool(v)

        def _i(key, default=0):
            try:
                return int(request.data.get(key, default) or default)
            except (ValueError, TypeError):
                return default

        def _s(key, default=''):
            v = request.data.get(key, default)
            return v if v else default

        # Récupérer les niveaux accessibles
        niveaux_accessibles = request.data.get('niveaux_accessibles', [])
        if isinstance(niveaux_accessibles, str):
            try:
                niveaux_accessibles = json.loads(niveaux_accessibles)
            except:
                niveaux_accessibles = [n.strip() for n in niveaux_accessibles.split(',') if n.strip()]
        elif not isinstance(niveaux_accessibles, list):
            niveaux_accessibles = []

        # === CONSTRUCTION DES CHAMPS DE BASE ===
        prix = _i('prix')
        prix_presentiel = _i('prix_presentiel')
        type_parc = parcours.type_parcours
        
        if type_parc == 'prepa':
            est_prepa_concours = True
            est_formation_metier = False
            est_formation_classique = False
        elif type_parc == 'formation':
            est_prepa_concours = False
            est_formation_metier = _b('est_formation_metier')
            est_formation_classique = _b('est_formation_classique')
            if not est_formation_metier and not est_formation_classique:
                return Response({
                    "detail": "Veuillez sélectionner au moins un type de formation (Métier ou Classique)."
                }, status=400)
        else:
            est_prepa_concours = False
            est_formation_metier = False
            est_formation_classique = False
        
        kwargs = {
            'nom': nom,
            'parcours': parcours,
            'description': _s('description'),
            'couleur': '#2884A0',  # Couleur par défaut, retirée du formulaire
            'prix': prix,
            'prix_presentiel': prix_presentiel,
            'est_actif': True,
            'mode': _s('mode', 'hybride'),
            'acces_restreint': _b('acces_restreint'),
            'niveaux_accessibles': ','.join(niveaux_accessibles) if niveaux_accessibles else '',
            'est_prepa_concours': est_prepa_concours,
            'est_formation_metier': est_formation_metier,
            'est_formation_classique': est_formation_classique,
        }

        # ✅ Ajout du champ niveau_formation pour les formations métier
        if type_parc == 'formation' and est_formation_metier:
            niveau_formation = request.data.get('niveau_formation', 'debutant')
            if niveau_formation not in ['debutant', 'intermediaire', 'avance']:
                niveau_formation = 'debutant'
            kwargs['niveau_formation'] = niveau_formation

        if request.FILES.get('image'):
            kwargs['image'] = request.FILES['image']

        # === PARCOURS PRÉPA CONCOURS ===
        if type_parc == 'prepa':
            kwargs.update({
                'nom_concours': _s('nom_concours'),
                'organisme_concours': _s('organisme_concours'),
                'date_limite_inscription': request.data.get('date_limite_inscription') or None,
                'date_examen': request.data.get('date_examen') or None,
                'arrete_ministeriel': _s('arrete_ministeriel'),
                'places_disponibles': _i('places_disponibles') or None,
                'debouches': _s('debouches'),
            })

        # === PARCOURS FORMATION ===
        elif type_parc == 'formation':
            kwargs.update({
                'duree_formation': _s('duree_formation'),
                'mode': _s('mode', 'hybride'),
                'certificat_delivre': _s('certificat_delivre'),
                'prerequis': _s('prerequis'),
                'objectifs': _s('objectifs'),
                'domaine': _s('domaine'),
                'ville': _s('ville'),
                'est_certifiante': _b('est_certifiante'),
            })

        # === CRÉATION DU DÉPARTEMENT ===
        departement = Departement.objects.create(**kwargs)

        enregistrer_activite(
            user=request.user,
            action='department_created',
            description=f"Département {departement.nom} créé dans {parcours.nom}",
            data={
                'departement': departement.nom,
                'parcours': parcours.nom,
                'type': type_parc,
                'prix': kwargs.get('prix', 0),
            },
            objet_id=departement.id,
            objet_type='Departement',
        )

        return Response(
            DepartementSerializer(departement, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )
    

# views.py - CORRECTION de AdminUpdateDepartementView

class AdminUpdateDepartementView(APIView):
    """
    PATCH /api/admin/departements/<pk>/update/
    Permet à l'enseignant admin de modifier un département.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, pk):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_admin':
            return Response(
                {"detail": "Accès réservé aux enseignants administrateurs."},
                status=403
            )

        departement = get_object_or_404(Departement, pk=pk)
        
        # Vérifier que le département appartient au parcours de l'admin
        if departement.parcours.admin != profile:
            return Response(
                {"detail": "Ce département n'appartient pas à votre parcours."},
                status=403
            )

        data = request.data.copy()
        
        # ── Validation et nettoyage des données ──────────────────
        
        # Gérer les niveaux accessibles
        if 'niveaux_accessibles' in data:
            niveaux = data.get('niveaux_accessibles', [])
            if isinstance(niveaux, str):
                try:
                    niveaux = json.loads(niveaux)
                except:
                    niveaux = [n.strip() for n in niveaux.split(',') if n.strip()]
            elif not isinstance(niveaux, list):
                niveaux = []
            # Le serializer attend une string, on convertit
            data['niveaux_accessibles'] = ','.join(niveaux) if niveaux else ''

        # Supprimer les champs qui ne sont pas dans le serializer
        # Ces champs existent dans le modèle mais pas dans le serializer
        champs_a_supprimer = ['couleur', 'created_at', 'image_url', 'type']
        for champ in champs_a_supprimer:
            if champ in data:
                data.pop(champ)

        # Si le type de parcours est 'formation', valider les champs spécifiques
        if departement.parcours.type_parcours == 'formation':
            # Si est_formation_metier ou est_formation_classique sont présents
            if 'est_formation_metier' not in data and 'est_formation_classique' not in data:
                # Conserver les valeurs existantes
                pass
            else:
                est_metier = data.get('est_formation_metier', departement.est_formation_metier)
                est_classique = data.get('est_formation_classique', departement.est_formation_classique)
                if not est_metier and not est_classique:
                    return Response({
                        "detail": "Veuillez sélectionner au moins un type de formation (Métier ou Classique)"
                    }, status=400)

        # ── Utiliser le serializer ────────────────────────────────
        serializer = DepartementUpdateSerializer(
            departement, 
            data=data, 
            partial=True,
            context={'request': request}
        )
        
        if serializer.is_valid():
            updated = serializer.save()
            enregistrer_activite(
                user=request.user,
                action='department_modified',
                description=f"Département {updated.nom} modifié",
                objet_id=updated.id,
                objet_type='Departement',
            )
            return Response(
                DepartementSerializer(updated, context={'request': request}).data,
                status=200
            )
        
        # Retourner les erreurs détaillées pour debug
        return Response({
            'detail': 'Erreur de validation',
            'errors': serializer.errors
        }, status=400)


class CadreOlympiadesView(APIView):
    """
    GET /api/olympiades/cadre/mes-olympiades/
    Retourne toutes les olympiades créées par le cadre connecté.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=403
            )

        olympiades = Olympiade.objects.filter(
            organisateur=profile
        ).select_related('devoir').order_by('-created_at')

        data = []
        for o in olympiades:
            data.append({
                "id": o.id,
                "titre": o.titre,
                "matiere": o.matiere,
                "niveau": o.niveau,
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
                "prix_1er": o.prix_1er,
                "prix_2eme": o.prix_2eme,
                "prix_3eme": o.prix_3eme,
                "recompense": o.recompense,
                "demande_paiement_participants": o.demande_paiement_participants,
                "prix_participation": o.prix_participation,
                "niveaux_accessibles": o.get_niveaux_accessibles_list(),
                "melanger_questions": o.melanger_questions,
                "melanger_choix": o.melanger_choix,
                "une_seule_session": o.une_seule_session,
                "max_focus_perdu": o.max_focus_perdu,
                "description": o.description,
                "created_at": o.created_at.isoformat() if hasattr(o, 'created_at') else None,
            })

        return Response(data)

# views.py - Ajouter LierDevoirOlympiadeView

class LierDevoirOlympiadeView(APIView):
    """
    POST /api/olympiades/<olympiade_id>/lier-devoir/
    Body: { "devoir_id": 123 }

    Lie un devoir existant à une olympiade.
    Le cadre doit être l'organisateur de l'olympiade et le créateur du devoir.
    Une fois lié, l'olympiade ne peut plus être modifiée.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, olympiade_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=403
            )

        olympiade = get_object_or_404(Olympiade, pk=olympiade_id)

        # Vérifier que le cadre est l'organisateur
        if olympiade.organisateur != profile:
            return Response(
                {"detail": "Vous n'êtes pas l'organisateur de cette olympiade."},
                status=403
            )

        # Vérifier que l'olympiade n'a pas déjà un devoir lié
        if olympiade.devoir:
            return Response(
                {"detail": "Cette olympiade a déjà un devoir lié. Elle ne peut plus être modifiée."},
                status=400
            )

        devoir_id = request.data.get('devoir_id')
        if not devoir_id:
            return Response(
                {"detail": "devoir_id est requis."},
                status=400
            )

        devoir = get_object_or_404(Devoir, pk=devoir_id)

        # Vérifier que le cadre a créé le devoir
        if devoir.cree_par != profile:
            return Response(
                {"detail": "Vous n'êtes pas le créateur de ce devoir."},
                status=403
            )

        # Vérifier que le devoir n'est pas déjà lié à une olympiade
        if hasattr(devoir, 'olympiade_config') and devoir.olympiade_config:
            return Response(
                {"detail": "Ce devoir est déjà lié à une olympiade."},
                status=400
            )

        # Lier le devoir à l'olympiade
        olympiade.devoir = devoir
        olympiade.save()

        # Le devoir devient non modifiable
        devoir.est_publie = False  # En attente de validation/paiement
        devoir.save()

        enregistrer_activite(
            user=request.user,
            action='olympiad_modified',
            description=f"Devoir « {devoir.titre} » lié à l'olympiade « {olympiade.titre} »",
            data={
                'olympiade': olympiade.titre,
                'devoir': devoir.titre,
            },
            objet_id=olympiade.id,
            objet_type='Olympiade',
        )

        # Calculer le prix global avec la nouvelle tarification
        nb_apprenants = Profile.objects.filter(
            user_type='apprenant',
            cursus=olympiade.organisateur.departements_cadre.first().parcours.nom,
            is_active=True
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
        olympiade.save(update_fields=['prix_global'])

        return Response({
            "detail": "Devoir lié avec succès à l'olympiade.",
            "olympiade_id": olympiade.id,
            "devoir_id": devoir.id,
            "prix_global": prix_global,
            "nb_apprenants": nb_apprenants,
            "message": "L'olympiade est maintenant prête à être soumise. Veuillez procéder au paiement pour la valider."
        }, status=200)

class VerifierAccesDepartementView(APIView):
    """
    GET /api/apprenant/departement/<pk>/acces/
    Vérifie si l'apprenant a accès au département.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)
        
        if profile.user_type != 'apprenant':
            return Response(
                {"detail": "Accès réservé aux apprenants."},
                status=403
            )
        
        departement = get_object_or_404(Departement, pk=pk)
        
        # Si pas d'accès restreint, tout le monde a accès
        if not departement.acces_restreint:
            return Response({
                "acces": True,
                "statut": "libre",
                "message": "Cette formation est en accès libre."
            })
        
        # Vérifier si l'apprenant est autorisé
        if request.user in departement.apprenants_autorises.all():
            return Response({
                "acces": True,
                "statut": "autorise",
                "message": "Vous avez accès à cette formation."
            })
        
        # Vérifier si une demande existe
        try:
            demande = DemandeAccesFormation.objects.get(
                apprenant=request.user,
                departement=departement
            )
            return Response({
                "acces": False,
                "statut": demande.statut,
                "message": "Votre demande d'accès est en attente de traitement." if demande.statut == 'en_attente' else "Votre demande d'accès a été refusée. Contactez le service client."
                    })
        except DemandeAccesFormation.DoesNotExist:
            return Response({
                "acces": False,
                "statut": "non_demandee",
                "message": "Vous devez demander l'accès à cette formation."
            })

# ---------------------------
# Update partiel departement
# ---------------------------
class DepartementUpdateView(generics.UpdateAPIView, generics.RetrieveAPIView):
    queryset = Departement.objects.select_related("parcours", "cadre")
    serializer_class = DepartementSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_target_parcours(self):
        dep = self.get_object()
        return dep.parcours

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        dep = self.get_object()
        payload = request.data

        if "enseignant_cadre" in payload:
            cadre_id = payload.get("enseignant_cadre")
            if cadre_id in [None, "", "null"]:
                dep.cadre = None
            else:
                cadre = get_object_or_404(User, pk=cadre_id)
                if getattr(cadre, "user_type", None) != "enseignant_cadre":
                    return Response({"detail": "L'utilisateur choisi n'est pas un enseignant_cadre."}, status=status.HTTP_400_BAD_REQUEST)
                dep.cadre = cadre

        if "nom" in payload:
            nom = (payload.get("nom") or "").strip()
            if not nom:
                return Response({"detail": "Le nom ne peut pas être vide."}, status=status.HTTP_400_BAD_REQUEST)
            dep.nom = nom

        dep.save()
        return Response(DepartementSerializer(dep).data, status=status.HTTP_200_OK)


# ---------------------------
# Parcours list/create (admin only create)
# ---------------------------
class ParcoursListCreateView(generics.ListCreateAPIView):
    queryset = Parcours.objects.all()
    serializer_class = ParcoursSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        user = self.request.user
        if getattr(user, "user_type", None) != "admin":
            raise PermissionDenied("Seul un administrateur général peut créer un parcours.")
        serializer.save()


# ---------------------------
# Assign admin to parcours
# ---------------------------
class AssignAdminView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        parcours = get_object_or_404(Parcours, pk=pk)
        admin_id = request.data.get("admin_id")
        if not admin_id:
            return Response({"error": "admin_id requis."}, status=status.HTTP_400_BAD_REQUEST)

        admin_user = get_object_or_404(User, pk=admin_id)
        if getattr(admin_user, "user_type", None) != "enseignant_admin":
            return Response({"error": "Utilisateur n'est pas enseignant_admin."}, status=status.HTTP_400_BAD_REQUEST)

        parcours.admin = admin_user
        parcours.save()
        return Response({"message": "Enseignant admin assigné avec succès."}, status=status.HTTP_200_OK)


# ---------------------------
# Stats enseignant_admin
# ---------------------------
class EnseignantAdminStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        admin_user = get_object_or_404(User, pk=pk, user_type="enseignant_admin")

        # départements où le parcours est administré par admin_user
        departements_count = Departement.objects.filter(parcours__admin=admin_user).count()

        # cours et leçons reliés aux parcours adminés par admin_user
        cours_count = Cours.objects.filter(departement__parcours__admin=admin_user).count()
        lecons_count = Lecon.objects.filter(cours__departement__parcours__admin=admin_user).count()

        stats = {
            "departements": departements_count,
            "cours": cours_count,
            "lecons": lecons_count
        }
        return Response(stats, status=status.HTTP_200_OK)


class HistoriqueActiviteView(APIView):
    permission_classes = [IsAuthenticated]

    CATEGORIES = {
        'cours':        ['course_created', 'course_modified', 'course_deleted'],
        'modules':      ['module_created', 'module_modified', 'module_deleted'],
        'lecons':       ['lesson_created', 'lesson_modified', 'lesson_deleted'],
        'devoirs':      ['homework_created', 'homework_modified', 'homework_graded'],
        'exercices':    ['exercise_created', 'question_added'],
        'olympiades':   ['olympiad_created', 'olympiad_closed', 'ranking_computed'],
        'enseignants':  ['teacher_assigned', 'teacher_changed', 'secondary_added', 'secondary_removed'],
        'departements': ['department_created', 'cadre_assigned'],
        'corrections':  ['submission_graded', 'homework_graded'],
    }

    def get(self, request):
        qs = HistoriqueActivite.objects.filter(
            user=request.user
        ).order_by('-timestamp')

        action_param = request.query_params.get('action')
        if action_param:
            qs = qs.filter(action=action_param)

        category_param = request.query_params.get('category', '').lower()
        if category_param and category_param in self.CATEGORIES:
            from django.db.models import Q
            q = Q()
            for a in self.CATEGORIES[category_param]:
                q |= Q(action=a)
            qs = qs.filter(q)

        depuis_param = request.query_params.get('depuis')
        if depuis_param:
            try:
                from datetime import datetime
                depuis_dt = datetime.strptime(depuis_param, '%Y-%m-%d')
                qs = qs.filter(timestamp__date__gte=depuis_dt.date())
            except ValueError:
                pass

        try:
            limit = min(int(request.query_params.get('limit', 100)), 200)
        except (TypeError, ValueError):
            limit = 100

        qs = qs[:limit]
        serializer = HistoriqueActiviteSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class HistoriqueStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        total = HistoriqueActivite.objects.filter(user=request.user).count()

        semaine_debut = now - timedelta(days=7)
        cette_semaine = HistoriqueActivite.objects.filter(
            user=request.user, timestamp__gte=semaine_debut
        ).count()

        mois_debut = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ce_mois = HistoriqueActivite.objects.filter(
            user=request.user, timestamp__gte=mois_debut
        ).count()

        category_map = {
            'cours':        ['course_created', 'course_modified', 'course_deleted'],
            'modules':      ['module_created', 'module_modified', 'module_deleted'],
            'lecons':       ['lesson_created', 'lesson_modified', 'lesson_deleted'],
            'devoirs':      ['homework_created', 'homework_modified', 'homework_graded'],
            'exercices':    ['exercise_created', 'question_added'],
            'olympiades':   ['olympiad_created', 'olympiad_closed', 'ranking_computed'],
            'enseignants':  ['teacher_assigned', 'teacher_changed', 'secondary_added', 'secondary_removed'],
            'corrections':  ['submission_graded', 'homework_graded'],
        }
        categories_count = {}
        for cat, actions in category_map.items():
            categories_count[cat] = HistoriqueActivite.objects.filter(
                user=request.user, action__in=actions
            ).count()

        derniere = HistoriqueActivite.objects.filter(
            user=request.user
        ).order_by('-timestamp').first()

        return Response({
            'total':             total,
            'cette_semaine':     cette_semaine,
            'ce_mois':           ce_mois,
            'categories':        categories_count,
            'derniere_activite': derniere.timestamp.isoformat() if derniere else None,
        }, status=status.HTTP_200_OK)


# ══════════════════════════════════════════════════════════════════
# APPRENANT — PRÉPA CONCOURS/FORMATION
# views.py - Remplacer ApprenantConcoursFormationsView et ApprenantFormationsAPIView par une vue unifiée

class ApprenantConcoursFormationsView(APIView):
    """
    GET /api/apprenant/prepa-concours/   → type='prepa' (concours)
    GET /api/apprenant/formations/       → type='formation' (formations)
    
    Retourne les concours ou formations accessibles selon le niveau de l'apprenant.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Récupérer le type depuis l'URL ou query param
        # Le type est déterminé par l'URL appelée
        path = request.path
        if 'prepa-concours' in path:
            type_parcours = 'prepa'
        elif 'formations' in path:
            type_parcours = 'formation'
        else:
            type_parcours = request.query_params.get('type', 'prepa')
        
        # Récupérer le profil de l'apprenant
        profile = _get_profile(request.user)
        if not profile or profile.user_type != 'apprenant':
            return Response({"detail": "Accès réservé aux apprenants"}, status=403)
        
        niveau_apprenant = (profile.niveau or '').strip().lower()
        
        # Filtrer par type de parcours
        depts = Departement.objects.filter(
            parcours__type_parcours=type_parcours,
            est_actif=True,
        ).select_related('parcours', 'cadre__user')

        resultats = []
        for dept in depts:
            # Filtrer par niveau
            if not dept.est_accessible_par_niveau(niveau_apprenant):
                continue
            
            # Récupérer les cours du département
            cours_qs = Cours.objects.filter(departement=dept)
            
            # Filtrer les cours par niveau
            if niveau_apprenant:
                cours_qs = cours_qs.filter(niveau__iexact=niveau_apprenant)
            
            cours_data = []
            for cours in cours_qs:
                cours_data.append({
                    'id': cours.id,
                    'titre': cours.titre,
                    'niveau': cours.niveau,
                    'description_brief': cours.description_brief or '',
                    'color_code': cours.color_code,
                    'icon_name': cours.icon_name,
                    'nb_lecons': cours.nb_lecons,
                    'nb_devoirs': cours.nb_devoirs,
                    'progression': 0.0,  # À calculer avec _progression_cours si besoin
                })
            
            resultats.append(self._serialiser_departement(dept, cours_data, request))
        
        return Response(resultats)

    def _serialiser_departement(self, dept, cours_data, request):
        """Sérialise un département avec ses cours selon son type."""
        image_url = None
        if dept.image:
            try:
                image_url = request.build_absolute_uri(dept.image.url)
            except Exception:
                pass

        statut = 'ACTIF' if dept.est_actif else 'INACTIF'
        type_parcours = dept.parcours.type_parcours if dept.parcours else ''

        # Base commune
        result = {
            'id': dept.id,
            'nom': dept.nom,
            'description': dept.description,
            'image_url': image_url,
            'couleur': dept.couleur or '#135F74',
            'prix': dept.prix,
            'prix_presentiel': dept.prix_presentiel,
            'type': dept.type_departement,
            'statut': statut,
            'progression': 0.0,
            'progression_moyenne': 0.0,
            'cours': cours_data,
            'nb_cours': len(cours_data),
            'niveaux_accessibles': dept.get_niveaux_accessibles_list(),
            'acces_restreint': dept.acces_restreint,
            'type_parcours': type_parcours,
            'parcours_nom': dept.parcours.nom if dept.parcours else '',
        }

        # Champs spécifiques aux concours (prepa)
        if type_parcours == 'prepa':
            result.update({
                'est_prepa_concours': True,
                'est_formation_metier': False,
                'est_formation_classique': False,
                'nom_concours': dept.nom_concours or '',
                'organisme_concours': dept.organisme_concours or '',
                'date_limite_inscription': dept.date_limite_inscription.isoformat() if dept.date_limite_inscription else None,
                'date_examen': dept.date_examen.isoformat() if dept.date_examen else None,
                'arrete_ministeriel': dept.arrete_ministeriel or '',
                'niveaux_cibles': dept.niveaux_cibles or '',
                'places_disponibles': dept.places_disponibles,
                'debouches': dept.debouches or '',
                'date_examen': dept.date_examen,
                'mode': dept.mode or '',
                'date_limite_inscription': dept.date_limite_inscription,
            })
        # Champs spécifiques aux formations
        elif type_parcours == 'formation':
            result.update({
                'est_prepa_concours': False,
                'est_formation_metier': dept.est_formation_metier,
                'est_formation_classique': dept.est_formation_classique,
                'duree_formation': dept.duree_formation or '',
                'mode': dept.mode or '',
                'mode_label': {
                    'presentiel': 'Présentiel',
                    'distance': 'À distance',
                    'hybride': 'Hybride',
                }.get(dept.mode, ''),
                'certificat_delivre': dept.certificat_delivre or '',
                'prerequis': dept.prerequis or '',
                'objectifs': dept.objectifs or '',
                'domaine': dept.domaine or '',
                'ville': dept.ville or '',
                'est_certifiante': dept.est_certifiante,
            })
        else:
            # Parcours autre (cursus) - champs par défaut
            result.update({
                'est_prepa_concours': False,
                'est_formation_metier': False,
                'est_formation_classique': False,
            })

        return result 

# ═══════════════════════════════════════════════════════════════════════════
# OLYMPIADES POUR APPRENANT (avec filtre par niveau)
# ═══════════════════════════════════════════════════════════════════════════

class OlympiadesPourMoiView(APIView):
    """
    GET /api/olympiades/pour-moi/
    
    Olympiades filtrées pour l'apprenant connecté selon son niveau.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        if not profile:
            return Response({"detail": "Profil introuvable."}, status=404)

        niveau_apprenant = (profile.niveau or '').strip().lower()

        # Base queryset — olympiades publiées ET validées
        qs = Olympiade.objects.filter(
            devoir__est_publie=True,
        ).select_related(
            'organisateur__user', 'devoir'
        ).order_by('-date_debut_olympiade')

        # ⭐ FILTRAGE PAR NIVEAU
        olympiades_accessibles = []
        for o in qs:
            if o.est_accessible_par_niveau(niveau_apprenant):
                olympiades_accessibles.append(o)

        serializer = OlympiadeListSerializer(
            olympiades_accessibles, many=True, context={"request": request}
        )
        return Response(serializer.data)


class ApprenantDepartementDetailView(APIView):
    """GET /api/apprenant/departement/<pk>/ — detail complet"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        dept = get_object_or_404(Departement, pk=pk)
        cours_qs = Cours.objects.filter(departement=dept).select_related('enseignant_principal__user')
        prog_map = _progression_cours(request.user, cours_qs)
        return Response(_serialise_departement_detail(dept, prog_map=prog_map, include_cours=True, user=request.user))

# ══════════════════════════════════════════════════════════════════
# ENSEIGNANT ADMIN — OLYMPIADES À VALIDER
# GET  /api/admin/olympiades/a-valider/
# POST /api/admin/olympiades/<pk>/valider/
#
# L'admin ne voit et ne valide que les olympiades de SON parcours.
# Seules les olympiades avec prix vides (gratuit) passent par la
# validation admin. Les autres sont visibles directement.
#
# Mécanisme : Devoir.est_publie=False = en attente de validation.
#             L'admin met est_publie=True → visible pour les apprenants.
# ══════════════════════════════════════════════════════════════════

class AdminOlympiadesAValiderView(APIView):
    """
    GET /api/admin/olympiades/a-valider/
    Retourne les olympiades du parcours de l'admin qui attendent validation
    ou qui ont été refusées.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != 'enseignant_admin':
            return Response({"detail": "Accès refusé."}, status=403)

        try:
            parcours = Parcours.objects.get(admin=profile)
        except Parcours.DoesNotExist:
            return Response({"detail": "Aucun parcours assigné."}, status=404)

        # Olympiades en attente de validation (prix_global = 0, non validées, non refusées)
        olympiades_attente = Olympiade.objects.filter(
            organisateur__departements_cadre__parcours=parcours,
            prix_global=0,
            est_validee=False,
            est_refusee=False,
        ).distinct().select_related('organisateur__user', 'devoir')

        # Olympiades refusées (l'admin peut encore les voir pour accepter)
        olympiades_refusees = Olympiade.objects.filter(
            organisateur__departements_cadre__parcours=parcours,
            prix_global=0,
            est_refusee=True,
        ).distinct().select_related('organisateur__user', 'devoir')

        result = []
        for o in olympiades_attente:
            result.append({
                "id": o.id,
                "titre": o.titre,
                "matiere": o.matiere,
                "niveau": o.niveau,
                "edition": o.edition,
                "statut_validation": "attente",
                "cadre": {
                    "id": o.organisateur.id,
                    "nom": _nom_profil(o.organisateur),
                },
                "date_creation": o.created_at,
                "prix_global": getattr(o, 'prix_global', 0),
                "niveaux_accessibles": o.get_niveaux_accessibles_list(),
            })
        
        for o in olympiades_refusees:
            result.append({
                "id": o.id,
                "titre": o.titre,
                "matiere": o.matiere,
                "niveau": o.niveau,
                "edition": o.edition,
                "statut_validation": "refuse",
                "motif_refus": getattr(o, 'motif_refus', ''),
                "cadre": {
                    "id": o.organisateur.id,
                    "nom": _nom_profil(o.organisateur),
                },
                "date_creation": o.created_at,
                "prix_global": getattr(o, 'prix_global', 0),
                "niveaux_accessibles": o.get_niveaux_accessibles_list(),
            })

        return Response(result)

class AdminValiderOlympiadeView(APIView):
    """
    POST /api/admin/olympiades/<pk>/valider/
    Body optionnel : { "refuser": true, "motif": "..." }

    Valide (publie) ou refuse une olympiade du parcours de l'admin.
    Valider = mettre Devoir.est_publie = True
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != 'enseignant_admin':
            return Response({"detail": "Accès refusé."}, status=403)

        try:
            parcours = Parcours.objects.get(admin=profile)
        except Parcours.DoesNotExist:
            return Response({"detail": "Aucun parcours assigné."}, status=404)

        olympiade = get_object_or_404(
            Olympiade,
            pk=pk,
            organisateur__departements_cadre__parcours=parcours,
        )

        refuser = request.data.get('refuser', False)

        if refuser:
            motif = request.data.get('motif', 'Refusée par l\'administrateur.')
            olympiade.est_refusee = True
            olympiade.est_validee = False
            olympiade.motif_refus = motif
            olympiade.save()
            
            enregistrer_activite(
                user=request.user,
                action='olympiad_rejected',
                description=f"Olympiade « {olympiade.titre} » refusée. Motif : {motif}",
                objet_id=olympiade.id,
                objet_type='Olympiade',
            )
            return Response({
                "detail": f"Olympiade refusée. Motif : {motif}",
                "id": olympiade.id,
                "statut": "refuse",
            })

        # Valider → publier le devoir lié
        if not olympiade.devoir:
            return Response(
                {"detail": "Cette olympiade n'a pas de devoir lié. Impossible de valider."},
                status=400,
            )

        olympiade.devoir.est_publie = True
        olympiade.devoir.save(update_fields=['est_publie'])
        olympiade.est_validee = True
        olympiade.est_refusee = False
        olympiade.save(update_fields=['est_validee', 'est_refusee'])

        enregistrer_activite(
            user=request.user,
            action='olympiad_validated',
            description=f"Olympiade « {olympiade.titre} » validée et publiée.",
            objet_id=olympiade.id,
            objet_type='Olympiade',
        )

        return Response({
            "detail": "Olympiade validée et publiée avec succès.",
            "id":     olympiade.id,
            "titre":  olympiade.titre,
            "statut": "validee",
        })

class AdminRefuserOlympiadeView(APIView):
    """Refuser une olympiade (la garde visible mais marquée comme refusée)"""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, olympiade_id):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != 'enseignant_admin':
            return Response({"detail": "Accès refusé."}, status=403)

        try:
            parcours = Parcours.objects.get(admin=profile)
        except Parcours.DoesNotExist:
            return Response({"detail": "Aucun parcours assigné."}, status=404)

        olympiade = get_object_or_404(
            Olympiade,
            pk=olympiade_id,
            organisateur__departements_cadre__parcours=parcours,
        )

        motif = request.data.get('motif', 'Refusée par l\'administrateur.')
        
        olympiade.est_refusee = True
        olympiade.est_validee = False
        olympiade.motif_refus = motif
        olympiade.save()
        
        enregistrer_activite(
            user=request.user,
            action='olympiad_rejected',
            description=f"Olympiade « {olympiade.titre} » refusée. Motif : {motif}",
            objet_id=olympiade.id,
            objet_type='Olympiade',
        )
        
        return Response({
            "detail": "Olympiade refusée.",
            "id": olympiade.id,
            "est_refusee": True,
        })

# views.py - Ajouter

class ApprenantsParDepartementView(APIView):
    """GET /api/departements/<departement_id>/apprenants/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, departement_id):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != 'enseignant_cadre':
            return Response({"detail": "Accès réservé aux enseignants cadres."}, status=403)
        
        departement = get_object_or_404(Departement, pk=departement_id)
        
        # Vérifier que le cadre gère ce département
        if departement.cadre != profile:
            return Response({"detail": "Vous n'êtes pas le cadre de ce département."}, status=403)
        
        # Récupérer les apprenants du parcours
        apprenants = Profile.objects.filter(
            user_type='apprenant',
            cursus=departement.parcours.nom,
            is_active=True
        ).select_related('user')
        
        data = [{
            "id": a.id,
            "nom": _nom_profil(a),
            "username": a.user.username,
            "email": a.user.email,
        } for a in apprenants]
        
        return Response(data)


# ══════════════════════════════════════════════════════════════════
# PAIEMENT
# POST /api/paiements/initier/
# GET  /api/paiements/<reference>/verifier/
# GET  /api/paiements/historique/
# ══════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════
# PAIEMENT CINETPAY - VERSION UNIFIÉE
# ══════════════════════════════════════════════════════════════════

class InitierPaiementCinetPayView(APIView):
    """
    POST /api/paiements/cinetpay/initier/
    
    Body:
    {
        "type_paiement": "wallet_recharge" | "acces_departement" | "olympiade" | "abonnement_mensuel" | "abonnement_annuel",
        "montant": 5000,
        "payment_method": "mtn_momo" | "orange_money" | "card",
        "phone": "691234567",  // Optionnel pour carte
        "departement_id": 1,   // Si type = acces_departement
        "olympiade_id": 2      // Si type = olympiade
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        type_paiement = request.data.get('type_paiement', '').strip()
        montant = request.data.get('montant')
        payment_method = request.data.get('payment_method', 'mtn_momo').strip()
        phone = request.data.get('phone', '').strip()
        departement_id = request.data.get('departement_id')
        olympiade_id = request.data.get('olympiade_id')

        # ── Validation ──────────────────────────────────────────
        types_valides = ['wallet_recharge', 'acces_departement', 'olympiade', 
                        'abonnement_mensuel', 'abonnement_annuel']
        if type_paiement not in types_valides:
            return Response(
                {'detail': f'type_paiement invalide. Valeurs: {types_valides}'},
                status=400
            )

        try:
            montant = int(montant)
            if montant < 500:
                return Response({'detail': 'Montant minimum: 500 FCFA'}, status=400)
        except (TypeError, ValueError):
            return Response({'detail': 'Montant invalide'}, status=400)

        # ── Créer la transaction ────────────────────────────────
        reference = f"YEKI-{uuid.uuid4().hex[:8].upper()}"
        
        transaction = CinetPayTransaction.objects.create(
            user=request.user,
            amount=montant,
            reference=reference,
            payment_method=payment_method,
            status='pending'
        )

        # ── Préparer les données pour CinetPay ──────────────────
        site_id = settings.CINETPAY_SITE_ID
        api_key = settings.CINETPAY_API_KEY
        notify_url = f"https://yeki.pythonanywhere.com/api/paiements/cinetpay/notify/"
        return_url = f"https://yeki.pythonanywhere.com/payment-result/"

        # Construire le payload
        payment_data = {
            'amount': montant,
            'currency': 'XAF',
            'transaction_id': reference,
            'description': f'Yéki - {type_paiement}',
            'site_id': site_id,
            'apikey': api_key,
            'notify_url': notify_url,
            'return_url': return_url,
            'channels': 'ALL',
            'metadata': json.dumps({
                'user_id': request.user.id,
                'type_paiement': type_paiement,
                'departement_id': departement_id,
                'olympiade_id': olympiade_id,
                'reference': reference
            }),
            'customer_name': f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username,
            'customer_email': request.user.email,
            'customer_phone_number': phone or '',
            'customer_address': 'Cameroun',
        }

        # Ajouter le canal spécifique si demandé
        if payment_method == 'mtn_momo':
            payment_data['channels'] = 'MOBILE_MONEY'
            payment_data['payment_method'] = 'MTN'
        elif payment_method == 'orange_money':
            payment_data['channels'] = 'MOBILE_MONEY'
            payment_data['payment_method'] = 'ORANGE'
        elif payment_method == 'card':
            payment_data['channels'] = 'CARD'

        try:
            response = requests.post(
                'https://api-checkout.cinetpay.com/v2/payment',
                json=payment_data,
                timeout=30
            )

            if response.status_code == 200 or response.status_code == 201:
                data = response.json()
                if data.get('code') in [200, 201]:
                    payment_url = data.get('data', {}).get('payment_url')
                    transaction_id = data.get('data', {}).get('transaction_id')
                    
                    transaction.transaction_id = transaction_id
                    transaction.save()
                    
                    return Response({
                        'reference': reference,
                        'payment_url': payment_url,
                        'status': 'pending',
                        'message': 'Paiement initié. Veuillez compléter la transaction.'
                    }, status=200)
                else:
                    transaction.status = 'failed'
                    transaction.save()
                    return Response({
                        'detail': data.get('message', 'Erreur CinetPay')
                    }, status=400)
            else:
                transaction.status = 'failed'
                transaction.save()
                return Response({'detail': 'Erreur de communication avec CinetPay'}, status=500)

        except Exception as e:
            transaction.status = 'failed'
            transaction.save()
            return Response({'detail': f'Erreur: {str(e)}'}, status=500)


class CinetPayWebhookView(APIView):
    """
    POST /api/paiements/cinetpay/notify/
    Webhook appelé par CinetPay après paiement
    """
    permission_classes = []  # Public
    authentication_classes = []  # Pas d'auth

    def post(self, request):
        data = request.data
        
        # Vérifier la signature (recommandé)
        # signature = request.headers.get('X-CinetPay-Signature')
        
        transaction_id = data.get('cpm_trans_id') or data.get('transaction_id')
        status = data.get('cpm_result') or data.get('status')
        
        if not transaction_id:
            return Response({'detail': 'transaction_id manquant'}, status=400)

        try:
            transaction = CinetPayTransaction.objects.get(transaction_id=transaction_id)
        except CinetPayTransaction.DoesNotExist:
            # Essayer par référence
            reference = data.get('cpm_custom') or data.get('reference')
            if reference:
                try:
                    transaction = CinetPayTransaction.objects.get(reference=reference)
                except CinetPayTransaction.DoesNotExist:
                    return Response({'detail': 'Transaction non trouvée'}, status=404)
            else:
                return Response({'detail': 'Transaction non trouvée'}, status=404)

        # Ne pas traiter deux fois
        if transaction.status == 'success':
            return Response({'status': 'already_processed'})

        # Vérifier le statut
        if status in ['00', 'ACCEPTED', 'SUCCESS', 'success']:
            transaction.status = 'success'
            transaction.save()

            # ── Créditer le wallet ou activer l'abonnement ──────
            metadata = json.loads(data.get('metadata', '{}')) if data.get('metadata') else {}
            type_paiement = metadata.get('type_paiement', 'wallet_recharge')

            if type_paiement == 'wallet_recharge':
                wallet = YekiWallet.get_or_create_wallet(transaction.user)
                wallet.crediter(
                    montant=transaction.amount,
                    description=f'Recharge CinetPay - {transaction.reference}',
                    reference=transaction.reference
                )
            elif type_paiement in ['abonnement_mensuel', 'abonnement_annuel']:
                jours = 30 if type_paiement == 'abonnement_mensuel' else 365
                try:
                    abo = transaction.user.abonnement
                    abo.renouveler('mensuel' if jours == 30 else 'annuel')
                except AbonnementPremium.DoesNotExist:
                    AbonnementPremium.objects.create(
                        utilisateur=transaction.user,
                        type_abonnement='mensuel' if jours == 30 else 'annuel',
                        actif=True,
                        fin=timezone.now() + timedelta(days=jours),
                    )
            elif type_paiement == 'olympiade':
                olympiade_id = metadata.get('olympiade_id')
                if olympiade_id:
                    InscriptionOlympiade.objects.get_or_create(
                        olympiade_id=olympiade_id,
                        apprenant=transaction.user,
                        defaults={'statut': 'confirme'}
                    )

            # Créer l'enregistrement de paiement
            Paiement.objects.create(
                utilisateur=transaction.user,
                type_paiement=type_paiement,
                moyen='cinetpay',
                montant=transaction.amount,
                statut='succes',
                transaction_id=transaction.transaction_id,
                reference=transaction.reference
            )

        elif status in ['-1', 'FAILED', 'failed', 'CANCELLED']:
            transaction.status = 'failed'
            transaction.save()

        return Response({'status': 'ok'})


class VerifierPaiementCinetPayView(APIView):
    """
    GET /api/paiements/cinetpay/verifier/<reference>/
    Vérifie le statut d'une transaction
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        transaction = get_object_or_404(
            CinetPayTransaction, 
            reference=reference, 
            user=request.user
        )

        # Optionnel: Vérifier auprès de CinetPay
        try:
            site_id = settings.CINETPAY_SITE_ID
            api_key = settings.CINETPAY_API_KEY
            
            response = requests.post(
                'https://api-checkout.cinetpay.com/v2/payment/check',
                json={
                    'site_id': site_id,
                    'apikey': api_key,
                    'transaction_id': transaction.transaction_id or reference,
                },
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 200:
                    cinetpay_status = data.get('data', {}).get('status')
                    if cinetpay_status == 'ACCEPTED' and transaction.status != 'success':
                        # Mettre à jour (normalement déjà fait par webhook)
                        pass
        except Exception:
            pass

        return Response({
            'reference': transaction.reference,
            'status': transaction.status,
            'amount': transaction.amount,
            'created_at': transaction.created_at.isoformat(),
        })


class HistoriquePaiementsView(APIView):
    """GET /api/paiements/historique/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        paiements = Paiement.objects.filter(
            utilisateur=request.user
        ).order_by('-date')[:50]

        data = [{
            "reference":     p.reference,
            "type_paiement": p.get_type_paiement_display(),
            "montant":       p.montant,
            "moyen":         p.get_moyen_display(),
            "statut":        p.statut,
            "date":          p.date,
        } for p in paiements]

        return Response(data)


# ══════════════════════════════════════════════════════════════════
# ABONNEMENT PREMIUM
# GET /api/abonnement/statut/
# ══════════════════════════════════════════════════════════════════

class StatutAbonnementView(APIView):
    """
    GET /api/abonnement/statut/
    Retourne le statut de l'abonnement premium de l'apprenant.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            abo = request.user.abonnement
            return Response({
                "actif":            abo.est_actif,
                "type_abonnement":  abo.type_abonnement,
                "debut":            abo.debut,
                "fin":              abo.fin,
                "jours_restants":   max(0, (abo.fin - timezone.now()).days),
            })
        except AbonnementPremium.DoesNotExist:
            return Response({
                "actif":           False,
                "type_abonnement": None,
                "debut":           None,
                "fin":             None,
                "jours_restants":  0,
            })


# ══════════════════════════════════════════════════════════════════
# YEKI IA — RÉPONSE AUTOMATIQUE DANS LE FORUM
# POST /api/ia/forum/<question_id>/repondre/
# POST /api/ia/cours/<cours_id>/chat/
# ══════════════════════════════════════════════════════════════════

def _get_ia_personnalite(cours=None, nom_parcours=None, niveau_cursus=None):
    """Récupère ou crée la personnalité IA adaptée au contexte."""
    qs = YekiIAPersonalite.objects.all()

    if cours:
        obj = qs.filter(cours_lie=cours).first()
        if obj:
            return obj
        return YekiIAPersonalite.objects.create(
            nom=f"IA – {cours.titre}",
            contexte='cours',
            style='pedagogique',
            niveau_difficulte='intermediaire',
            cours_lie=cours,
            niveau_cursus=cours.niveau or '',
        )

    if nom_parcours:
        obj = qs.filter(contexte='parcours', nom_parcours=nom_parcours).first()
        if obj:
            return obj
        return YekiIAPersonalite.objects.create(
            nom=f"IA – {nom_parcours}",
            contexte='parcours',
            style='academique',
            niveau_difficulte='intermediaire',
            nom_parcours=nom_parcours,
        )

    if niveau_cursus:
        obj = qs.filter(contexte='cursus_niveau', niveau_cursus=niveau_cursus).first()
        if obj:
            return obj
        style    = 'encourageant' if niveau_cursus in ['3ème', '2nde'] else 'pedagogique'
        difficulte = 'debutant'   if niveau_cursus in ['3ème', '2nde'] else 'intermediaire'
        return YekiIAPersonalite.objects.create(
            nom=f"IA – Niveau {niveau_cursus}",
            contexte='cursus_niveau',
            style=style,
            niveau_difficulte=difficulte,
            niveau_cursus=niveau_cursus,
        )

    # Fallback générique
    obj = qs.filter(contexte='cursus_niveau', niveau_cursus='').first()
    if obj:
        return obj
    return YekiIAPersonalite.objects.create(
        nom="IA – Générale",
        contexte='cursus_niveau',
        style='pedagogique',
        niveau_difficulte='intermediaire',
    )


def _appeler_openai(system_prompt: str, question: str) -> tuple[str, int]:
    """
    Appelle l'API OpenAI et retourne (réponse_texte, tokens_utilisés).
    En cas d'erreur ou si la clé est absente, retourne une réponse de secours.
    """
    import openai as _openai

    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        return (
            "Yeki IA : Je suis temporairement indisponible. "
            "Un enseignant répondra à votre question prochainement.",
            0,
        )

    _openai.api_key = api_key
    try:
        response = _openai.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=800,
            messages=[
                {"role": "system",  "content": system_prompt},
                {"role": "user",    "content": question},
            ],
        )
        texte  = response.choices[0].message.content.strip()
        tokens = response.usage.total_tokens
        return texte, tokens
    except Exception as e:
        return (
            "Yeki IA : Désolé, je rencontre une difficulté technique. "
            "Veuillez réessayer ou contacter un enseignant.",
            0,
        )


class YekiIAChatView(APIView):
    """
    POST /api/ia/cours/<cours_id>/chat/
    Body : { "message": "Explique-moi les dérivées" }

    Chat direct avec Yeki IA dans le contexte d'un cours.
    Retourne directement la réponse sans créer de ReponseQuestion.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        message = (request.data.get('message') or '').strip()
        if not message:
            return Response({"detail": "message requis."}, status=400)

        personnalite = _get_ia_personnalite(cours=cours)
        system_prompt = personnalite.build_system_prompt()
        texte_ia, tokens = _appeler_openai(system_prompt, message)

        if not texte_ia.startswith("Yeki IA :"):
            texte_ia = f"Yeki IA : {texte_ia}"

        return Response({
            "reponse": texte_ia,
            "tokens":  tokens,
            "cours":   {"id": cours.id, "titre": cours.titre},
        })



# ══════════════════════════════════════════════════════════════════
# WALLET — PORTEFEUILLE YEKI
# GET  /api/wallet/solde/            → solde + historique
# POST /api/wallet/recharger/        → recharge via Google Play IAP ou Mobile Money
# POST /api/wallet/payer/            → payer cours/formation/olympiade depuis wallet
# POST /api/wallet/verifier-iap/     → webhook Google Play purchase verification
# ══════════════════════════════════════════════════════════════════

# Prix IA
TARIF_IA_FCFA_PAR_1K_TOKENS = 2    # 2 FCFA par 1000 tokens
COMMISSION_YEKI_IA_FCFA      = 5   # 5 FCFA commission fixe par requête
TARIF_IA_MIN                 = 10  # minimum 10 FCFA par requête


def _calculer_cout_ia(tokens: int) -> int:
    """Calcule le coût d'une requête IA en FCFA."""
    cout_tokens = max(1, round(tokens * TARIF_IA_FCFA_PAR_1K_TOKENS / 1000))
    return max(TARIF_IA_MIN, cout_tokens + COMMISSION_YEKI_IA_FCFA)


class WalletSoldeView(APIView):
    """GET /api/wallet/solde/ — solde et historique des transactions"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = YekiWallet.get_or_create_wallet(request.user)
        transactions = wallet.transactions.all()[:30]
        return Response({
            'solde':    wallet.solde,
            'total_recharge': wallet.total_recharge,
            'total_depense':  wallet.total_depense,
            'transactions': [{
                'id':          t.id,
                'type':        t.type_transaction,
                'montant':     t.montant,
                'description': t.description,
                'cree_le':     t.cree_le.isoformat(),
            } for t in transactions],
        })


class WalletRechargerView(APIView):
    """
    POST /api/wallet/recharger/
    Body: {
      "moyen": "google_play" | "mtn_momo" | "orange_om",
      "montant": 5000,                        ← pour Mobile Money
      "purchase_token": "...",                 ← pour Google Play
      "sku": "yeki_recharge_5000",             ← pour Google Play
      "telephone": "6XXXXXXXX"                 ← pour Mobile Money
    }
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    # SKUs Google Play → montants (FCFA)
    GOOGLE_PLAY_SKUS = {
        'yeki_recharge_1000':  1000,
        'yeki_recharge_2000':  2000,
        'yeki_recharge_5000':  5000,
        'yeki_recharge_10000': 10000,
        'yeki_recharge_20000': 20000,
        'yeki_premium_1500':   1500,  # Abonnement mensuel
        'yeki_premium_13000':  13000, # Abonnement annuel
    }

    def post(self, request):
        moyen = request.data.get('moyen', '').strip()

        if moyen == 'google_play':
            return self._google_play(request)
        elif moyen in ('mtn_momo', 'orange_om'):
            return self._mobile_money(request, moyen)
        else:
            return Response({'detail': 'moyen invalide. Valeurs: google_play, mtn_momo, orange_om'}, status=400)

    def _google_play(self, request):
        """Vérification d'un achat Google Play et crédit du wallet."""
        purchase_token = request.data.get('purchase_token', '').strip()
        sku            = request.data.get('sku', '').strip()
        package_name   = 'com.yeki.app'

        if not purchase_token or not sku:
            return Response({'detail': 'purchase_token et sku requis.'}, status=400)

        if sku not in self.GOOGLE_PLAY_SKUS:
            return Response({'detail': f'SKU inconnu: {sku}'}, status=400)

        montant = self.GOOGLE_PLAY_SKUS[sku]

        # ── Vérification Google Play Developer API ──────────────
        try:
            valide, message = self._verifier_google_play_purchase(
                package_name, sku, purchase_token
            )
        except Exception as e:
            return Response({'detail': f'Erreur vérification Google Play: {e}'}, status=500)

        if not valide:
            return Response({'detail': f'Achat Google Play invalide: {message}'}, status=402)

        # Vérifier que ce token n'a pas déjà été utilisé (anti-replay)
        if WalletTransaction.objects.filter(reference_paiement=purchase_token).exists():
            return Response({'detail': 'Cet achat a déjà été enregistré.'}, status=400)

        wallet = YekiWallet.get_or_create_wallet(request.user)

        # SKU abonnement Premium → activer l'abonnement
        if 'premium' in sku:
            type_abo = 'mensuel' if '1500' in sku else 'annuel'
            paiement = Paiement.objects.create(
                utilisateur=request.user, type_paiement=f'abonnement_{type_abo}',
                moyen='google_play', montant=montant, statut='succes',
                transaction_id=purchase_token,
            )
            jours = 30 if type_abo == 'mensuel' else 365
            try:
                abo = request.user.abonnement
                abo.renouveler(type_abo)
                abo.paiement = paiement
                abo.save()
            except AbonnementPremium.DoesNotExist:
                AbonnementPremium.objects.create(
                    utilisateur=request.user, type_abonnement=type_abo,
                    actif=True, fin=timezone.now() + timedelta(days=jours),
                    paiement=paiement,
                )
            return Response({
                'statut': 'succes',
                'detail': f'Abonnement {type_abo} activé.',
                'montant': montant,
            })

        # SKU recharge → créditer le wallet
        wallet.crediter(
            montant=montant,
            description=f'Recharge Google Play ({sku})',
            reference=purchase_token,
        )

        return Response({
            'statut':       'succes',
            'solde':        wallet.solde,
            'montant':      montant,
            'detail':       f'Wallet rechargé de {montant} FCFA.',
            'sku':          sku,
        })

    def _verifier_google_play_purchase(self, package_name: str, sku: str, purchase_token: str):
        """
        Vérifie un achat via Google Play Developer API.
        Nécessite : GOOGLE_SERVICE_ACCOUNT_JSON dans les settings.
        """
        from django.conf import settings
        import json

        service_account_json = getattr(settings, 'GOOGLE_SERVICE_ACCOUNT_JSON', None)

        # En mode DEBUG sans credentials → simuler succès
        if settings.DEBUG and not service_account_json:
            return True, "Mode DEBUG — achat simulé"

        if not service_account_json:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON non configuré")

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds_dict = json.loads(service_account_json) if isinstance(service_account_json, str) else service_account_json
            creds = service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=['https://www.googleapis.com/auth/androidpublisher']
            )
            service = build('androidpublisher', 'v3', credentials=creds)

            # Pour un produit consommable (recharge)
            result = service.purchases().products().get(
                packageName=package_name,
                productId=sku,
                token=purchase_token,
            ).execute()

            # purchaseState: 0 = acheté, 1 = annulé
            if result.get('purchaseState') == 0:
                return True, "Achat valide"
            else:
                return False, f"État achat: {result.get('purchaseState')}"
        except Exception as e:
            return False, str(e)

    def _mobile_money(self, request, moyen):
        """Recharge via MTN MoMo ou Orange Money."""
        from django.conf import settings
        montant   = request.data.get('montant')
        telephone = request.data.get('telephone', '').strip()

        try:
            montant = int(montant)
            if montant < 500:
                return Response({'detail': 'Montant minimum: 500 FCFA'}, status=400)
        except (TypeError, ValueError):
            return Response({'detail': 'Montant invalide'}, status=400)

        if not telephone:
            return Response({'detail': 'telephone requis'}, status=400)

        # En mode DEBUG → simuler le succès
        if settings.DEBUG:
            wallet = YekiWallet.get_or_create_wallet(request.user)
            ref = f"SIM-{uuid.uuid4().hex[:10].upper()}"
            wallet.crediter(
                montant=montant,
                description=f'Recharge {moyen.upper()} (simulation)',
                reference=ref,
            )
            return Response({
                'statut': 'succes',
                'solde':  wallet.solde,
                'montant': montant,
                'reference': ref,
                'detail': f'Wallet rechargé de {montant} FCFA (simulation DEBUG).',
            })

        # En production → intégrer SDK MTN / Orange
        return Response({
            'detail': 'Intégration Mobile Money non configurée. Contactez le support.',
        }, status=503)


class WalletPayerView(APIView):
    """
    POST /api/wallet/payer/
    Body: {
      "type": "cours"|"formation"|"olympiade"|"ia",
      "objet_id": 5,
      "montant": 2000
    }
    Débite le wallet de l'utilisateur.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        type_achat = request.data.get('type', '').strip()
        objet_id   = request.data.get('objet_id')
        montant    = request.data.get('montant')

        try:
            montant = int(montant)
            if montant <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response({'detail': 'Montant invalide'}, status=400)

        wallet = YekiWallet.get_or_create_wallet(request.user)

        if not wallet.peut_debiter(montant):
            return Response({
                'detail': f'Solde insuffisant. Solde actuel: {wallet.solde} FCFA. Requis: {montant} FCFA.',
                'solde':  wallet.solde,
                'requis': montant,
            }, status=402)

        descriptions = {
            'cours':      f'Accès cours #{objet_id}',
            'formation':  f'Accès formation #{objet_id}',
            'olympiade':  f'Inscription olympiade #{objet_id}',
            'ia':         f'Session Yéki IA #{objet_id}',
        }
        description = descriptions.get(type_achat, f'Paiement {type_achat}')
        wallet.debiter(montant=montant, description=description)

        # Enregistrer dans Paiement
        type_map = {
            'cours': 'acces_departement',
            'formation': 'acces_departement',
            'olympiade': 'olympiade',
            'ia': 'acces_departement',
        }
        Paiement.objects.create(
            utilisateur=request.user,
            type_paiement=type_map.get(type_achat, 'acces_departement'),
            moyen='wallet',
            montant=montant,
            statut='succes',
            transaction_id=f"WALLET-{uuid.uuid4().hex[:10].upper()}",
        )

        return Response({
            'statut':  'succes',
            'solde':   wallet.solde,
            'debite':  montant,
            'detail':  f'{description} payé avec succès.',
        })


class WalletVerifierIAPView(APIView):
    """
    POST /api/wallet/verifier-iap/
    Webhook appelé par le frontend après achat Google Play.
    Body: { "purchase_token": "...", "sku": "yeki_recharge_5000", "platform": "android" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Déléguer à WalletRechargerView._google_play()
        request.data._mutable = True if hasattr(request.data, '_mutable') else None
        moyen_orig = request.data.get('moyen')
        request.data['moyen'] = 'google_play'
        view = WalletRechargerView()
        view.request = request
        view.format_kwarg = None
        return view._google_play(request)


# ---------------------------
# Dashboard selon rôle
# ---------------------------
# views.py - get_dashboard_data version CORRIGÉE

#@api_view(['GET'])
#@permission_classes([IsAuthenticated])
def get_dashboard_data(request):
    """
    GET /api/enseignant/dashboard/
    Retourne les données du dashboard selon le rôle de l'utilisateur.
    """
    try:
        # Vérification explicite de l'authentification
        if not request.user.is_authenticated:
            return Response(
                {'error': 'Utilisateur non authentifié'}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Récupération du profil
        try:
            profile = Profile.objects.get(user=request.user)
        except Profile.DoesNotExist:
            return Response(
                {'error': 'Profil introuvable pour cet utilisateur'}, 
                status=status.HTTP_404_NOT_FOUND
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Erreur dans get_dashboard_data: {e}")
        return Response(
            {'error': f'Erreur serveur: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    role = getattr(profile, "user_type", None)
    
    # Construction des données
    data = {
        "role": role, 
        "nom": f"{profile.user.first_name} {profile.user.last_name}".strip() or profile.user.username
    }

    try:
        if role == "admin":
            parcours = Parcours.objects.select_related("admin").all()
            data["parcours"] = ParcoursSerializer(parcours, many=True).data

        elif role == "enseignant_admin":
            parcours = Parcours.objects.filter(admin=profile)
            data["parcours"] = ParcoursSerializer(parcours, many=True).data

        elif role == "enseignant_cadre":
            departements = Departement.objects.filter(cadre=profile)
            data["departements"] = DepartementSerializer(departements, many=True).data

        elif role == "enseignant_principal":
            cours = Cours.objects.filter(enseignant_principal=profile)
            data["cours"] = CoursSerializer(cours, many=True).data

        elif role == "enseignant":
            cours = profile.cours_secondaires.all()
            data["cours"] = CoursSerializer(cours, many=True).data

        else:
            return Response(
                {'error': f'Rôle non géré: {role}'}, 
                status=status.HTTP_403_FORBIDDEN
            )

        # Retourner la réponse avec le status 200 et le content-type JSON
        return Response(data, status=status.HTTP_200_OK)
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Erreur lors du chargement des données: {e}")
        return Response(
            {'error': f'Erreur lors du chargement des données: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ---------------------------
# Landing page
# ---------------------------
def landing(request):
    return render(request, 'landing-page.html')


# ---------------------------
# Register
# ---------------------------

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)

        if serializer.is_valid():
            try:
                profile = serializer.save()
                
                token, _ = Token.objects.get_or_create(user=profile.user)

                return Response({
                    'token': token.key,
                    'role': profile.user_type,
                    'user': {
                        'id': profile.user.id,
                        'username': profile.user.username,
                        'email': profile.user.email,
                    }
                }, status=status.HTTP_201_CREATED)
            except Exception as e:
                # Gestion des erreurs inattendues
                return Response({
                    'detail': str(e),
                    'error_type': 'server_error'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # ✅ Formatage des erreurs pour le frontend
        errors = {}
        for field, error_list in serializer.errors.items():
            errors[field] = error_list[0] if error_list else "Champ invalide"

        # Détecter spécifiquement l'erreur email
        if 'email' in errors:
            return Response({
                'detail': errors['email'],
                'error_type': 'email_exists',
                'field': 'email',
                'errors': errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({
            'detail': next(iter(errors.values())) if errors else "Erreur d'inscription",
            'error_type': 'validation_error',
            'errors': errors
        }, status=status.HTTP_400_BAD_REQUEST)

# ---------------------------
# Login
# ---------------------------

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.validated_data['user']
            profile = Profile.objects.get(user=user)

            # Vérifier si le compte est actif
            if not profile.is_active:
                return Response({
                    'detail': '⚠️ Votre compte enseignant est en attente de validation par l\'administrateur.',
                    'error_type': 'account_inactive',
                    'role': profile.user_type,
                }, status=403)

            token, _ = Token.objects.get_or_create(user=user)

            return Response({
                'token': token.key,
                'role': profile.user_type,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                }
            }, status=200)

        return Response(serializer.errors, status=400)
    
# ═══════════════════════════════════════════════════════════════════════════
#  ADDITIONS À views.py — Gestion complète du mot de passe oublié
#  Coller à la fin de votre views.py existant
#
#  3 endpoints :
#    POST /api/auth/forgot-password/         → envoie le code OTP par email
#    POST /api/auth/verify-otp/              → vérifie le code OTP
#    POST /api/auth/reset-password/          → définit le nouveau mot de passe
# ═══════════════════════════════════════════════════════════════════════════


# ───────────────────────────────────────────────────────────────────────────
# ÉTAPE 1 : Demander un code OTP
# POST /api/auth/forgot-password/
# Body : { "email": "utilisateur@example.com" }
#
# Répond toujours 200 même si l'email n'existe pas (sécurité anti-enumération)
# ───────────────────────────────────────────────────────────────────────────
class ForgotPasswordView(APIView):
    permission_classes = []   # public

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()

        if not email:
            return Response(
                {"detail": "L'adresse email est requise."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Réponse générique pour ne pas révéler si l'email existe
        generic_response = Response(
            {"detail": "Si cet email est enregistré, vous recevrez un code de vérification."},
            status=status.HTTP_200_OK,
        )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return generic_response

        # Invalider tous les OTP précédents non utilisés de cet utilisateur
        PasswordResetOTP.objects.filter(user=user, used=False).update(used=True)

        # Créer un nouvel OTP (le code est généré dans le save())
        otp = PasswordResetOTP.objects.create(user=user)

        # ── Envoyer l'email ───────────────────────────────────────
        try:
            _envoyer_email_otp(user, otp.code)
        except Exception as e:
            # Ne pas bloquer si l'email échoue — log l'erreur
            import logging
            logging.getLogger(__name__).error(f"Erreur envoi OTP email: {e}")
            # En développement, renvoyer le code dans la réponse pour tests
            if settings.DEBUG:
                return Response(
                    {
                        "detail": "Email non envoyé (mode DEBUG). Code OTP pour test :",
                        "debug_code": otp.code,
                        "expires_in_minutes": 10,
                    },
                    status=status.HTTP_200_OK,
                )

        return generic_response


def _envoyer_email_otp(user, code):
    """Envoie l'email contenant le code OTP."""
    nom = f"{user.first_name} {user.last_name}".strip() or user.username

    sujet = "🔐 Votre code de vérification Yéki"

    message_texte = f"""
Bonjour {nom},

Vous avez demandé la réinitialisation de votre mot de passe sur Yéki.

Votre code de vérification est : {code}

Ce code est valable pendant 10 minutes.
Si vous n'avez pas fait cette demande, ignorez cet email.

— L'équipe Yéki
"""

    message_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
    .container {{ max-width: 480px; margin: 40px auto; background: white;
                  border-radius: 16px; overflow: hidden;
                  box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #2884A9, #2A657D);
               padding: 32px 24px; text-align: center; }}
    .header h1 {{ color: white; margin: 0; font-size: 22px; }}
    .header p  {{ color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 14px; }}
    .body   {{ padding: 32px 24px; text-align: center; }}
    .greeting {{ color: #1E293B; font-size: 15px; margin-bottom: 24px; }}
    .code-box {{ background: #F1F5F9; border: 2px dashed #2884A9;
                 border-radius: 12px; padding: 20px; margin: 0 auto;
                 display: inline-block; min-width: 200px; }}
    .code {{ font-size: 38px; font-weight: bold; letter-spacing: 10px;
             color: #2884A9; font-family: monospace; }}
    .validity {{ color: #64748B; font-size: 12px; margin-top: 8px; }}
    .note  {{ color: #94A3B8; font-size: 11px; margin-top: 28px;
               border-top: 1px solid #E2E8F0; padding-top: 16px; }}
    .footer {{ background: #F8FAFC; padding: 16px; text-align: center;
               color: #94A3B8; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🔐 Code de vérification</h1>
      <p>Réinitialisation de mot de passe</p>
    </div>
    <div class="body">
      <p class="greeting">Bonjour <strong>{nom}</strong>,<br>
      Voici votre code pour réinitialiser votre mot de passe.</p>

      <div class="code-box">
        <div class="code">{code}</div>
        <div class="validity">⏱ Valable 10 minutes</div>
      </div>

      <p class="note">
        Si vous n'avez pas demandé la réinitialisation de votre mot de passe,
        ignorez cet email. Votre compte reste sécurisé.
      </p>
    </div>
    <div class="footer">© Yeki — Plateforme éducative</div>
  </div>
</body>
</html>
"""

    send_mail(
        subject      = sujet,
        message      = message_texte,
        from_email   = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@yeki.app'),
        recipient_list = [user.email],
        html_message = message_html,
        fail_silently = False,
    )


# ───────────────────────────────────────────────────────────────────────────
# ÉTAPE 2 : Vérifier le code OTP
# POST /api/auth/verify-otp/
# Body : { "email": "...", "code": "123456" }
#
# Retourne un token temporaire si le code est correct.
# Ce token sera envoyé avec la requête de reset.
# ───────────────────────────────────────────────────────────────────────────
class VerifyOTPView(APIView):
    permission_classes = []   # public

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        code  = (request.data.get('code')  or '').strip()

        if not email or not code:
            return Response(
                {"detail": "Email et code sont requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Récupérer l'utilisateur
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response(
                {"detail": "Code invalide ou expiré."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Récupérer le dernier OTP actif
        otp = PasswordResetOTP.objects.filter(
            user=user, used=False
        ).order_by('-created_at').first()

        if otp is None:
            return Response(
                {"detail": "Aucun code en attente. Faites une nouvelle demande."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Vérifier expiration
        if not otp.is_valid:
            if otp.attempts >= 5:
                return Response(
                    {"detail": "Trop de tentatives. Demandez un nouveau code."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {"detail": "Ce code a expiré. Demandez un nouveau code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Incrémenter les tentatives
        otp.attempts += 1
        otp.save(update_fields=['attempts'])

        # Vérifier le code
        if otp.code != code:
            remaining = 5 - otp.attempts
            if remaining <= 0:
                otp.used = True
                otp.save(update_fields=['used'])
                return Response(
                    {"detail": "Code incorrect. Trop de tentatives. Demandez un nouveau code."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {"detail": f"Code incorrect. {remaining} tentative(s) restante(s)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Code correct → générer un reset_token temporaire ─────
        import secrets
        reset_token = secrets.token_urlsafe(32)

        # Stocker le token dans l'OTP (on réutilise le champ code)
        otp.code = f"VERIFIED:{reset_token}"
        otp.save(update_fields=['code'])

        return Response({
            "detail": "Code vérifié avec succès.",
            "reset_token": reset_token,
        }, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    permission_classes = []   # public

    def post(self, request):
        email           = (request.data.get('email')           or '').strip().lower()
        reset_token     = (request.data.get('reset_token')     or '').strip()
        new_password    = (request.data.get('new_password')    or '').strip()
        confirm_password= (request.data.get('confirm_password') or '').strip()

        # ── Validation des champs ─────────────────────────────────
        if not all([email, reset_token, new_password, confirm_password]):
            return Response(
                {"detail": "Tous les champs sont requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_password != confirm_password:
            return Response(
                {"detail": "Les mots de passe ne correspondent pas."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(new_password) < 8:
            return Response(
                {"detail": "Le mot de passe doit contenir au moins 8 caractères."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Vérification de la complexité ────────────────────────
        has_digit = any(c.isdigit() for c in new_password)
        has_alpha = any(c.isalpha() for c in new_password)
        if not (has_digit and has_alpha):
            return Response(
                {"detail": "Le mot de passe doit contenir au moins une lettre et un chiffre."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Récupérer l'utilisateur ───────────────────────────────
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response(
                {"detail": "Lien de réinitialisation invalide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Vérifier le reset_token ───────────────────────────────
        otp = PasswordResetOTP.objects.filter(
            user=user,
            used=False,
            code=f"VERIFIED:{reset_token}",
        ).order_by('-created_at').first()

        if otp is None or not otp.is_valid:
            return Response(
                {"detail": "Lien de réinitialisation invalide ou expiré. Recommencez."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Mettre à jour le mot de passe ─────────────────────────
        user.set_password(new_password)
        user.save()

        # Invalider l'OTP
        otp.used = True
        otp.save(update_fields=['used'])

        # Supprimer tous les anciens tokens d'auth → force une nouvelle connexion
        from rest_framework.authtoken.models import Token as AuthToken
        AuthToken.objects.filter(user=user).delete()

        # ── Email de confirmation ─────────────────────────────────
        try:
            _envoyer_email_confirmation(user)
        except Exception:
            pass   # Ne pas bloquer si l'email de confirmation échoue

        return Response(
            {"detail": "Mot de passe réinitialisé avec succès. Connectez-vous avec votre nouveau mot de passe."},
            status=status.HTTP_200_OK,
        )


def _envoyer_email_confirmation(user):
    """Email de confirmation après changement réussi."""
    nom = f"{user.first_name} {user.last_name}".strip() or user.username
    from django.utils import timezone
    now_str = timezone.now().strftime('%d/%m/%Y à %H:%M')

    send_mail(
        subject  = "✅ Mot de passe modifié — Yeki",
        message  = f"Bonjour {nom},\n\nVotre mot de passe a été modifié le {now_str}.\nSi ce n'est pas vous, contactez-nous immédiatement.\n\n— L'équipe Yeki",
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@yeki.app'),
        recipient_list = [user.email],
        fail_silently  = True,
    )


# ---------------------------
# Listes publiques simples
# ---------------------------
@api_view(['GET'])
#@permission_classes([IsAuthenticated])
def liste_parcours(request):
    parcours = Parcours.objects.select_related('admin').all()
    serializer = ParcoursSerializer(parcours, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
#@permission_classes([IsAuthenticated])
def parcours_unique(request, parcours_id):
    parcours = Parcours.objects.get(id=parcours_id)
    serializer = ParcoursSerializer(parcours)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
#@permission_classes([IsAuthenticated])
def liste_enseignants_principaux(request):
    qs = Profile.objects.filter(user_type='enseignant_principal')
    serializer = EnseignantSerializer(qs, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


# ---------------------------
# Statistiques globales (exemples)
# ---------------------------
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def statistiques_globales(request):
    total_apprenants = Parcours.objects.aggregate(Sum('apprenants'))['apprenants__sum'] or 0
    total_cours = Parcours.objects.aggregate(Sum('cours'))['cours__sum'] or 0
    moyenne_globale = Parcours.objects.aggregate(Avg('moyenne'))['moyenne__avg'] or 0.0

    return Response({
        "total_apprenants": total_apprenants,
        "total_cours": total_cours,
        "moyenne_globale": round(moyenne_globale, 2)
    }, status=status.HTTP_200_OK)


class LogoutView(APIView):
    #permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # Si JWT : invalider le token côté serveur
            # Si Token : supprimer le token
            request.user.auth_token.delete()
        except:
            pass
        return Response({"detail": "Déconnecté avec succès"}, status=status.HTTP_200_OK)
