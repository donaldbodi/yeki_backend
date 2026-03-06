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


class ChoixSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choix
        fields = ["id", "texte"]


class QuestionSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="type_question")
    choix = serializers.SerializerMethodField()

    class Meta:
        model = Question
        fields = ["id", "text", "type", "points", "choix"]

    def get_choix(self, obj):
        if obj.type_question.lower() == "qcm":
            return [c.texte for c in obj.choix.all()]
        return []


class ExerciceSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)

    class Meta:
        model = Exercice
        fields = ["id", "titre", "enonce", "etoiles", "questions"]


class SessionSerializer(serializers.ModelSerializer):
    temps_restant = serializers.SerializerMethodField()

    class Meta:
        model = SessionExercice
        fields = ["id", "exercice", "debut", "termine", "temps_restant"]

    def get_temps_restant(self, obj):
        return obj.temps_restant()  # déjà défini dans ton modèle


class EvaluationSerializer(serializers.ModelSerializer):
    titre = serializers.CharField(source="exercice.titre", read_only=True)
    etoiles = serializers.IntegerField(source="exercice.etoiles", read_only=True)

    class Meta:
        model = EvaluationExercice
        fields = ["id", "titre", "etoiles", "score", "total", "date"]


# ============================================================
#  serializers_devoirs.py 
# ============================================================

# ─────────────────────────────────────────────────────────────────
# CHOIX / QUESTIONS
# ─────────────────────────────────────────────────────────────────

class ChoixReponseSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ChoixReponse
        fields = ["id", "texte"]  # ⚠️ ne jamais exposer est_correct à l'apprenant !


class ChoixReponseAdminSerializer(serializers.ModelSerializer):
    """Version enseignant — expose la bonne réponse."""
    class Meta:
        model  = ChoixReponse
        fields = ["id", "texte", "est_correct"]


class QuestionDevoirSerializer(serializers.ModelSerializer):
    choix = ChoixReponseSerializer(many=True, read_only=True)

    class Meta:
        model  = QuestionDevoir
        fields = ["id", "texte", "type_question", "points", "ordre", "choix"]


class QuestionDevoirAdminSerializer(serializers.ModelSerializer):
    choix = ChoixReponseAdminSerializer(many=True, read_only=True)

    class Meta:
        model  = QuestionDevoir
        fields = ["id", "texte", "type_question", "points", "ordre", "choix"]


# ─────────────────────────────────────────────────────────────────
# DEVOIR  (list, detail apprenant, detail admin)
# ─────────────────────────────────────────────────────────────────

class DevoirListSerializer(serializers.ModelSerializer):
    """Utilisé dans les listes — inclut le statut dynamique de l'apprenant."""
    statut_apprenant  = serializers.SerializerMethodField()
    note_apprenant    = serializers.SerializerMethodField()
    temps_restant_jours = serializers.SerializerMethodField()
    est_ouvert        = serializers.BooleanField(read_only=True)
    est_expire        = serializers.BooleanField(read_only=True)

    class Meta:
        model  = Devoir
        fields = [
            "id", "titre", "description", "type_devoir", "matiere",
            "niveau", "date_debut", "date_limite", "duree_minutes",
            "note_sur", "coefficient", "concours_lie", "formation_liee",
            "est_publie", "est_ouvert", "est_expire",
            "statut_apprenant", "note_apprenant", "temps_restant_jours",
        ]

    def get_statut_apprenant(self, obj):
        user = self.context["request"].user
        soum = SoumissionDevoir.objects.filter(utilisateur=user, devoir=obj).first()
        if not soum:
            return "non_commence"
        return soum.statut

    def get_note_apprenant(self, obj):
        user = self.context["request"].user
        soum = SoumissionDevoir.objects.filter(utilisateur=user, devoir=obj).first()
        if soum and soum.note is not None:
            return soum.note
        return None

    def get_temps_restant_jours(self, obj):
        delta = obj.date_limite - timezone.now()
        return max(0, delta.days)


class DevoirDetailSerializer(serializers.ModelSerializer):
    """Détail pour l'apprenant — questions sans bonnes réponses."""
    questions = QuestionDevoirSerializer(many=True, read_only=True)

    class Meta:
        model  = Devoir
        fields = [
            "id", "titre", "description", "type_devoir", "matiere",
            "niveau", "enonce", "date_debut", "date_limite", "duree_minutes",
            "note_sur", "coefficient", "tentatives_max",
            "concours_lie", "formation_liee", "questions",
        ]


class DevoirCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Devoir
        fields = [
            "titre", "description", "type_devoir", "matiere", "niveau",
            "enonce", "date_debut", "date_limite", "duree_minutes",
            "note_sur", "coefficient", "tentatives_max",
            "concours_lie", "formation_liee", "cours_lie",
            "est_publie", "acces_restreint",
        ]

    def validate(self, data):
        if data.get("date_limite") and data.get("date_debut"):
            if data["date_limite"] <= data["date_debut"]:
                raise serializers.ValidationError(
                    "La date limite doit être postérieure à la date de début."
                )
        return data


# ─────────────────────────────────────────────────────────────────
# SOUMISSION
# ─────────────────────────────────────────────────────────────────

class ReponseSubmitSerializer(serializers.Serializer):
    """Reçu du Flutter : {question_id: réponse, ...}"""
    reponses = serializers.DictField(
        child=serializers.CharField(allow_blank=True)
    )


