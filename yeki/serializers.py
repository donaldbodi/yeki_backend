from rest_framework import serializers
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import Parcours, Departement, Cours, Lecon, Profile

User = get_user_model()

# =======================
# USER SERIALIZER
# =======================
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
        ]


class ProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Profile
        fields = [
            'id', 'user', 'user_type', 'cursus', 'sub_cursus',
            'niveau', 'filiere', 'licence', 'is_active', 'avatar', 'bio'
        ]


# =======================
# REGISTER SERIALIZER
# =======================
User = get_user_model()

class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    name = serializers.CharField(required=True)
    username = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True)

    user_type = serializers.CharField(required=True)

    cursus = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    sub_cursus = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    niveau = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    filiere = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    licence = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def create(self, validated_data):
        # Crée l'utilisateur Django
        user = User.objects.create(
            username=validated_data['username'],
            email=validated_data['email'],
        )
        user.set_password(validated_data['password'])
        user.save()

        # Crée le profil relié
        profile = Profile.objects.create(
            user=user,
            user_type=validated_data.get('user_type'),
            cursus=validated_data.get('cursus'),
            sub_cursus=validated_data.get('sub_cursus'),
            niveau=validated_data.get('niveau'),
            filiere=validated_data.get('filiere'),
            licence=validated_data.get('licence'),
        )

        if profile.user_type == 'apprenant':
            profile.is_active = True
            profile.save()

        return profile


# =======================
# LOGIN SERIALIZER
# =======================
class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        identifier = data.get('identifier')
        password = data.get('password')

        # login par username
        user = authenticate(username=identifier, password=password)

        # login par email
        if user is None:
            try:
                user_obj = User.objects.get(email=identifier)
                user = authenticate(username=user_obj.username, password=password)
            except User.DoesNotExist:
                raise serializers.ValidationError("Identifiants incorrects.")

        if not user.profile.is_active:
            raise serializers.ValidationError("Compte non activé.")

        data['user'] = user
        return data


# =======================
# ENSEIGNANT SERIALIZER
# =======================
class EnseignantSerializer(serializers.ModelSerializer):
    user = UserSerializer()

    class Meta:
        model = Profile
        fields = ['id', 'user', 'user_type']


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
        fields = [
            'id',
            'titre',
            'niveau',

            # UI / Présentation
            'description_brief',
            'color_code',
            'icon_name',

            # Stats
            'nb_lecons',
            'nb_devoirs',
            'nb_apprenants',

            # Relations
            'departement',
            'enseignant_principal',
            'enseignants',
            'lecons',
        ]


class CoursCreateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Cours
        fields = [
            'titre',
            'niveau',
            'departement',

            # UI
            'description_brief',
            'color_code',
            'icon_name',

            # pédagogique
            'enseignant_principal',
        ]

    def validate_color_code(self, value):
        if value and (not value.startswith('#') or len(value) != 7):
            raise serializers.ValidationError(
                "Le code couleur doit être au format #RRGGBB"
            )
        return value

    def create(self, validated_data):
        request = self.context['request']
        user = request.user

        return Cours.create_cours(
            user=user,
            departement=validated_data['departement'],
            titre=validated_data['titre'],
            niveau=validated_data['niveau'],

            # UI
            description_brief=validated_data.get('description_brief'),
            color_code=validated_data.get('color_code'),
            icon_name=validated_data.get('icon_name'),

            # 👇 ENSEIGNANT PRINCIPAL
            enseignant_principal=validated_data.get('enseignant_principal', None),
        )


class CoursListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cours
        fields = [
            'id',
            'titre',
            'niveau',
            'description_brief',
            'color_code',
            'icon_name',
            'nb_lecons',
            'nb_devoirs',
        ]

# =======================
# DEPARTEMENT SERIALIZER
# =======================
class EnseignantCadreLightSerializer(serializers.ModelSerializer): # enseignant serializer joue le meme role
    user = UserSerializer()
    class Meta:
        model = Profile
        fields = ["id", "user", 'user_type']


class DepartementSerializer(serializers.ModelSerializer):
    cadre = EnseignantCadreLightSerializer(read_only=True)
    cours = CoursSerializer(many=True, read_only=True)

    class Meta:
        model = Departement
        fields = ["id", "nom", "parcours", "cadre", "cours"]


# =======================
# PARCOURS SERIALIZER
# =======================
class ParcoursSerializer(serializers.ModelSerializer):
    admin = EnseignantSerializer(read_only=True)
    departements = DepartementSerializer(many=True, read_only=True)

    class Meta:
        model = Parcours
        fields = ['id', 'nom', 'admin', 'departements']
