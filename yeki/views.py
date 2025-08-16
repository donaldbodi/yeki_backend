from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics
from rest_framework.authtoken.models import Token
from .serializers import (
    RegisterSerializer, 
    LoginSerializer, 
    ParcoursSerializer, 
    EnseignantSerializer,
    DepartementSerializer,
    CoursSerializer,
    LeconSerializer
)
from rest_framework.decorators import api_view, permission_classes
from .models import Parcours, CustomUser, AppVersion, Departement, Cours, Lecon
from django.db.models import Sum, Avg
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied

# 1️⃣ Liste et création des parcours (Admin général uniquement)
class ParcoursListCreateView(generics.ListCreateAPIView):
    queryset = Parcours.objects.all()
    serializer_class = ParcoursSerializer

    def perform_create(self, serializer):
        # seul un admin général doit pouvoir créer un parcours
        user = self.request.user
        if user.user_type != "admin":
            raise PermissionError("Seul un administrateur général peut créer un parcours.")
        serializer.save()


# 2️⃣ Assigner ou changer un enseignant_admin à un parcours
class AssignAdminView(APIView):
    def put(self, request, pk):
        try:
            parcours = Parcours.objects.get(pk=pk)
            admin_id = request.data.get("admin_id")
            admin_user = CustomUser.objects.get(pk=admin_id, user_type="enseignant_admin")
            parcours.admin = admin_user
            parcours.save()
            return Response({"message": "Enseignant admin assigné avec succès."}, status=status.HTTP_200_OK)
        except Parcours.DoesNotExist:
            return Response({"error": "Parcours introuvable."}, status=status.HTTP_404_NOT_FOUND)
        except CustomUser.DoesNotExist:
            return Response({"error": "Enseignant_admin introuvable."}, status=status.HTTP_404_NOT_FOUND)


# 3️⃣ Statistiques d’un enseignant_admin
class EnseignantAdminStatsView(APIView):
    def get(self, request, pk):
        try:
            enseignant_admin = CustomUser.objects.get(pk=pk, user_type="enseignant_admin")
            
            # récupère les parcours gérés par cet enseignant_admin
            departements = Departement.objects.filter(admin=enseignant_admin).count()
            cours = Cours.objects.filter(departement__admin=enseignant_admin).count()
            lecons = Lecon.objects.filter(cours__departement__admin=enseignant_admin).count()

            stats = {
                "departements": departements,
                "cours": cours,
                "lecons": lecons
            }
            return Response(stats, status=status.HTTP_200_OK)

        except CustomUser.DoesNotExist:
            return Response({"error": "Enseignant_admin introuvable."}, status=status.HTTP_404_NOT_FOUND)


# ✅ Fonction utilitaire pour vérifier les rôles
def check_role(user, allowed_roles):
    if user.user_type not in allowed_roles:
        raise PermissionDenied("Vous n’avez pas les permissions nécessaires.")


# ✅ API : version la plus récente
def latest_version(request):
    latest = AppVersion.objects.latest("created_at")
    return JsonResponse({
        "version_code": latest.version_code,
        "version_name": latest.version_name,
        "apk_url": latest.apk_url,
        "changelog": latest.changelog
    })


# ✅ Dashboard selon rôle
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_data(request):
    user = request.user
    role = user.user_type

    data = {"role": role, "nom": user.name}

    if role == "admin":
        # admin voit tous les parcours
        parcours = Parcours.objects.select_related("admin").all()
        data["parcours"] = ParcoursSerializer(parcours, many=True).data

    elif role == "enseignant_admin":
        # enseignant admin voit uniquement ses parcours
        parcours = Parcours.objects.filter(admin=user)
        data["parcours"] = ParcoursSerializer(parcours, many=True).data

    elif role == "enseignant_cadre":
        # ✅ utilise le serializer
        departements = Departement.objects.filter(enseignant_cadre=user)
        data["departements"] = DepartementSerializer(departements, many=True).data

    elif role == "enseignant_principal":
        # ✅ utilise le serializer
        cours = Cours.objects.filter(enseignant_principal=user)
        data["cours"] = CoursSerializer(cours, many=True).data

    elif role == "enseignant":
        # enseignant secondaire : les cours où il a été ajouté (ManyToMany cours_secondaires)
        cours = user.cours_secondaires.all()
        data["cours"] = CoursSerializer(cours, many=True).data

    else:
        return Response({'error': 'Rôle non géré ici.'}, status=403)

    return Response(data)


# ✅ Landing page
def landing(request):
    return render(request, 'landing-page.html')


# ✅ Inscription
class RegisterView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            token, _ = Token.objects.get_or_create(user=user)
            return Response({
                'token': token.key,
                'user': serializer.data,
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ✅ Connexion
class LoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            token, _ = Token.objects.get_or_create(user=user)
            return Response({
                'token': token.key,
                'role': user.user_type,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email
                }
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ✅ Liste des parcours
@api_view(['GET'])
def liste_parcours(request):
    parcours = Parcours.objects.select_related('admin').all()
    serializer = ParcoursSerializer(parcours, many=True)
    return Response(serializer.data)


# ✅ Liste des enseignants
@api_view(['GET'])
def liste_enseignants(request):
    enseignants = CustomUser.objects.filter(
        user_type__in=['enseignant', 'enseignant_principal', 'enseignant_admin', 'enseignant_cadre', 'admin']
    )
    serializer = EnseignantSerializer(enseignants, many=True)
    return Response(serializer.data)


# ✅ Changer l’admin d’un parcours (uniquement par l’admin général)
@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def changer_admin(request, parcours_id):
    user = request.user
    check_role(user, ["admin"])  # sécurité : seul un admin peut faire ça

    try:
        parcours = Parcours.objects.get(id=parcours_id)
        id_enseignant = request.data.get("enseignant_id")
        nouvel_admin = CustomUser.objects.get(id=id_enseignant)

        if nouvel_admin.user_type != "enseignant_admin":
            return Response({"error": "Le nouvel utilisateur doit être un enseignant_admin."}, status=400)

        parcours.admin = nouvel_admin
        parcours.save()
        return Response({"success": True})
    except Exception as e:
        return Response({"error": str(e)}, status=400)


# ✅ Statistiques globales
@api_view(['GET'])
def statistiques_globales(request):
    total_apprenants = Parcours.objects.aggregate(Sum('apprenants'))['apprenants__sum'] or 0
    total_cours = Parcours.objects.aggregate(Sum('cours'))['cours__sum'] or 0
    moyenne_globale = Parcours.objects.aggregate(Avg('moyenne'))['moyenne__avg'] or 0.0

    return Response({
        "total_apprenants": total_apprenants,
        "total_cours": total_cours,
        "moyenne_globale": round(moyenne_globale, 2)
    })
