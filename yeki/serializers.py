from rest_framework import serializers
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import CustomUser, Parcours, Departement, Cours, Lecon

User = get_user_model()

# =======================
# USER SERIALIZER
# =======================
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'name', 'email', 'user_type']


# =======================
# REGISTER SERIALIZER
# =======================
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])

    class Meta:
        model = CustomUser
        fields = [
            'username', 'email', 'password', 'name', 'user_type',
            'cursus', 'sub_cursus', 'niveau', 'filiere', 'licence'
        ]

        extra_kwargs = {
            'email': {'required': True},
            'username': {'required': True},
            'name': {'required': True},
            'user_type': {'required': True},
            'password': {'required': True},
        }

    def create(self, validated_data):
        user = CustomUser.objects.create(
            username=validated_data['username'],
            email=validated_data['email'],
            name=validated_data['name'],
            user_type=validated_data['user_type'],
            cursus=validated_data.get('cursus'),
            sub_cursus=validated_data.get('sub_cursus'),
            niveau=validated_data.get('niveau'),
            filiere=validated_data.get('filiere'),
            licence=validated_data.get('licence'),
        )
        user.set_password(validated_data['password'])

        # Auto-activation si apprenant
        if user.user_type == 'apprenant':
            user.is_active = True

        user.save()
        return user


# =======================
# LOGIN SERIALIZER
# =======================
class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        identifier = data.get('identifier')
        password = data.get('password')

        # Auth via username
        user = authenticate(username=identifier, password=password)

        # Auth via email
        if user is None:
            try:
                user_obj = User.objects.get(email=identifier)
                user = authenticate(username=user_obj.username, password=password)
            except User.DoesNotExist:
                pass

        if not user:
            raise serializers.ValidationError("Identifiants incorrects.")
        if not user.is_active:
            raise serializers.ValidationError("Le compte n'est pas activé. Contactez l’administration.")

        data['user'] = user
        return data


# =======================
# ENSEIGNANT SERIALIZER
# =======================
class EnseignantSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'name', 'user_type', 'email']


# =======================
# LEÇON SERIALIZER
# =======================
class LeconSerializer(serializers.ModelSerializer):
    enseignant_principal = EnseignantSerializer(read_only=True)

    class Meta:
        model = Lecon
        fields = ['id', 'titre', 'contenu', 'enseignant_principal', 'cours']


# =======================
# COURS SERIALIZER
# =======================
class CoursSerializer(serializers.ModelSerializer):
    enseignant_cadre = EnseignantSerializer(read_only=True)
    principal = EnseignantSerializer(read_only=True)
    enseignants = EnseignantSerializer(many=True, read_only=True)
    lecons = LeconSerializer(many=True, read_only=True)

    class Meta:
        model = Cours
        fields = ['id', 'nom', 'enseignant_cadre', 'principal', 'enseignants', 'departement', 'lecons']


# =======================
# DEPARTEMENT SERIALIZER
# =======================

class EnseignantCadreLightSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="name")  # assure-toi que CustomUser a bien .name
    class Meta:
        model = CustomUser
        fields = ["id", "name"]

class DepartementSerializer(serializers.ModelSerializer):
    enseignant_cadre_name = serializers.SerializerMethodField()

    class Meta:
        model = Departement
        fields = ["id", "nom", "parcours", "cadre", "parcours_id"]

    def get_enseignant_cadre_name(self, obj):
        if obj.enseignant_cadre:
            # utilise .name si dispo, sinon fallback username
            return getattr(obj.enseignant_cadre, "name", obj.enseignant_cadre.username)
        return None


# =======================
# PARCOURS SERIALIZER
# =======================
class ParcoursSerializer(serializers.ModelSerializer):
    admin = EnseignantSerializer(read_only=True)
    departements = DepartementSerializer(many=True, read_only=True)

    class Meta:
        model = Parcours
        fields = ['id', 'nom', 'admin', 'departements']

