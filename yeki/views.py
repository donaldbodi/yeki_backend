# views.py
from django.shortcuts import render, get_object_or_404
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from django.contrib.auth.hashers import check_password
import uuid
import os
import openai


from django.contrib.auth import get_user_model
from django.db.models import Sum, Avg

from .models import *
from .serializers import *

User = get_user_model()


openai.api_key = os.environ.get('OPENAI_API_KEY', '')
YEKI_COMMISSION_RATE = 0.15  # 15% de commission sur les formations payantes

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
        profile = request.user.profile

        if profile.user_type != 'apprenant':
            return Response(
                {"detail": "Accès réservé aux apprenants"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not profile.cursus:
            return Response([], status=status.HTTP_200_OK)

        cours_qs = Cours.objects.filter(
            departement__parcours__nom=profile.cursus
        ).select_related('enseignant_principal__user')

        # Récupérer les progressions de cet apprenant en une seule requête
        try:
            from .models import ProgressionLecon
            progressions = ProgressionLecon.objects.filter(
                apprenant=request.user,
                cours__in=cours_qs,
            ).values('cours_id', 'terminee')

            # Calculer le taux de complétion par cours
            from django.db.models import Count, Q
            prog_map = {}
            for c in cours_qs:
                total_lecons = c.nb_lecons or Lecon.objects.filter(cours=c).count()
                if total_lecons == 0:
                    prog_map[c.id] = 0.0
                    continue
                terminees = sum(
                    1 for p in progressions
                    if p['cours_id'] == c.id and p['terminee']
                )
                prog_map[c.id] = round((terminees / total_lecons) * 100, 1)
        except Exception:
            prog_map = {}

        result = []
        for c in cours_qs:
            ep_nom = '—'
            if c.enseignant_principal:
                ep = c.enseignant_principal
                ep_nom = f"{ep.user.first_name} {ep.user.last_name}".strip() \
                         or ep.user.username

            result.append({
                'id':                   c.id,
                'title':                c.titre,
                'description':          c.description_brief or '',
                'enseignant_principal': ep_nom,
                'lessons':              c.nb_lecons,
                'assignments':          c.nb_devoirs,
                'icon':                 c.icon_name or 'school',
                'color':                c.color_code or '#2884A0',
                'progression':          prog_map.get(c.id, 0.0),
            })

        return Response(result, status=status.HTTP_200_OK)


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


class ListeExercicesCoursView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        exercices = Exercice.objects.filter(cours_id=cours_id).prefetch_related("questions__choix")
        serializer = ExerciceSerializer(exercices, many=True)
        return Response(serializer.data)


class SoumettreEvaluationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, exercice_id):
        user = request.user
        exercice = get_object_or_404(Exercice, id=exercice_id)

        session = get_object_or_404(
            SessionExercice,
            user=user,
            exercice=exercice,
            termine=False
        )

        # ⛔ Vérifier chrono expiré
        if session.temps_restant() <= 0:
            session.termine = True
            session.save()
            return Response(
                {"detail": "Temps écoulé. Examen terminé."},
                status=403
            )

        reponses = request.data.get("reponses", {})
        score = 0
        total = 0

        for question in exercice.questions.all():
            bonne = question.bonne_reponse.lower().strip()

            # support id OU texte (compatibilité Flutter)
            user_rep = (
                reponses.get(str(question.id)) or
                reponses.get(question.text) or
                ""
            ).lower().strip()

            total += question.points
            if user_rep == bonne:
                score += question.points

        EvaluationExercice.objects.create(
            user=user,
            exercice=exercice,
            score=score,
            total=total
        )

        session.termine = True
        session.save()

        return Response({
            "score": score,
            "total": total,
            "message": "Examen soumis avec succès",
        })

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

        # 🔒 Anti-triche : vérifier tentatives
        tentatives = EvaluationExercice.objects.filter(
            user=user, exercice=exercice
        ).count()

        if tentatives >= exercice.tentatives_max:
            return Response(
                {"detail": "Nombre maximum de tentatives atteint."},
                status=403
            )

        # 🔁 Vérifier session existante non terminée
        session = SessionExercice.objects.filter(
            user=user, exercice=exercice, termine=False
        ).first()

        if not session:
            session = SessionExercice.objects.create(
                user=user,
                exercice=exercice
            )

        serializer = SessionSerializer(session)
        return Response(serializer.data)


class ExerciceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, exercice_id):
        user = request.user
        exercice = get_object_or_404(
            Exercice.objects.prefetch_related("questions__choix"),
            id=exercice_id
        )

        # session en cours
        session = SessionExercice.objects.filter(
            user=user,
            exercice=exercice,
            termine=False
        ).first()

        data = ExerciceSerializer(exercice).data

        if session:
            data["temps_restant"] = session.temps_restant()
        else:
            data["temps_restant"] = exercice.duree

        return Response(data, status=status.HTTP_200_OK)


