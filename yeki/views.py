# views.py
from django.shortcuts import render, get_object_or_404
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.contrib.auth.hashers import check_password

from django.contrib.auth import get_user_model
from django.db.models import Sum, Avg

from .models import *
from .serializers import *

User = get_user_model()



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
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.core.exceptions import PermissionDenied
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from .models import Cours, Profile
from .serializers import CoursSerializer


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

        # 🔐 SÉCURITÉ : apprenant seulement
        if profile.user_type != "apprenant":
            return Response(
                {"detail": "Accès réservé aux apprenants"},
                status=status.HTTP_403_FORBIDDEN
            )

        if not profile.cursus:
            return Response([], status=status.HTTP_200_OK)

        cours = Cours.objects.filter(
            departement__parcours__nom=profile.cursus
        ).select_related("enseignant_principal")

        serializer = CursusApprenantSerializer(cours, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


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

            cours.nb_lecons += 1
            cours.save(update_fields=['nb_lecons'])

            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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

        return Response(
            {
                "id": module.id,
                "titre": module.titre,
                "ordre": module.ordre,
                "cours": cours.id
            },
            status=status.HTTP_201_CREATED
        )


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

        # Devoirs liés à ce cours (type cursus, reliés au cours)
        devoirs = Devoir.objects.filter(
            cours_id=cours_id,      # Adaptez selon votre champ FK vers Cours
            type_devoir='cursus',
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
        if soum.statut not in ["corrige"]:
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

        parcours_qs = Parcours.objects.get(admin=profile)(
            'departements__cours',
            'departements__cadre__user'
        )

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
    #permission_classes = [AllowAny]

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
    #permission_classes = [AllowAny]

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
