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
    EnseignantCadreLightSerializer,
    LeconSerializer
)
from rest_framework.decorators import api_view, permission_classes
from .models import Parcours, CustomUser, AppVersion, Departement, Cours, Lecon
from django.db.models import Sum, Avg
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.db import transaction

# --- LISTE DES ENSEIGNANTS CADRES ---
# GET /api/enseignants_cadres/
@api_view(["GET"])
#@permission_classes([IsAuthenticated])
def liste_enseignants_cadres(request):
    qs = CustomUser.objects.filter(user_type="enseignant_cadre").order_by("name")
    data = EnseignantCadreLightSerializer(qs, many=True).data
    # Flutter attend {id, name}
    return Response(data, status=200)


# --- LISTE DES DEPARTEMENTS D'UN PARCOURS ---
# GET /api/parcours/<parcours_id>/departements/
@api_view(["GET"])
#@permission_classes([IsAuthenticated])
def departements_par_parcours(request, parcours_id):
    """
    Renvoie la liste des départements du parcours demandé.
    Accessible à tout utilisateur connecté (tu peux restreindre si besoin).
    """
    parcours = get_object_or_404(Parcours, pk=parcours_id)
    deps = Departement.objects.filter(parcours=parcours).select_related("enseignant_cadre")
    data = DepartementSerializer(deps, many=True).data
    return Response(data, status=200)


# --- CREATION D'UN DEPARTEMENT ---
# POST /api/departements/
class DepartementCreateView(generics.CreateAPIView):
    """
    Crée un département.
    Autorisé: admin global OU enseignant_admin du parcours indiqué.
    Payload attendu par Flutter:
    {
        "nom": "...",
        "parcours": <id>,
        "enseignant_cadre": <id|null>
    }
    """
    serializer_class = DepartementSerializer
    #permission_classes = [IsAuthenticated]

    def get_target_parcours(self):
        # utilisé par IsAdminOrParcoursAdmin
        parcours_id = self.request.data.get("parcours")
        if not parcours_id:
            return None
        return Parcours.objects.filter(pk=parcours_id).first()

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        nom = request.data.get("nom", "").strip()
        parcours_id = request.data.get("parcours")
        cadre_id = request.data.get("enseignant_cadre", None)

        if not nom:
            return Response({"detail": "Le champ 'nom' est requis."}, status=400)

        parcours = get_object_or_404(Parcours, pk=parcours_id)
 
        cadre = None
        if cadre_id:
            cadre = get_object_or_404(CustomUser, pk=cadre_id)
            if cadre.user_type != "enseignant_cadre":
                return Response(
                    {"detail": "L'utilisateur choisi n'est pas un enseignant_cadre."},
                    status=400,
                )

        dep = Departement.objects.create(
            nom=nom, parcours=parcours, cadre=cadre
        )
        data = DepartementSerializer(dep).data
        return Response(data, status=status.HTTP_201_CREATED)


# --- MISE A JOUR PARTIELLE D'UN DEPARTEMENT ---
# PATCH /api/departements/<id>/
class DepartementUpdateView(generics.UpdateAPIView, generics.RetrieveAPIView):
    """
    Permet de patcher un département (principalement 'enseignant_cadre' ou 'nom').
    Autorisé: admin global OU enseignant_admin du parcours du département.
    """
    queryset = Departement.objects.select_related("parcours", "enseignant_cadre")
    serializer_class = DepartementSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_target_parcours(self):
        # utilisé par IsAdminOrParcoursAdmin
        dep = self.get_object()
        return dep.parcours

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        dep = self.get_object()
        payload = request.data

        # Changement d'enseignant_cadre
        if "enseignant_cadre" in payload:
            cadre_id = payload.get("enseignant_cadre")
            if cadre_id in [None, "", "null"]:
                dep.cadre = None
            else:
                cadre = get_object_or_404(CustomUser, pk=cadre_id)
                if cadre.user_type != "enseignant_cadre":
                    return Response(
                        {"detail": "L'utilisateur choisi n'est pas un enseignant_cadre."},
                        status=400,
                    )
                dep.cadre = cadre

        # Changement du nom (optionnel)
        if "nom" in payload:
            nom = (payload.get("nom") or "").strip()
            if not nom:
                return Response({"detail": "Le nom ne peut pas être vide."}, status=400)
            dep.nom = nom

        dep.save()
        return Response(DepartementSerializer(dep).data, status=200)



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
