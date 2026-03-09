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

        
# 📚 LISTE DES DEVOIRS
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def liste_devoirs(request):
    devoirs = Devoir.objects.all().order_by("-date_limite")
    serializer = DevoirSerializer(
        devoirs, many=True, context={"request": request}
    )
    return Response(serializer.data)


# 📄 DETAIL D’UN DEVOIR
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def detail_devoir(request, pk):
    devoir = Devoir.objects.get(pk=pk)
    serializer = DevoirSerializer(
        devoir, context={"request": request}
    )
    return Response(serializer.data)


# ▶️ DEMARRER DEVOIR
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def demarrer_devoir(request, pk):
    devoir = Devoir.objects.get(pk=pk)

    SoumissionDevoir.objects.get_or_create(
        utilisateur=request.user,
        devoir=devoir
    )

    return Response({"message": "Devoir démarré"})


# 📤 SOUMETTRE DEVOIR
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def soumettre_devoir(request, pk):
    devoir = Devoir.objects.get(pk=pk)

    soumission, _ = SoumissionDevoir.objects.get_or_create(
        utilisateur=request.user,
        devoir=devoir
    )

    soumission.date_soumission = timezone.now()
    soumission.save()

    return Response({"message": "Devoir soumis avec succès"})
    

# 📊 RESULTAT
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def resultat_devoir(request, pk):
    soum = SoumissionDevoir.objects.filter(
        utilisateur=request.user,
        devoir_id=pk
    ).first()

    if not soum:
        return Response({"detail": "Aucune soumission"}, status=404)

    return Response({
        "note": soum.note,
        "corrige": soum.corrige,
        "date_soumission": soum.date_soumission
    })


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
