from rest_framework import serializers
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import *

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
    fichier_pdf = serializers.SerializerMethodField()
    created_by = EnseignantSerializer(read_only=True)

    class Meta:
        model = Lecon
        fields = [
            'id',
            'titre',
            'description',
            'fichier_pdf',
            'video',
            'module',
            'created_by',
            'cours',
            'created_at',
        ]

    def get_fichier_pdf(self, obj):
        if obj.fichier_pdf:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.fichier_pdf.url)
            return obj.fichier_pdf.url
        return None


class LeconCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lecon
        fields = [
            'titre',
            'description',
            'fichier_pdf',
            'video',
            'module',
        ]

    def validate_fichier_pdf(self, value):
        if not value.name.endswith('.pdf'):
            raise serializers.ValidationError("Seuls les fichiers PDF sont autorisés.")
        return value


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
            color_code=validated_data.get('color_code'),
            icon_name=validated_data.get('icon_name'),

            # 👇 ENSEIGNANT PRINCIPAL
            enseignant_principal=validated_data.get('enseignant_principal', None),
            description_brief=validated_data.get('description_brief'),
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


class CursusApprenantSerializer(serializers.ModelSerializer):
    enseignant_principal = serializers.SerializerMethodField()
    title = serializers.CharField(source="titre")
    description = serializers.CharField(source="description_brief")
    lessons = serializers.IntegerField(source="nb_lecons")
    assignments = serializers.IntegerField(source="nb_devoirs")
    icon = serializers.CharField(source="icon_name")
    color = serializers.CharField(source="color_code")

    class Meta:
        model = Cours
        fields = [
            "id",
            "title",
            "description",
            "enseignant_principal",
            "lessons",
            "assignments",
            "icon",
            "color",
        ]

    def get_enseignant_principal(self, obj):
        if obj.enseignant_principal:
            return obj.enseignant_principal.user.username
        return "—"


class ModuleCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ['titre', 'ordre', 'description']

class ModuleListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ['id', 'titre', 'ordre', 'description']

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


class LeconLightSerializer(serializers.ModelSerializer):
    fichier_pdf = serializers.SerializerMethodField()
    video = serializers.SerializerMethodField()

    class Meta:
        model = Lecon
        fields = [
            'id',
            'titre',
            'description',
            'fichier_pdf',
            'video',
        ]

    def get_fichier_pdf(self, obj):
        if obj.fichier_pdf:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.fichier_pdf.url)
        return None

    def get_video(self, obj):
        if obj.video:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.video.url)
        return None



class ModuleAvecLeconsSerializer(serializers.ModelSerializer):
    lecons = LeconLightSerializer(many=True, read_only=True)

    class Meta:
        model = Module
        fields = [
            'id',
            'titre',
            'description',
            'ordre',
            'lecons',
        ]


class QuestionExerciceSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionExercice
        fields = [
            'id',
            'texte',
            'type',
            'choix',
            'points',
        ]


class ExerciceSerializer(serializers.ModelSerializer):
    questions = QuestionExerciceSerializer(many=True, read_only=True)

    class Meta:
        model = Exercice
        fields = [
            'id',
            'titre',
            'enonce',
            'difficulte',
            'questions',
        ]


class ExerciceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exercice
        fields = [
            'titre',
            'enonce',
            'difficulte',
            'module',
        ]
