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
    created_by = EnseignantSerializer(read_only=True)

    class Meta:
        model = Lecon
        fields = ['id', 'titre', 'contenu_html', 'created_by', 'cours', 'created_at']


# =======================
# COURS SERIALIZER
# =======================
class CoursSerializer(serializers.ModelSerializer):
    enseignant_principal = EnseignantSerializer(read_only=True)
    enseignants = EnseignantSerializer(many=True, read_only=True)
    lecons = LeconSerializer(many=True, read_only=True)

    class Meta:
        model = Cours
        fields = ['id', 'titre', 'niveau', 'enseignant_principal', 'enseignants', 'departement', 'lecons']

class CoursCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cours
        fields = ['titre', 'niveau', 'departement', 'enseignant_principal']

    def create(self, validated_data):
        user = self.context['request'].user
        departement = validated_data['departement']
        titre = validated_data['titre']
        niveau = validated_data['niveau']
        enseignant_principal = validated_data.get('enseignant_principal', None)

        return Cours.create_cours(
            user=user,
            departement=departement,
            titre=titre,
            niveau=niveau,
            enseignant_principal=enseignant_principal
        )


# =======================
# DEPARTEMENT SERIALIZER
# =======================
class EnseignantCadreLightSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["id", "name"]

class DepartementSerializer(serializers.ModelSerializer):
    cadre = EnseignantCadreLightSerializer(read_only=True)
    cours = CoursSerializer(many=True, read_only=True)

    class Meta:
        model = Departement
        fields = ["id", "nom", "parcours", "cadre" , "cours"]


# =======================
# PARCOURS SERIALIZER
# =======================
class ParcoursSerializer(serializers.ModelSerializer):
    admin = EnseignantSerializer(read_only=True)
    departements = DepartementSerializer(many=True, read_only=True)

    class Meta:
        model = Parcours
        fields = ['id', 'nom', 'admin', 'departements']