class AjouterExerciceView(APIView):

    permission_classes = [IsAuthenticated]

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

        serializer = ExerciceCreateSerializer(data=request.data)
        if serializer.is_valid():
            exercice = serializer.save(cours=cours)
            enregistrer_activite(
       user=request.user,
       action='exercise_created',
       description=f"Exercice « {exercice.titre} » ajouté au cours « {cours.titre} »",
       data={'exercice': exercice.titre, 'cours': cours.titre, 'etoiles': exercice.etoiles},
       objet_id=exercice.id,
       objet_type='Exercice',
   )
            cours.nb_devoirs += 1
            cours.save(update_fields=['nb_devoirs'])
            return Response(
                ExerciceSerializer(exercice).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

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


# ═══════════════════════════════════════════════════════════════════════════
#  AJOUTS À views.py — Gestion complète des devoirs (enseignant principal)
#  À coller dans votre views.py existant
# ═══════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# 1. CRÉER UN DEVOIR LIÉ À UN COURS
#    POST /api/cours/<cours_id>/devoirs/creer/
# ─────────────────────────────────────────────────────────────────────────────
class CreerDevoirCoursView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut créer un devoir."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy()
        data['type_devoir'] = data.get('type_devoir', 'cursus')
        data['cours_lie']   = cours.id
        data['est_publie']  = data.get('est_publie', True)

        # Champ type_correction stocké dans description ou champ dédié
        type_correction = data.pop('type_correction', 'auto')

        serializer = DevoirCreateSerializer(data=data)
        if serializer.is_valid():
            devoir = serializer.save()
            enregistrer_activite(
       user=request.user,
       action='homework_created',
       description=f"Devoir « {devoir.titre} » créé pour le cours « {cours.titre} »",
       data={
           'devoir':       devoir.titre,
           'cours':        cours.titre,
           'date_limite':  devoir.date_limite.strftime('%d/%m/%Y') if devoir.date_limite else '',
           'nb_questions': devoir.questions.count(),
       },
       objet_id=devoir.id,
       objet_type='Devoir',
   )

            # Stocker type_correction (si champ existe dans le modèle)
            if hasattr(devoir, 'type_correction'):
                devoir.type_correction = type_correction
                devoir.save(update_fields=['type_correction'])

            # MAJ compteur
            cours.nb_devoirs = Devoir.objects.filter(
                cours_lie=cours, est_publie=True
            ).count()
            cours.save(update_fields=['nb_devoirs'])

            return Response(
                _devoir_to_dict(devoir, request.user),
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
# 7. SOUMISSION APPRENANT AVEC FICHIER PDF (correction manuelle)
#    POST /api/devoirs/<devoir_id>/soumettre-fichier/
# ─────────────────────────────────────────────────────────────────────────────
class SoumettreDevoirFichierView(APIView):
    """
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
        # Assurez-vous que SoumissionDevoir a un champ `fichier_soumis`
        if hasattr(soum, 'fichier_soumis'):
            soum.fichier_soumis = fichier
        
        now = timezone.now()
        soum.statut    = 'en_retard' if soum.est_en_retard else 'soumis'
        soum.soumis_le = now
        soum.save()

        return Response({
            "statut":    soum.statut,
            "message":   "Fichier soumis avec succès. En attente de correction.",
            "soumis_le": soum.soumis_le.isoformat(),
        })


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


# GET tous les messages + réponses
class ForumMessagesListAPIView(generics.ListAPIView):
    serializer_class = ForumMessageSerializer

    def get_queryset(self):
        cours_id = self.request.query_params.get('cours_id')
        if cours_id:
            return ForumMessage.objects.filter(cours_id=cours_id, parent=None).order_by('-timestamp')
        return ForumMessage.objects.filter(parent=None).order_by('-timestamp')


# POST nouvelle question ou réponse
class ForumMessageCreateAPIView(generics.CreateAPIView):
    serializer_class = ForumMessageSerializer
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        data = request.data.copy()
        user = request.user
        data['sender'] = user.id

        serializer = ForumMessageSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

# ─────────────────────────────────────────────────────────────────
# GET  /api/forum/questions/          → liste des questions
# POST /api/forum/questions/          → créer une question
# ─────────────────────────────────────────────────────────────────
class ListeQuestionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = QuestionForum.objects.all()

        # Filtres
        source    = request.query_params.get("source")
        lecon_id  = request.query_params.get("lecon_id")
        exo_id    = request.query_params.get("exercice_id")
        devoir_id = request.query_params.get("devoir_id")
        cours_id  = request.query_params.get("cours_id")
        resolue   = request.query_params.get("resolue")
        since     = request.query_params.get("since")   # ISO timestamp pour polling temps réel

        if source:
            qs = qs.filter(source=source)
        if lecon_id:
            qs = qs.filter(lecon_id=lecon_id)
        if exo_id:
            qs = qs.filter(exercice_id=exo_id)
        if devoir_id:
            qs = qs.filter(devoir_id=devoir_id)
        if cours_id:
            qs = qs.filter(cours_id=cours_id)
        if resolue is not None:
            qs = qs.filter(est_resolue=(resolue == "true"))
        if since:
            qs = qs.filter(cree_le__gt=since)

        # Annoter nb_reponses
        from django.db.models import Count
        qs = qs.annotate(nb_reponses=Count("reponses"))

        serializer = QuestionForumListSerializer(
            qs, many=True, context={"request": request}
        )
        return Response(serializer.data)

    def post(self, request):
        serializer = QuestionForumCreateSerializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            question = serializer.save()
            return Response(
                QuestionForumListSerializer(question, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────────────────────────────
# GET  /api/forum/questions/<pk>/     → détail + réponses
# DELETE /api/forum/questions/<pk>/   → supprimer (auteur seulement)
# ─────────────────────────────────────────────────────────────────
class DetailQuestionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            question = QuestionForum.objects.get(pk=pk)
        except QuestionForum.DoesNotExist:
            return Response({"detail": "Question introuvable."}, status=404)

        # Incrémenter les vues
        QuestionForum.objects.filter(pk=pk).update(nb_vues=question.nb_vues + 1)
        question.refresh_from_db()

        serializer = QuestionForumDetailSerializer(question, context={"request": request})
        return Response(serializer.data)

    def delete(self, request, pk):
        try:
            question = QuestionForum.objects.get(pk=pk, auteur=request.user)
        except QuestionForum.DoesNotExist:
            return Response(status=404)
        question.delete()
        return Response(status=204)


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

        serializer = ReponseCreateSerializer(
            data=request.data,
            context={"request": request, "question": question},
        )
        if serializer.is_valid():
            reponse = serializer.save()
            return Response(
                ReponseSerializer(reponse, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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

        # ── Département unique du cadre ───────────────────────────
        departement = Departement.objects.filter(
            cadre=profile
        ).select_related('parcours').first()

        if departement is None:
            # Cadre non encore affecté à un département
            nom_complet = (
                f"{profile.user.first_name} {profile.user.last_name}".strip()
                or profile.user.username
            )
            return Response({
                "nom":                   nom_complet,
                "departement":           {},
                "cours":                 [],
                "enseignants_principaux": [],
                "stats": {
                    "nb_cours":       0,
                    "nb_apprenants":  0,
                    "nb_enseignants": 0,
                    "taux_moyen":     0,
                },
            }, status=status.HTTP_200_OK)

        # ── Cours du département ──────────────────────────────────
        cours_qs = Cours.objects.filter(
            departement=departement
        ).select_related('enseignant_principal__user')

        cours_data = []
        for c in cours_qs:
            ep_data = None
            if c.enseignant_principal:
                ep = c.enseignant_principal
                ep_data = {
                    "id":       ep.id,
                    "nom":      f"{ep.user.first_name} {ep.user.last_name}".strip()
                                or ep.user.username,
                    "username": ep.user.username,
                    "photo":    request.build_absolute_uri(ep.avatar.url)
                                if ep.avatar else None,
                }
            cours_data.append({
                "id":               c.id,
                "titre":            c.titre,
                "niveau":           c.niveau,
                "nb_apprenants":    c.nb_apprenants,
                "taux_completion":  0,          # calculer si tu as le modèle de progression
                "color_code":       c.color_code,
                "icon_name":        c.icon_name,
                "enseignant_principal": ep_data,
            })

        # ── Enseignants principaux distincts + leurs stats ────────
        ep_ids_vus = set()
        enseignants_principaux = []

        for c in cours_qs:
            if c.enseignant_principal is None:
                continue
            ep = c.enseignant_principal
            if ep.id in ep_ids_vus:
                continue
            ep_ids_vus.add(ep.id)

            nb_cours_ep   = Cours.objects.filter(
                enseignant_principal=ep,
                departement=departement
            ).count()
            nb_app_ep     = sum(
                co.nb_apprenants
                for co in Cours.objects.filter(
                    enseignant_principal=ep,
                    departement=departement
                )
            )

            # Score moyen à partir des évaluations d'exercices
            from django.db.models import Avg
            avg = EvaluationExercice.objects.filter(
                exercice__cours__enseignant_principal=ep,
                exercice__cours__departement=departement
            ).aggregate(moy=Avg('score'))['moy']

            score_moyen = round((avg or 0) / 20 * 20, 1)   # ramener sur 20

            enseignants_principaux.append({
                "id":          ep.id,
                "nom":         f"{ep.user.first_name} {ep.user.last_name}".strip()
                               or ep.user.username,
                "username":    ep.user.username,
                "email":       ep.user.email,
                "photo":       request.build_absolute_uri(ep.avatar.url)
                               if ep.avatar else None,
                "nb_cours":    nb_cours_ep,
                "nb_apprenants": nb_app_ep,
                "score_moyen": score_moyen,
            })

        # ── Stats globales du département ─────────────────────────
        nb_cours      = len(cours_data)
        # Calcul dynamique : apprenants dont profile.cursus == nom du parcours
        parcours_nom  = departement.parcours.nom if departement.parcours else ''
        nb_apprenants = _nb_apprenants_pour_parcours(parcours_nom)
        nb_enseignants = len(enseignants_principaux)
        taux_moyen    = (
            sum(c["taux_completion"] for c in cours_data) / nb_cours
            if nb_cours > 0 else 0
        )

        # ── Infos département ─────────────────────────────────────
        dept_data = {
            "id":          departement.id,
            "nom":         departement.nom,
            "description": getattr(departement, 'description', ''),
            "parcours":    departement.parcours.nom if departement.parcours else "",
            "parcours_id": departement.parcours.id  if departement.parcours else None,
        }

        nom_complet = (
            f"{profile.user.first_name} {profile.user.last_name}".strip()
            or profile.user.username
        )

        return Response({
            "nom":                   nom_complet,
            "departement":           dept_data,
            "cours":                 cours_data,
            "enseignants_principaux": enseignants_principaux,
            "stats": {
                "nb_cours":       nb_cours,
                "nb_apprenants":  nb_apprenants,
                "nb_enseignants": nb_enseignants,
                "taux_moyen":     round(taux_moyen, 1),
            },
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
        # ── Récupérer le profil ──────────────────────────────────
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        # ── Vérifier le rôle ─────────────────────────────────────
        if profile.user_type != 'enseignant_cadre':
            return Response(
                {"detail": "Seuls les enseignants cadres peuvent créer des olympiades."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data

        # ── Validation des champs obligatoires ───────────────────
        titre = (data.get('titre') or '').strip()
        if not titre:
            return Response(
                {"detail": "Le titre est obligatoire."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        matiere = (data.get('matiere') or '').strip()
        if not matiere:
            return Response(
                {"detail": "La matière est obligatoire."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        niveau = (data.get('niveau') or '').strip()
        if not niveau:
            return Response(
                {"detail": "Le niveau est obligatoire."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Validation du département ─────────────────────────────
        departement_id = data.get('departement_id')
        if not departement_id:
            return Response(
                {"detail": "departement_id est obligatoire."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        departement = get_object_or_404(Departement, pk=departement_id)

        # Sécurité : le cadre ne peut créer que pour SON département
        if departement.cadre != profile:
            return Response(
                {"detail": "Ce département ne vous appartient pas."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Validation des dates ──────────────────────────────────
        from django.utils.dateparse import parse_datetime

        def _parse_date(field_name):
            raw = data.get(field_name)
            if not raw:
                return None, f"Le champ '{field_name}' est obligatoire."
            parsed = parse_datetime(str(raw))
            if not parsed:
                return None, f"Format de date invalide pour '{field_name}'. Utilisez ISO 8601."
            # Rendre timezone-aware si nécessaire
            from django.utils import timezone as tz
            if tz.is_naive(parsed):
                from django.conf import settings
                import pytz
                try:
                    local_tz = pytz.timezone(settings.TIME_ZONE)
                    parsed = local_tz.localize(parsed)
                except Exception:
                    parsed = tz.make_aware(parsed)
            return parsed, None

        date_ouv_insc, err = _parse_date('date_ouverture_inscription')
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)

        date_clo_insc, err = _parse_date('date_cloture_inscription')
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)

        date_debut, err = _parse_date('date_debut_olympiade')
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)

        date_fin, err = _parse_date('date_fin_olympiade')
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)

        # ── Cohérence des dates ───────────────────────────────────
        if date_clo_insc >= date_debut:
            return Response(
                {"detail": "La clôture des inscriptions doit être avant le début de l'olympiade."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if date_debut >= date_fin:
            return Response(
                {"detail": "Le début de l'olympiade doit être avant sa fin."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if date_ouv_insc >= date_clo_insc:
            return Response(
                {"detail": "L'ouverture des inscriptions doit être avant leur clôture."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Paramètres de composition ─────────────────────────────
        try:
            duree_minutes = int(data.get('duree_minutes', 120))
            if duree_minutes < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"detail": "duree_minutes doit être un entier positif."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            nb_questions = int(data.get('nb_questions', 30))
            if nb_questions < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"detail": "nb_questions doit être un entier positif."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            max_focus = int(data.get('max_focus_perdu', 3))
            if max_focus < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"detail": "max_focus_perdu doit être un entier positif."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        melanger_questions = bool(data.get('melanger_questions', True))
        melanger_choix     = bool(data.get('melanger_choix', True))
        une_seule_session  = bool(data.get('une_seule_session', True))

        # ── Création de l'olympiade ───────────────────────────────
        olympiade = Olympiade.objects.create(
            titre                      = titre,
            description                = (data.get('description') or '').strip(),
            edition                    = (data.get('edition') or '').strip(),
            matiere                    = matiere,
            niveau                     = niveau,
            date_ouverture_inscription = date_ouv_insc,
            date_cloture_inscription   = date_clo_insc,
            date_debut_olympiade       = date_debut,
            date_fin_olympiade         = date_fin,
            duree_minutes              = duree_minutes,
            nb_questions               = nb_questions,
            max_focus_perdu            = max_focus,
            melanger_questions         = melanger_questions,
            melanger_choix             = melanger_choix,
            une_seule_session          = une_seule_session,
            prix_1er                   = (data.get('prix_1er') or '').strip(),
            prix_2eme                  = (data.get('prix_2eme') or '').strip(),
            prix_3eme                  = (data.get('prix_3eme') or '').strip(),
            note_sur                   = 20,
            organisateur               = profile,
            cree_par                   = request.user,
        )

        # ── Créer automatiquement un Devoir lié (pour les questions) ──
        # L'enseignant cadre pourra ensuite ajouter des questions via
        # /api/devoirs/<devoir_id>/questions/ajouter/

        devoir_lie = Devoir.objects.create(
            titre        = f"[Olympiade] {titre}",
            description  = f"Devoir lié à l'olympiade : {titre}",
            type_devoir  = 'olympiade',
            matiere      = matiere,
            niveau       = niveau,
            enonce       = f"Questions de l'olympiade {titre}",
            date_debut   = date_debut,
            date_limite  = date_fin,
            duree_minutes= duree_minutes,
            note_sur     = 20,
            est_publie   = False,   # Géré par la logique olympiade
            cree_par     = profile,
        )
        olympiade.devoir = devoir_lie
        olympiade.save(update_fields=['devoir'])

        enregistrer_activite(
       user=request.user,
       action='olympiad_created',
       description=f"Olympiade « {olympiade.titre} » créée",
       data={
           'titre':   olympiade.titre,
           'matiere': olympiade.matiere,
           'niveau':  olympiade.niveau,
           'edition': olympiade.edition,
           'debut':   olympiade.date_debut_olympiade.strftime('%d/%m/%Y'),
       },
       objet_id=olympiade.id,
       objet_type='Olympiade',
   )

        # ── Réponse ───────────────────────────────────────────────
        return Response({
            "id":                          olympiade.id,
            "titre":                       olympiade.titre,
            "edition":                     olympiade.edition,
            "matiere":                     olympiade.matiere,
            "niveau":                      olympiade.niveau,
            "statut":                      olympiade.statut_auto,
            "date_ouverture_inscription":  olympiade.date_ouverture_inscription.isoformat(),
            "date_cloture_inscription":    olympiade.date_cloture_inscription.isoformat(),
            "date_debut_olympiade":        olympiade.date_debut_olympiade.isoformat(),
            "date_fin_olympiade":          olympiade.date_fin_olympiade.isoformat(),
            "duree_minutes":               olympiade.duree_minutes,
            "nb_questions":                olympiade.nb_questions,
            "devoir_id":                   devoir_lie.id,
            "prix_1er":                    olympiade.prix_1er,
            "prix_2eme":                   olympiade.prix_2eme,
            "prix_3eme":                   olympiade.prix_3eme,
            "detail": (
                "Olympiade créée avec succès. "
                f"Ajoutez les questions via /api/devoirs/{devoir_lie.id}/questions/ajouter/"
            ),
        }, status=status.HTTP_201_CREATED)


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


# new

# ═══════════════════════════════════════════════════════════════════════════
# BLOC À AJOUTER DANS views.py
# Coller ces classes dans views.py (avant ou après les vues existantes)
# ═══════════════════════════════════════════════════════════════════════════


# ───────────────────────────────────────────────────────────────────────────
# ADMIN GÉNÉRAL — Dashboard
# GET /api/admin-general/dashboard/
# ───────────────────────────────────────────────────────────────────────────
class AdminGeneralDashboardView(APIView):
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

        parcours_qs = Parcours.objects.prefetch_related(
            'departements__cours', 'admin__user'
        ).all()

        parcours_data = []
        for p in parcours_qs:
            depts = p.departements.all()
            nb_depts = depts.count()
            nb_app = sum(c.nb_apprenants for d in depts for c in d.cours.all())
            nb_cours = sum(d.cours.count() for d in depts)

            admin_data = None
            if p.admin:
                admin_data = {
                    "id": p.admin.id,
                    "nom": f"{p.admin.user.first_name} {p.admin.user.last_name}".strip()
                          or p.admin.user.username,
                    "username": p.admin.user.username,
                    "email": p.admin.user.email,
                }

            parcours_data.append({
                "id": p.id,
                "nom": p.nom,
                "nb_departements": nb_depts,
                "nb_apprenants": nb_app,
                "nb_cours": nb_cours,
                "taux_moyen": 0,
                "enseignant_admin": admin_data,
            })

        departements_qs = Departement.objects.select_related(
            'parcours', 'cadre__user'
        ).prefetch_related('cours').all()

        depts_data = []
        for d in departements_qs:
            nb_cours = d.cours.count()
            nb_app = sum(c.nb_apprenants for c in d.cours.all())
            depts_data.append({
                "id": d.id,
                "nom": d.nom,
                "parcours": d.parcours.nom if d.parcours else "",
                "nb_cours": nb_cours,
                "nb_apprenants": nb_app,
                "taux_moyen": 0,
            })

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

        nom_complet = (
            f"{profile.user.first_name} {profile.user.last_name}".strip()
            or profile.user.username
        )

        return Response({
            "nom": nom_complet,
            "stats": stats,
            "parcours": parcours_data,
            "departements": depts_data,
            "top_enseignants": [],
        }, status=status.HTTP_200_OK)


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
                {"detail": "Accès réservé à l'administrateur général."},
                status=status.HTTP_403_FORBIDDEN
            )

        nom = request.data.get('nom', '').strip()
        if not nom:
            return Response(
                {"detail": "Le nom du parcours est obligatoire."},
                status=status.HTTP_400_BAD_REQUEST
            )

        parcours = Parcours.objects.create(nom=nom)
        return Response(
            {"id": parcours.id, "nom": parcours.nom},
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
# ENSEIGNANT ADMIN — Dashboard
# GET /api/enseignant/admin/dashboard/
# ───────────────────────────────────────────────────────────────────────────
class EnseignantAdminDashboardView(APIView):
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

        parcours_qs = Parcours.objects.prefetch_related(
            'departements__cours',
            'departements__cadre__user'
        ).get(admin=profile)

        departements_data = []
        cadres_dict = {}

        for dept in parcours_qs.departements.all():
            nb_cours = dept.cours.count()
            nb_app = sum(c.nb_apprenants for c in dept.cours.all())

            cadre_data = None
            if dept.cadre:
                cadre_data = {
                    "id": dept.cadre.id,
                    "nom": f"{dept.cadre.user.first_name} {dept.cadre.user.last_name}".strip()
                          or dept.cadre.user.username,
                    "username": dept.cadre.user.username,
                }
                if dept.cadre.id not in cadres_dict:
                    cadres_dict[dept.cadre.id] = {
                        "id": dept.cadre.id,
                        "nom": cadre_data["nom"],
                        "username": dept.cadre.user.username,
                        "email": dept.cadre.user.email,
                        "nb_cours": nb_cours,
                        "nb_apprenants": nb_app,
                        "taux_moyen": 0,
                        "departement": {"id": dept.id, "nom": dept.nom},
                    }

            departements_data.append({
                "id": dept.id,
                "nom": dept.nom,
                "parcours": parcours_qs.nom,
                "parcours_id": parcours_qs.id,
                "nb_cours": nb_cours,
                "nb_apprenants": nb_app,
                "taux_moyen": 0,
                "cadre": cadre_data,
            })

        stats = {
            "nb_departements": len(departements_data),
            "nb_cours": sum(d["nb_cours"] for d in departements_data),
            "nb_apprenants": sum(d["nb_apprenants"] for d in departements_data),
            "nb_enseignants": len(cadres_dict),
        }

        nom_complet = (
            f"{profile.user.first_name} {profile.user.last_name}".strip()
            or profile.user.username
        )

        return Response({
            "nom": nom_complet,
            "stats": stats,
            "nom_parcours": parcours_qs.nom,
            "id_parcours": parcours_qs.id,
            "departements": departements_data,
            "cadres": list(cadres_dict.values()),
        }, status=status.HTTP_200_OK)


# ───────────────────────────────────────────────────────────────────────────
# ENSEIGNANT ADMIN — Créer un département
# POST /api/departements/creer/
# Body: { "nom": "Mathématiques", "description": "...", "parcours_id": 1 }
#   → parcours_id est OPTIONNEL si l'enseignant admin n'a qu'un seul parcours
# ───────────────────────────────────────────────────────────────────────────
class CreerDepartementView(APIView):
    permission_classes = [IsAuthenticated]

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

        # Résolution du parcours
        parcours_id = request.data.get('parcours_id')
        if parcours_id:
            # Vérifier que ce parcours appartient à cet enseignant admin
            parcours = get_object_or_404(Parcours, pk=parcours_id, admin=profile)
        else:
            # Auto-déduction si un seul parcours assigné
            parcours_qs = Parcours.objects.filter(admin=profile)
            if not parcours_qs.exists():
                return Response(
                    {"detail": "Aucun parcours ne vous est assigné."},
                    status=status.HTTP_403_FORBIDDEN
                )
            if parcours_qs.count() > 1:
                return Response(
                    {
                        "detail": "Vous gérez plusieurs parcours. "
                                  "Veuillez spécifier 'parcours_id' dans la requête."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            parcours = parcours_qs.first()

        departement = Departement.objects.create(nom=nom, parcours=parcours)
        return Response(
            {
                "id": departement.id,
                "nom": departement.nom,
                "parcours": parcours.nom,
                "parcours_id": parcours.id,
            },
            status=status.HTTP_201_CREATED
        )


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


# ---------------------------
# Creation de Departement
# ---------------------------
class DepartementCreateView(generics.CreateAPIView):
    serializer_class = DepartementSerializer
    #permission_classes = [IsAuthenticated]

    def get_target_parcours(self):
        parcours_id = self.request.data.get("parcours")
        if not parcours_id:
            return None
        return Parcours.objects.filter(pk=parcours_id).first()

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        nom = (request.data.get("nom") or "").strip()
        parcours_id = request.data.get("parcours")
        cadre_id = request.data.get("enseignant_cadre", None)

        if not nom:
            return Response({"detail": "Le champ 'nom' est requis."}, status=status.HTTP_400_BAD_REQUEST)
        if not parcours_id:
            return Response({"detail": "Le champ 'parcours' est requis."}, status=status.HTTP_400_BAD_REQUEST)

        parcours = get_object_or_404(Parcours, pk=parcours_id)

        cadre = None
        if cadre_id:
            cadre = get_object_or_404(Profile, pk=cadre_id)
            if getattr(cadre, "user_type", None) != "enseignant_cadre":
                return Response({"detail": "L'utilisateur choisi n'est pas un enseignant_cadre."}, status=status.HTTP_400_BAD_REQUEST)

        dep = Departement.objects.create(nom=nom, parcours=parcours, cadre=cadre)
        data = DepartementSerializer(dep).data
        return Response(data, status=status.HTTP_201_CREATED)


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
# APPRENANT — PRÉPA CONCOURS
# GET /api/apprenant/prepa-concours/
#
# Filtre par profile.sub_cursus, exactement comme ApprenantCursusAPIView
# filtre par profile.cursus.
# L'apprenant voit les départements (= concours) de son parcours Prépa,
# groupés par département, avec les cours à l'intérieur.
# ══════════════════════════════════════════════════════════════════

class ApprenantPrepaConcoursAPIView(APIView):
    """
    GET /api/apprenant/prepa-concours/
    Retourne les départements (concours) du parcours Prépa Concours
    de l'apprenant, groupés par département avec leurs cours.

    Filtre : profile.cursus == nom du Parcours (ex: "Prépa Concours")
    Même logique que ApprenantCursusAPIView.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != 'apprenant':
            return Response(
                {"detail": "Accès réservé aux apprenants."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Filtre identique à ApprenantCursusAPIView : profile.cursus = nom du Parcours
        if not profile.cursus:
            return Response([], status=status.HTTP_200_OK)

        cours_qs = Cours.objects.filter(
            departement__parcours__nom=profile.cursus
        ).select_related(
            'enseignant_principal__user', 'departement__parcours'
        ).order_by('departement__nom', 'titre')

        if not cours_qs.exists():
            return Response([], status=status.HTTP_200_OK)

        prog_map = _progression_cours(request.user, cours_qs)

        # Grouper par département (= concours)
        departements = {}
        for c in cours_qs:
            dept = c.departement
            if dept.id not in departements:
                cadre_data = None
                if dept.cadre:
                    cadre_data = {
                        "id":  dept.cadre.id,
                        "nom": _nom_profil(dept.cadre),
                    }
                departements[dept.id] = {
                    "id":       dept.id,
                    "nom":      dept.nom,
                    "cadre":    cadre_data,
                    "cours":    [],
                    "nb_cours": 0,
                    "progression_moyenne": 0.0,
                }
            departements[dept.id]["cours"].append(_serialise_cours(c, prog_map))

        # Calculer la progression moyenne par département
        result = []
        for dept_data in departements.values():
            progs = [c["progression"] for c in dept_data["cours"]]
            dept_data["progression_moyenne"] = round(
                sum(progs) / len(progs), 1
            ) if progs else 0.0
            dept_data["nb_cours"] = len(dept_data["cours"])
            result.append(dept_data)

        return Response(result, status=status.HTTP_200_OK)


# ══════════════════════════════════════════════════════════════════
# APPRENANT — FORMATIONS
# GET /api/apprenant/formations/
#
# Même logique que Prépa Concours et ApprenantCursusAPIView.
# Filtre par profile.cursus = nom du Parcours.
# Paramètre optionnel ?parcours= pour charger un parcours spécifique
# (ex: "Formations Classiques" ou "Formations Métiers").
# ══════════════════════════════════════════════════════════════════

class ApprenantFormationsAPIView(APIView):
    """
    Retourne les départements (formations) du parcours de l'apprenant,
    groupés par département avec leurs cours.

    Filtre : profile.cursus == nom du Parcours
    Paramètre optionnel ?parcours=<nom> pour forcer un parcours spécifique.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != 'apprenant':
            return Response(
                {"detail": "Accès réservé aux apprenants."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Filtre identique à ApprenantCursusAPIView : profile.cursus = nom du Parcours
        # Paramètre optionnel ?parcours= pour afficher un sous-parcours spécifique
        nom_parcours = request.query_params.get('parcours', profile.cursus)

        if not nom_parcours:
            return Response([], status=status.HTTP_200_OK)

        cours_qs = Cours.objects.filter(
            departement__parcours__nom=nom_parcours
        ).select_related(
            'enseignant_principal__user', 'departement__parcours'
        ).order_by('departement__nom', 'titre')

        if not cours_qs.exists():
            return Response([], status=status.HTTP_200_OK)

        prog_map = _progression_cours(request.user, cours_qs)

        departements = {}
        for c in cours_qs:
            dept = c.departement
            if dept.id not in departements:
                cadre_data = None
                if dept.cadre:
                    cadre_data = {
                        "id":    dept.cadre.id,
                        "nom":   _nom_profil(dept.cadre),
                        "email": dept.cadre.user.email,
                    }
                departements[dept.id] = {
                    "id":                 dept.id,
                    "nom":                dept.nom,
                    "parcours_nom":       dept.parcours.nom if dept.parcours else '',
                    "cadre":              cadre_data,
                    "cours":              [],
                    "nb_cours":           0,
                    "progression_moyenne": 0.0,
                }
            departements[dept.id]["cours"].append(_serialise_cours(c, prog_map))

        result = []
        for dept_data in departements.values():
            progs = [c["progression"] for c in dept_data["cours"]]
            dept_data["progression_moyenne"] = round(
                sum(progs) / len(progs), 1
            ) if progs else 0.0
            dept_data["nb_cours"] = len(dept_data["cours"])
            result.append(dept_data)

        return Response(result, status=status.HTTP_200_OK)


# ══════════════════════════════════════════════════════════════════
# APPRENANT — DÉTAIL D'UN DÉPARTEMENT
# GET /api/apprenant/departement/<pk>/
# ══════════════════════════════════════════════════════════════════

class ApprenantDepartementDetailView(APIView):
    """Détail d'un département (concours ou formation) avec ses cours."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        dept = get_object_or_404(Departement, pk=pk)
        cours_qs = Cours.objects.filter(
            departement=dept
        ).select_related('enseignant_principal__user')

        prog_map = _progression_cours(request.user, cours_qs)

        cadre_data = None
        if dept.cadre:
            cadre_data = {
                "id":  dept.cadre.id,
                "nom": _nom_profil(dept.cadre),
            }

        return Response({
            "id":          dept.id,
            "nom":         dept.nom,
            "parcours":    {"id": dept.parcours.id, "nom": dept.parcours.nom},
            "cadre":       cadre_data,
            "nb_cours":    cours_qs.count(),
            "cours":       [_serialise_cours(c, prog_map) for c in cours_qs],
        })


# ══════════════════════════════════════════════════════════════════
# OLYMPIADES — FILTRÉES POUR L'APPRENANT
# GET /api/olympiades/pour-moi/
#
# Retourne les olympiades dont le cadre organisateur appartient
# au même parcours que l'apprenant (via sub_cursus ou un parcours
# "Olympiades" dédié).
# Seules les olympiades avec Devoir.est_publie=True sont visibles.
# ══════════════════════════════════════════════════════════════════

class OlympiadesPourMoiView(APIView):
    """
    Olympiades filtrées pour l'apprenant connecté.

    Logique de filtrage (par ordre de priorité) :
    1. Si profile.cursus existe → parcours de l'olympiade == cursus
    2. Sinon → toutes les olympiades validées (Devoir.est_publie=True)

    Le lien parcours ↔ olympiade se fait via :
      Olympiade.organisateur (Profile cadre)
        → departements_cadre (Departement)
          → parcours (Parcours)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        if not profile:
            return Response({"detail": "Profil introuvable."}, status=404)

        # Filtres URL
        statut  = request.query_params.get('statut')
        matiere = request.query_params.get('matiere')
        niveau  = request.query_params.get('niveau')

        # Base queryset — seulement les olympiades publiées
        # (Devoir.est_publie=True signifie que l'admin a validé)
        qs = Olympiade.objects.filter(
            devoir__est_publie=True
        ).select_related(
            'organisateur__user', 'devoir'
        ).order_by('-date_debut_olympiade')

        # Filtre par parcours si l'apprenant a un cursus (même logique que ApprenantCursusAPIView)
        if profile.cursus:
            qs = qs.filter(
                organisateur__departements_cadre__parcours__nom=profile.cursus
            ).distinct()

        if matiere:
            qs = qs.filter(matiere=matiere)
        if niveau:
            qs = qs.filter(niveau=niveau)

        serializer = OlympiadeListSerializer(
            qs, many=True, context={"request": request}
        )
        data = serializer.data

        if statut:
            data = [d for d in data if d["statut"] == statut]

        return Response(data)


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
    Retourne les olympiades du parcours de l'admin qui attendent validation.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != 'enseignant_admin':
            return Response({"detail": "Accès refusé."}, status=403)

        # Récupérer le parcours de cet admin
        try:
            parcours = Parcours.objects.get(admin=profile)
        except Parcours.DoesNotExist:
            return Response({"detail": "Aucun parcours assigné."}, status=404)

        # Olympiades du parcours, non encore publiées
        olympiades = Olympiade.objects.filter(
            organisateur__departements_cadre__parcours=parcours,
            devoir__est_publie=False,
        ).select_related(
            'organisateur__user', 'devoir'
        ).distinct().order_by('-date_debut_olympiade')

        result = []
        for o in olympiades:
            cadre_nom = _nom_profil(o.organisateur) if o.organisateur else '—'
            dept = (
                o.organisateur.departements_cadre.filter(parcours=parcours).first()
                if o.organisateur else None
            )
            result.append({
                "id":             o.id,
                "titre":          o.titre,
                "matiere":        o.matiere,
                "niveau":         o.niveau,
                "edition":        o.edition,
                "cadre":          cadre_nom,
                "departement":    {"id": dept.id, "nom": dept.nom} if dept else None,
                "date_debut":     o.date_debut_olympiade,
                "date_fin":       o.date_fin_olympiade,
                "nb_questions":   o.nb_questions,
                "prix_1er":       o.prix_1er,
                "prix_2eme":      o.prix_2eme,
                "prix_3eme":      o.prix_3eme,
                "est_gratuite":   not any([o.prix_1er, o.prix_2eme, o.prix_3eme]),
                "devoir_id":      o.devoir.id if o.devoir else None,
                "statut":         o.statut_auto,
            })

        return Response(result)


class AdminValiderOlympiadeView(APIView):
    """
    POST /api/admin/olympiades/<pk>/valider/
    Body optionnel : { "refuser": true, "motif": "..." }

    Valide (publie) ou refuse une olympiade du parcours de l'admin.
    Valider = mettre Devoir.est_publie = True
    Refuser = supprimer l'olympiade et son devoir lié, ou juste notifier
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != 'enseignant_admin':
            return Response({"detail": "Accès refusé."}, status=403)

        try:
            parcours = Parcours.objects.get(admin=profile)
        except Parcours.DoesNotExist:
            return Response({"detail": "Aucun parcours assigné."}, status=404)

        # Vérifier que cette olympiade appartient bien au parcours de cet admin
        olympiade = get_object_or_404(
            Olympiade,
            pk=pk,
            organisateur__departements_cadre__parcours=parcours,
        )

        refuser = request.data.get('refuser', False)

        if refuser:
            motif = request.data.get('motif', 'Refusée par l\'administrateur.')
            # On garde l'olympiade mais on la marque comme refusée
            # en gardant est_publie=False — le cadre peut corriger et resoumettre
            enregistrer_activite(
                user=request.user,
                action='olympiad_closed',
                description=f"Olympiade « {olympiade.titre} » refusée : {motif}",
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

        enregistrer_activite(
            user=request.user,
            action='olympiad_created',
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


# ══════════════════════════════════════════════════════════════════
# ENSEIGNANT ADMIN — DÉPARTEMENTS À VALIDER (formations/concours)
# GET  /api/admin/departements/a-valider/
# POST /api/admin/departements/<pk>/valider/
#
# L'enseignant_admin peut voir les départements récemment créés dans
# son parcours, activer ou désactiver un département.
# Un département "non validé" signifie que ses cours ne sont pas
# encore accessibles aux apprenants.
# On s'appuie sur le fait qu'un cours non publié (Devoir.est_publie=False)
# ou un département sans cours actif est considéré "en attente".
#
# Pour ne PAS modifier models.py, on utilise le champ :
#   Departement.cadre = None  →  département sans cadre = en attente d'activation
#   Valider = assigner un cadre + activer
#   OU : pour les formations à prix=0, l'admin doit explicitement activer
#        en publiant tous les devoirs du département.
# ══════════════════════════════════════════════════════════════════

class AdminDepartementsAValiderView(APIView):
    """
    GET /api/admin/departements/a-valider/
    Retourne les départements du parcours sans cadre assigné
    (= créés par l'admin mais pas encore activés) + ceux dont
    les devoirs/cours sont en attente de publication.
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

        # Départements du parcours sans cadre assigné
        deps_sans_cadre = Departement.objects.filter(
            parcours=parcours, cadre__isnull=True
        ).prefetch_related('cours')

        # Départements dont certains devoirs ne sont pas encore publiés
        deps_avec_devoirs_attente = Departement.objects.filter(
            parcours=parcours,
            cours__devoirs__est_publie=False,
        ).distinct().prefetch_related('cours', 'cadre__user')

        # Union des deux ensembles
        all_ids = set(
            list(deps_sans_cadre.values_list('id', flat=True)) +
            list(deps_avec_devoirs_attente.values_list('id', flat=True))
        )
        departements = Departement.objects.filter(
            id__in=all_ids
        ).select_related('cadre__user', 'parcours')

        result = []
        for dept in departements:
            nb_cours     = dept.cours.count()
            nb_devoirs_attente = Devoir.objects.filter(
                cours_lie__departement=dept, est_publie=False
            ).count()
            cadre_data = None
            if dept.cadre:
                cadre_data = {
                    "id":    dept.cadre.id,
                    "nom":   _nom_profil(dept.cadre),
                    "email": dept.cadre.user.email,
                }
            result.append({
                "id":                  dept.id,
                "nom":                 dept.nom,
                "cadre":               cadre_data,
                "nb_cours":            nb_cours,
                "nb_devoirs_attente":  nb_devoirs_attente,
                "statut":              "sans_cadre" if not dept.cadre else "devoirs_en_attente",
            })

        return Response(result)


class AdminValiderDepartementView(APIView):
    """
    POST /api/admin/departements/<pk>/valider/
    Body : { "cadre_id": 12 }          → assigner un cadre au département
           { "publier_devoirs": true }  → publier tous les devoirs du département
           { "desactiver": true }       → retirer le cadre (désactiver)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != 'enseignant_admin':
            return Response({"detail": "Accès refusé."}, status=403)

        try:
            parcours = Parcours.objects.get(admin=profile)
        except Parcours.DoesNotExist:
            return Response({"detail": "Aucun parcours assigné."}, status=404)

        dept = get_object_or_404(Departement, pk=pk, parcours=parcours)

        actions_effectuees = []

        # 1. Assigner un cadre
        cadre_id = request.data.get('cadre_id')
        if cadre_id:
            cadre = get_object_or_404(
                Profile, pk=cadre_id, user_type='enseignant_cadre'
            )
            dept.cadre = cadre
            dept.save(update_fields=['cadre'])
            actions_effectuees.append(f"Cadre assigné : {_nom_profil(cadre)}")
            enregistrer_activite(
                user=request.user,
                action='cadre_assigned',
                description=f"Cadre « {_nom_profil(cadre)} » assigné au dept « {dept.nom} »",
                objet_id=dept.id,
                objet_type='Departement',
            )

        # 2. Publier tous les devoirs du département
        if request.data.get('publier_devoirs'):
            nb = Devoir.objects.filter(
                cours_lie__departement=dept, est_publie=False
            ).update(est_publie=True)
            actions_effectuees.append(f"{nb} devoir(s) publié(s)")

        # 3. Désactiver (retirer le cadre)
        if request.data.get('desactiver'):
            dept.cadre = None
            dept.save(update_fields=['cadre'])
            actions_effectuees.append("Département désactivé (cadre retiré)")

        if not actions_effectuees:
            return Response(
                {"detail": "Aucune action spécifiée (cadre_id, publier_devoirs, desactiver)."},
                status=400,
            )

        return Response({
            "detail":   "Actions effectuées.",
            "actions":  actions_effectuees,
            "dept_id":  dept.id,
            "dept_nom": dept.nom,
        })


# ══════════════════════════════════════════════════════════════════
# PAIEMENT
# POST /api/paiements/initier/
# GET  /api/paiements/<reference>/verifier/
# GET  /api/paiements/historique/
# ══════════════════════════════════════════════════════════════════

class InitierPaiementView(APIView):
    """
    POST /api/paiements/initier/
    Body : {
      "type_paiement": "abonnement_mensuel" | "abonnement_annuel" | "acces_departement" | "olympiade",
      "moyen":         "mtn_momo" | "orange_om" | "carte",
      "montant":       1500,
      "telephone":     "6XXXXXXXX",        ← pour Mobile Money
      "departement_id": 3,                 ← si type = acces_departement
      "olympiade_id":  5                   ← si type = olympiade
    }
    """
    permission_classes = [IsAuthenticated]

    # Montants attendus (vérification côté serveur)
    MONTANTS_FIXES = {
        'abonnement_mensuel': 1500,
        'abonnement_annuel':  13000,
    }

    def post(self, request):
        data            = request.data
        type_paiement   = data.get('type_paiement', '').strip()
        moyen           = data.get('moyen', '').strip()
        montant_envoye  = data.get('montant')

        # ── Validations ────────────────────────────────────────────
        types_valides = [t[0] for t in Paiement.TYPE_CHOICES]
        if type_paiement not in types_valides:
            return Response(
                {"detail": f"type_paiement invalide. Valeurs acceptées : {types_valides}"},
                status=400,
            )

        moyens_valides = [m[0] for m in Paiement.MOYEN_CHOICES]
        if moyen not in moyens_valides:
            return Response(
                {"detail": f"moyen invalide. Valeurs acceptées : {moyens_valides}"},
                status=400,
            )

        # Vérifier le montant pour les abonnements
        if type_paiement in self.MONTANTS_FIXES:
            montant_attendu = self.MONTANTS_FIXES[type_paiement]
            if int(montant_envoye or 0) != montant_attendu:
                return Response(
                    {"detail": f"Montant incorrect. Attendu : {montant_attendu} FCFA."},
                    status=400,
                )
            montant = montant_attendu
        else:
            try:
                montant = int(montant_envoye)
                if montant <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return Response({"detail": "Montant invalide."}, status=400)

        # ── Créer le paiement en attente ──────────────────────────
        paiement_kwargs = {
            "utilisateur":   request.user,
            "type_paiement": type_paiement,
            "moyen":         moyen,
            "montant":       montant,
            "statut":        "en_attente",
        }

        if type_paiement == 'olympiade':
            olympiade_id = data.get('olympiade_id')
            if not olympiade_id:
                return Response({"detail": "olympiade_id requis."}, status=400)
            olympiade = get_object_or_404(Olympiade, pk=olympiade_id)
            paiement_kwargs["olympiade_liee"] = olympiade

        if type_paiement == 'acces_departement':
            dept_id = data.get('departement_id')
            if not dept_id:
                return Response({"detail": "departement_id requis."}, status=400)
            # Vérifier que le département existe
            get_object_or_404(Departement, pk=dept_id)
            # Commission 15% pour accès département payant
            paiement_kwargs["commission_yeki"] = round(montant * 0.15)

        paiement = Paiement.objects.create(**paiement_kwargs)

        # ── Simulation opérateur (à remplacer par SDK MTN/Orange) ─
        # En production : appel API MTN MoMo ou Orange Money ici
        # Pour l'instant, on simule un succès immédiat
        # Accepte 'telephone' ET 'numero' (Flutter peut envoyer l'un ou l'autre)
        telephone = data.get('telephone') or data.get('numero', '')
        succes_simule = self._simuler_paiement(moyen, telephone)

        if succes_simule:
            paiement.statut       = 'succes'
            paiement.transaction_id = f"SIM-{uuid.uuid4().hex[:12].upper()}"
            paiement.save(update_fields=['statut', 'transaction_id'])

            # Post-traitement selon le type
            self._post_traitement(request.user, paiement, type_paiement)

            return Response({
                "reference":      paiement.reference,
                "statut":         "succes",
                "transaction_id": paiement.transaction_id,
                "montant":        paiement.montant,
                "detail":         "Paiement effectué avec succès.",
            }, status=201)
        else:
            paiement.statut = 'echec'
            paiement.save(update_fields=['statut'])
            return Response({
                "reference": paiement.reference,
                "statut":    "echec",
                "detail":    "Échec du paiement. Vérifiez votre solde.",
            }, status=402)

    def _simuler_paiement(self, moyen, telephone):
        """
        Simulation locale — uniquement en mode DEBUG.
        En production, remplacer par l'appel SDK MTN MoMo / Orange Money.
        """
        from django.conf import settings
        if not settings.DEBUG:
            # En production : lever une erreur claire pour forcer l'intégration réelle
            raise NotImplementedError(
                "Intégration paiement MTN MoMo / Orange Money non configurée. "
                "Veuillez implémenter _simuler_paiement() avec le SDK opérateur."
            )
        return bool(telephone)

    @transaction.atomic
    def _post_traitement(self, user, paiement, type_paiement):
        """Actions après un paiement réussi."""
        if type_paiement == 'abonnement_mensuel':
            self._activer_abonnement(user, 'mensuel', paiement)
        elif type_paiement == 'abonnement_annuel':
            self._activer_abonnement(user, 'annuel', paiement)

    def _activer_abonnement(self, user, type_abo, paiement):
        jours = 30 if type_abo == 'mensuel' else 365
        try:
            abo = user.abonnement
            abo.renouveler(type_abo)
            abo.paiement = paiement
            abo.save(update_fields=['paiement'])
        except AbonnementPremium.DoesNotExist:
            AbonnementPremium.objects.create(
                utilisateur     = user,
                type_abonnement = type_abo,
                actif           = True,
                fin             = timezone.now() + timedelta(days=jours),
                paiement        = paiement,
            )


class VerifierPaiementView(APIView):
    """GET /api/paiements/<reference>/verifier/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        paiement = get_object_or_404(
            Paiement, reference=reference, utilisateur=request.user
        )
        return Response({
            "reference":      paiement.reference,
            "statut":         paiement.statut,
            "type_paiement":  paiement.type_paiement,
            "montant":        paiement.montant,
            "moyen":          paiement.moyen,
            "transaction_id": paiement.transaction_id,
            "date":           paiement.date,
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


class YekiIARepondreForumView(APIView):
    """
    POST /api/ia/forum/<question_id>/repondre/
    Déclenche une réponse de Yeki IA sur une question du forum.
    Peut être appelé manuellement (bouton "@YekiIA") ou automatiquement.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, question_id):
        question = get_object_or_404(QuestionForum, pk=question_id)

        # Éviter les doublons IA sur la même question
        if YekiIAMessage.objects.filter(question=question).exists():
            return Response(
                {"detail": "Yeki IA a déjà répondu à cette question."},
                status=400,
            )

        # Déterminer le contexte de la personnalité IA
        profile = _get_profile(request.user)
        cours_lie = None
        if question.cours_id:
            try:
                cours_lie = Cours.objects.get(pk=question.cours_id)
            except Cours.DoesNotExist:
                pass

        nom_parcours = None
        niveau_cursus = None
        if profile:
            nom_parcours  = profile.cursus or None
            niveau_cursus = profile.niveau or None

        personnalite = _get_ia_personnalite(
            cours=cours_lie,
            nom_parcours=nom_parcours,
            niveau_cursus=niveau_cursus,
        )

        system_prompt = personnalite.build_system_prompt()
        texte_ia, tokens = _appeler_openai(system_prompt, question.contenu)

        # S'assurer que la réponse commence par "Yeki IA :"
        if not texte_ia.startswith("Yeki IA :"):
            texte_ia = f"Yeki IA : {texte_ia}"

        # Créer ou récupérer l'utilisateur YekiIA
        yeki_user, _ = __import__(
            'django.contrib.auth', fromlist=['get_user_model']
        ).get_user_model().objects.get_or_create(
            username='YekiIA',
            defaults={'first_name': 'Yeki', 'last_name': 'IA'},
        )

        # Sauvegarder comme ReponseQuestion normale
        with transaction.atomic():
            reponse = ReponseQuestion.objects.create(
                question   = question,
                auteur     = yeki_user,
                contenu    = texte_ia,
                est_solution = False,
            )

            ia_msg = YekiIAMessage.objects.create(
                question        = question,
                personalite     = personnalite,
                contenu         = texte_ia,
                tokens_utilises = tokens,
                erreur          = tokens == 0,
                reponse_forum   = reponse,
            )

        return Response({
            "id":        ia_msg.id,
            "contenu":   texte_ia,
            "tokens":    tokens,
            "reponse_id": reponse.id,
        }, status=201)


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
# ENSEIGNANT ADMIN — DASHBOARD ENRICHI (avec olympiades + formations)
# GET /api/enseignant/admin/dashboard/enrichi/
#
# Extension du dashboard existant (EnseignantAdminDashboardView)
# qui ajoute les olympiades en attente et les stats de formations.
# ══════════════════════════════════════════════════════════════════

class EnseignantAdminDashboardEnrichiView(APIView):
    """
    GET /api/enseignant/admin/dashboard/enrichi/
    Dashboard complet pour l'enseignant_admin incluant :
    - Départements (= concours / formations) du parcours
    - Olympiades en attente de validation
    - Stats globales
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != 'enseignant_admin':
            return Response({"detail": "Accès refusé."}, status=403)

        try:
            parcours = Parcours.objects.prefetch_related(
                'departements__cours',
                'departements__cadre__user',
            ).get(admin=profile)
        except Parcours.DoesNotExist:
            return Response({"detail": "Aucun parcours assigné."}, status=404)

        # ── Départements ─────────────────────────────────────────
        departements_data = []
        cadres_dict = {}

        for dept in parcours.departements.all():
            nb_cours  = dept.cours.count()
            nb_app    = sum(c.nb_apprenants for c in dept.cours.all())

            # Olympiades de ce département
            olympiades_dept = Olympiade.objects.filter(
                organisateur__departements_cadre=dept
            )
            nb_olympiades_total    = olympiades_dept.count()
            nb_olympiades_attente  = olympiades_dept.filter(
                devoir__est_publie=False
            ).count()

            cadre_data = None
            if dept.cadre:
                cadre_data = {
                    "id":    dept.cadre.id,
                    "nom":   _nom_profil(dept.cadre),
                    "email": dept.cadre.user.email,
                }
                if dept.cadre.id not in cadres_dict:
                    cadres_dict[dept.cadre.id] = {
                        "id":             dept.cadre.id,
                        "nom":            cadre_data["nom"],
                        "email":          dept.cadre.user.email,
                        "nb_cours":       nb_cours,
                        "nb_apprenants":  nb_app,
                        "departement":    {"id": dept.id, "nom": dept.nom},
                    }

            departements_data.append({
                "id":                     dept.id,
                "nom":                    dept.nom,
                "parcours":               parcours.nom,
                "parcours_id":            parcours.id,
                "nb_cours":               nb_cours,
                "nb_apprenants":          nb_app,
                "nb_olympiades":          nb_olympiades_total,
                "nb_olympiades_attente":  nb_olympiades_attente,
                "cadre":                  cadre_data,
            })

        # ── Olympiades en attente de validation ──────────────────
        olympiades_attente = Olympiade.objects.filter(
            organisateur__departements_cadre__parcours=parcours,
            devoir__est_publie=False,
        ).distinct().values('id', 'titre', 'matiere', 'date_debut_olympiade')

        # ── Stats globales ───────────────────────────────────────
        stats = {
            "nb_departements":        len(departements_data),
            "nb_cours":               sum(d["nb_cours"] for d in departements_data),
            "nb_apprenants":          sum(d["nb_apprenants"] for d in departements_data),
            "nb_enseignants":         len(cadres_dict),
            "nb_olympiades_attente":  len(olympiades_attente),
            "nb_deps_sans_cadre":     sum(
                1 for d in departements_data if d["cadre"] is None
            ),
        }

        return Response({
            "nom":              _nom_profil(profile),
            "nom_parcours":     parcours.nom,
            "id_parcours":      parcours.id,
            "stats":            stats,
            "departements":     departements_data,
            "cadres":           list(cadres_dict.values()),
            "olympiades_a_valider": list(olympiades_attente),
        })


# ---------------------------
# Dashboard selon rôle
# ---------------------------
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_data(request):
    user = Profile.objects.get(user=request.user)
    role = getattr(user, "user_type", None)

    data = {"role": role, "nom": getattr(user.user, "name", getattr(user.user, "username", ""))}

    if role == "admin":
        parcours = Parcours.objects.select_related("admin").all()
        data["parcours"] = ParcoursSerializer(parcours, many=True).data

    elif role == "enseignant_admin":
        parcours = Parcours.objects.filter(admin=user)
        data["parcours"] = ParcoursSerializer(parcours, many=True).data

    elif role == "enseignant_cadre":
        departements = Departement.objects.filter(cadre=user)
        data["departements"] = DepartementSerializer(departements, many=True).data

    elif role == "enseignant_principal":
        cours = Cours.objects.filter(enseignant_principal=user)
        data["cours"] = CoursSerializer(cours, many=True).data

    elif role == "enseignant":
        cours = user.cours_secondaires.all()
        data["cours"] = CoursSerializer(cours, many=True).data

    else:
        return Response({'error': 'Rôle non géré ici.'}, status=status.HTTP_403_FORBIDDEN)

    return Response(data, status=status.HTTP_200_OK)


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

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------
# Login
# ---------------------------
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.validated_data['user']
            token, _ = Token.objects.get_or_create(user=user)
            profile = Profile.objects.get(user=user)

            return Response({
                'token': token.key,
                'role': profile.user_type,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                }
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
