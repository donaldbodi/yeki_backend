from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authtoken.models import Token
from .serializers import RegisterSerializer, LoginSerializer, ParcoursSerializer, UserSerializer
from rest_framework.decorators import api_view, permission_classes
from .models import Parcours, CustomUser
from .serializers import ParcoursSerializer, EnseignantSerializer
from django.db.models import Sum, Avg
from rest_framework.permissions import IsAuthenticated


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_enseignant_dashboard_data(request):
    user = request.user

    if user.user_type not in ['enseignant', 'enseignant_principal', 'enseignant_admin', 'admin']:
        return Response({'error': 'Utilisateur non autorisé'}, status=403)

    parcours = Parcours.objects.filter(admin=user)
    serialized_parcours = ParcoursSerializer(parcours, many=True).data

    role = user.user_type

    return Response({
        'role': role,
        'nom': user.name,
        'parcours': serialized_parcours,
    })

def landing(request):
    return render(request, 'landing-page.html')

class RegisterView(APIView):
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


class LoginView(APIView):
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

@api_view(['GET'])
def liste_parcours(request):
    parcours = Parcours.objects.select_related('admin').all()
    serializer = ParcoursSerializer(parcours, many=True)
    return Response(serializer.data)

@api_view(['GET'])
def liste_enseignants(request):
    enseignants = CustomUser.objects.filter(user_type__in=['enseignant', 'enseignant_principal', 'enseignant_admin', 'admin'])
    serializer = EnseignantSerializer(enseignants, many=True)
    return Response(serializer.data)

@api_view(['PATCH'])
def changer_admin(request, parcours_id):
    try:
        parcours = Parcours.objects.get(id=parcours_id)
        id_enseignant = request.data.get("enseignant_id")
        nouvel_admin = CustomUser.objects.get(id=id_enseignant)
        if nouvel_admin.user_type not in ['enseignant', 'enseignant_principal', 'enseignant_admin', 'admin']:
            return Response({"error": "Cet utilisateur n'est pas un enseignant valide."}, status=400)
        parcours.admin = nouvel_admin
        parcours.save()
        return Response({"success": True})
    except Exception as e:
        return Response({"error": str(e)}, status=400)

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