class SoumissionDetailSerializer(serializers.ModelSerializer):
    devoir_titre = serializers.CharField(source="devoir.titre", read_only=True)
    temps_restant = serializers.SerializerMethodField()

    class Meta:
        model  = SoumissionDevoir
        fields = [
            "id", "devoir", "devoir_titre", "statut",
            "debut", "soumis_le", "note", "commentaire",
            "temps_restant", "nb_focus_perdu", "est_suspecte",
        ]

    def get_temps_restant(self, obj):
        return obj.temps_restant_secondes()


# ─────────────────────────────────────────────────────────────────
# OLYMPIADE
# ─────────────────────────────────────────────────────────────────

class OlympiadeListSerializer(serializers.ModelSerializer):
    statut              = serializers.SerializerMethodField()
    est_inscrit         = serializers.SerializerMethodField()
    nb_inscrits         = serializers.SerializerMethodField()
    inscription_ouverte = serializers.SerializerMethodField()

    class Meta:
        model  = Olympiade
        fields = [
            "id", "titre", "description", "matiere", "niveau", "edition",
            "date_ouverture_inscription", "date_cloture_inscription",
            "date_debut_olympiade", "date_fin_olympiade",
            "duree_minutes", "nb_questions", "note_sur",
            "prix_1er", "prix_2eme", "prix_3eme",
            "statut", "est_inscrit", "nb_inscrits", "inscription_ouverte",
        ]

    def get_statut(self, obj):
        return obj.statut_auto

    def get_est_inscrit(self, obj):
        user = self.context["request"].user
        return InscriptionOlympiade.objects.filter(
            olympiade=obj, apprenant=user
        ).exists()

    def get_nb_inscrits(self, obj):
        return obj.inscriptions.count()

    def get_inscription_ouverte(self, obj):
        now = timezone.now()
        return obj.date_ouverture_inscription <= now <= obj.date_cloture_inscription


class OlympiadeDetailSerializer(OlympiadeListSerializer):
    """Inclut les questions seulement si l'olympiade est EN COURS pour l'apprenant inscrit."""
    questions = serializers.SerializerMethodField()

    class Meta(OlympiadeListSerializer.Meta):
        fields = OlympiadeListSerializer.Meta.fields + ["questions"]

    def get_questions(self, obj):
        user = self.context["request"].user
        inscription = InscriptionOlympiade.objects.filter(
            olympiade=obj, apprenant=user, soumis=False
        ).first()

        # Questions visibles uniquement si l'olympiade est en cours ET l'apprenant a démarré
        if not inscription or not inscription.session_demarree:
            return []
        if obj.statut_auto != "en_cours":
            return []

        questions = obj.devoir.questions.all() if obj.devoir else []
        data = QuestionDevoirSerializer(questions, many=True).data

        # Mélange côté serveur si activé
        if obj.melanger_questions:
            import random
            data_list = list(data)
            random.seed(str(user.id) + str(obj.id))  # seed déterministe par participant
            random.shuffle(data_list)
            return data_list
        return data


class InscriptionOlympiadeSerializer(serializers.ModelSerializer):
    olympiade_titre = serializers.CharField(source="olympiade.titre", read_only=True)
    statut_olympiade = serializers.SerializerMethodField()
    temps_restant   = serializers.SerializerMethodField()

    class Meta:
        model  = InscriptionOlympiade
        fields = [
            "id", "olympiade", "olympiade_titre", "statut",
            "inscrit_le", "session_demarree", "heure_debut_compo",
            "soumis", "soumis_automatique", "note", "classement",
            "nb_focus_perdu", "est_suspecte",
            "statut_olympiade", "temps_restant",
        ]

    def get_statut_olympiade(self, obj):
        return obj.olympiade.statut_auto

    def get_temps_restant(self, obj):
        return obj.temps_restant_secondes()


class ClassementOlympiadeSerializer(serializers.ModelSerializer):
    nom_complet = serializers.SerializerMethodField()
    username    = serializers.CharField(source="apprenant.username", read_only=True)

    class Meta:
        model  = ClassementOlympiade
        fields = ["rang", "nom_complet", "username", "note", "mention"]

    def get_nom_complet(self, obj):
        u = obj.apprenant
        full = f"{u.first_name} {u.last_name}".strip()
        return full or u.username


class ForumMessageSerializer(serializers.ModelSerializer):
    replies = serializers.SerializerMethodField()

    class Meta:
        model = ForumMessage
        fields = ['id', 'parent', 'text', 'image', 'audio', 'sender', 'role', 'timestamp', 'replies']

    def get_replies(self, obj):
        serializer = ForumMessageSerializer(obj.replies.all(), many=True)
        return serializer.data
    

class ProfilDetailSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    avatar = serializers.SerializerMethodField()

    # Champs user.first/last_name exposés à plat
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name  = serializers.CharField(source="user.last_name",  read_only=True)
    email      = serializers.CharField(source="user.email",      read_only=True)
    username   = serializers.CharField(source="user.username",   read_only=True)

    class Meta:
        model = Profile
        fields = [
            "id", "user", "user_type",
            "first_name", "last_name", "email", "username",
            "phone", "bio",
            "cursus", "sub_cursus", "niveau", "filiere", "licence",
            "is_active", "avatar",
        ]

    def get_avatar(self, obj):
        if obj.avatar:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.avatar.url)
            return obj.avatar.url
        return None