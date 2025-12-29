# views.py
from django.shortcuts import render, get_object_or_404
from django.db import transaction
from django.core.exceptions import PermissionDenied

from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token

from django.contrib.auth import get_user_model
from django.db.models import Sum, Avg

from .models import Parcours, Departement, Cours, Lecon, Profile
from .serializers import (
    CoursCreateSerializer,
    RegisterSerializer,
    LoginSerializer,
    ParcoursSerializer,
    EnseignantSerializer,
    DepartementSerializer,
    CoursSerializer,
    EnseignantCadreLightSerializer,
    LeconSerializer
)

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
class AddEnseignantSecondaireView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        if cours.enseignant_principal != request.user:
            raise PermissionDenied("Action réservée à l’enseignant principal du cours.")

        enseignant_id = request.data.get('enseignant_id')
        if not enseignant_id:
            return Response({"detail": "L'id de l'enseignant est requis."}, status=status.HTTP_400_BAD_REQUEST)

        enseignant = get_object_or_404(User, pk=enseignant_id)
        if getattr(enseignant, "user_type", None) != 'enseignant':
            return Response({"detail": "L'utilisateur choisi n'est pas un enseignant secondaire."}, status=status.HTTP_400_BAD_REQUEST)

        if enseignant in cours.enseignants.all():
            return Response({"detail": "Enseignant déjà présent."}, status=status.HTTP_400_BAD_REQUEST)

        cours.enseignants.add(enseignant)
        cours.save()
        return Response(CoursSerializer(cours).data, status=status.HTTP_200_OK)


class RemoveEnseignantSecondaireView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        if cours.enseignant_principal != request.user:
            raise PermissionDenied("Action réservée à l’enseignant principal du cours.")

        enseignant_id = request.data.get('enseignant_id')
        if not enseignant_id:
            return Response({"detail": "L'id de l'enseignant est requis."}, status=status.HTTP_400_BAD_REQUEST)

        enseignant = get_object_or_404(User, pk=enseignant_id)
        if enseignant not in cours.enseignants.all():
            return Response({"detail": "Enseignant non présent dans le cours."}, status=status.HTTP_400_BAD_REQUEST)

        cours.enseignants.remove(enseignant)
        cours.save()
        return Response(CoursSerializer(cours).data, status=status.HTTP_200_OK)


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


class CoursUpdateView(generics.UpdateAPIView, generics.RetrieveAPIView):
    queryset = Cours.objects.select_related('departement', 'enseignant_principal')
    serializer_class = CoursSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch']

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        cours = self.get_object()
        payload = request.data

        # Autorisation : enseignant_cadre ou enseignant_principal
        check_role(request.user, ['enseignant_cadre', 'enseignant_principal'])

        # Champs modifiables
        if 'titre' in payload:
            titre = (payload.get('titre') or "").strip()
            if not titre:
                return Response({"detail": "Le titre ne peut pas être vide."}, status=status.HTTP_400_BAD_REQUEST)
            cours.titre = titre

        if 'niveau' in payload:
            niveau = (payload.get('niveau') or "").strip()
            if not niveau:
                return Response({"detail": "Le niveau ne peut pas être vide."}, status=status.HTTP_400_BAD_REQUEST)
            cours.niveau = niveau

        if 'departement' in payload:
            dep_id = payload.get('departement')
            departement = get_object_or_404(Departement, pk=dep_id)
            cours.departement = departement

        if 'enseignant_principal' in payload:
            principal_id = payload.get('enseignant_principal')
            if principal_id in [None, "", "null"]:
                cours.enseignant_principal = None
            else:
                principal = get_object_or_404(User, pk=principal_id)
                if getattr(principal, "user_type", None) != 'enseignant_principal':
                    return Response({"detail": "L'utilisateur choisi n'est pas un enseignant_principal."}, status=status.HTTP_400_BAD_REQUEST)
                cours.enseignant_principal = principal

        cours.save()
        return Response(CoursSerializer(cours).data, status=status.HTTP_200_OK)


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
            cadre = get_object_or_404(User, pk=cadre_id)
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


# ---------------------------
# Listes publiques simples
# ---------------------------
@api_view(['GET'])
@permission_classes([IsAuthenticated])
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
@permission_classes([IsAuthenticated])
def liste_enseignants(request):
    qs = User.objects.filter(user_type__in=[
        'enseignant', 'enseignant_principal', 'enseignant_admin', 'enseignant_cadre', 'admin'
    ])
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
