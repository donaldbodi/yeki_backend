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
    # departement envoyé comme id (multipart ou json)
    departement = serializers.PrimaryKeyRelatedField(
        queryset=Departement.objects.all()
    )

    # enseignant_principal optionnel
    enseignant_principal = serializers.PrimaryKeyRelatedField(
        queryset=Profile.objects.filter(user_type='enseignant_principal'),
        required=False,
        allow_null=True
    )

    class Meta:
        model  = Cours
        fields = [
            'titre',
            'niveau',
            'matiere',
            'concours',
            'description_brief',
            'color_code',
            'icon_name',
            'departement',
            'enseignant_principal',
        ]
        extra_kwargs = {
            'titre':             {'required': True},
            'niveau':            {'required': True},
            'matiere':           {'required': False, 'allow_blank': True},
            'concours':          {'required': False, 'allow_blank': True},
            'description_brief': {'required': False, 'allow_blank': True, 'allow_null': True},
            'color_code':        {'required': False},
            'icon_name':         {'required': False},
        }

    # ── Validation du département ────────────────────────────────
    def validate_departement(self, departement):
        request = self.context.get('request')
        if not request:
            return departement
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            raise serializers.ValidationError("Profil introuvable.")

        # Un cadre ne peut créer que dans SON département
        if profile.user_type == 'enseignant_cadre':
            if departement.cadre != profile:
                raise serializers.ValidationError(
                    "Vous ne pouvez créer un cours que dans votre propre département."
                )
        return departement

    # ── Validation de l'enseignant principal ─────────────────────
    def validate_enseignant_principal(self, ep):
        if ep is not None and ep.user_type != 'enseignant_principal':
            raise serializers.ValidationError(
                "Cet utilisateur n'est pas un enseignant principal."
            )
        return ep

    # ── Validation globale ───────────────────────────────────────
    def validate(self, attrs):
        color = attrs.get('color_code', '#008080')
        if color and not color.startswith('#'):
            attrs['color_code'] = f'#{color}'
        return attrs

    def create(self, validated_data):
        return Cours.objects.create(**validated_data)


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


# ═══════════════════════════════════════════════════════════════
#  À ajouter à la fin de serializers.py
# ═══════════════════════════════════════════════════════════════

class ModuleUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer pour la MODIFICATION partielle d'un module.
    Gère le conflit d'ordre : si l'ordre choisi est déjà pris
    dans le même cours, on décale les autres modules.
    """
    class Meta:
        model  = Module
        fields = ['titre', 'description', 'ordre']
        extra_kwargs = {
            'titre':       {'required': False},
            'description': {'required': False},
            'ordre':       {'required': False},
        }

    def validate_ordre(self, value):
        if value < 1:
            raise serializers.ValidationError("L'ordre doit être supérieur ou égal à 1.")
        return value

    def update(self, instance, validated_data):
        nouvel_ordre = validated_data.get('ordre')

        # Si l'ordre change ET qu'un autre module occupe déjà cette position
        if nouvel_ordre and nouvel_ordre != instance.ordre:
            conflit = Module.objects.filter(
                cours=instance.cours,
                ordre=nouvel_ordre
            ).exclude(pk=instance.pk).first()

            if conflit:
                # Échange des positions
                conflit.ordre = instance.ordre
                conflit.save(update_fields=['ordre'])

        return super().update(instance, validated_data)


class LeconUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer pour la MODIFICATION partielle d'une leçon.
    Tous les champs sont optionnels (PATCH).
    Valide que le module cible appartient bien au même cours.
    """
    class Meta:
        model  = Lecon
        fields = [
            'titre',
            'description',
            'module',
            'fichier_pdf',
            'video',
        ]
        extra_kwargs = {
            'titre':       {'required': False},
            'description': {'required': False},
            'module':      {'required': False, 'allow_null': True},
            'fichier_pdf': {'required': False, 'allow_null': True},
            'video':       {'required': False, 'allow_null': True},
        }

    def validate_fichier_pdf(self, value):
        if value and not value.name.lower().endswith('.pdf'):
            raise serializers.ValidationError("Seuls les fichiers PDF sont autorisés.")
        return value

    def validate_video(self, value):
        ALLOWED = ['.mp4', '.mov', '.avi', '.mkv', '.webm']
        if value and not any(value.name.lower().endswith(ext) for ext in ALLOWED):
            raise serializers.ValidationError(
                f"Format vidéo non supporté. Formats acceptés : {', '.join(ALLOWED)}"
            )
        return value

    def validate_module(self, module):
        """Le module cible doit appartenir au même cours que la leçon."""
        if module is None:
            return module
        lecon = self.instance
        if lecon and module.cours_id != lecon.cours_id:
            raise serializers.ValidationError(
                "Le module cible doit appartenir au même cours que cette leçon."
            )
        return module


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
    

class ReponseSerializer(serializers.ModelSerializer):
    auteur_nom      = serializers.CharField(source="auteur.get_full_name", read_only=True)
    auteur_username = serializers.CharField(source="auteur.username", read_only=True)
    nb_likes        = serializers.SerializerMethodField()
    mon_like        = serializers.SerializerMethodField()

    class Meta:
        model  = ReponseQuestion
        fields = [
            "id", "contenu", "cree_le", "est_solution",
            "auteur_nom", "auteur_username",
            "nb_likes", "mon_like",
        ]

    def get_nb_likes(self, obj):
        return obj.likes.count()

    def get_mon_like(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(utilisateur=request.user).exists()
        return False


class QuestionForumListSerializer(serializers.ModelSerializer):
    auteur_nom      = serializers.CharField(source="auteur.get_full_name", read_only=True)
    auteur_username = serializers.CharField(source="auteur.username", read_only=True)
    nb_reponses     = serializers.IntegerField(read_only=True)

    class Meta:
        model  = QuestionForum
        fields = [
            "id", "contenu", "source", "cree_le", "est_resolue", "nb_vues",
            "nb_reponses",
            "lecon_id", "lecon_titre", "cours_id", "cours_titre",
            "exercice_id", "exercice_titre",
            "devoir_id", "devoir_titre",
            "auteur_nom", "auteur_username",
        ]


class QuestionForumDetailSerializer(serializers.ModelSerializer):
    auteur_nom      = serializers.CharField(source="auteur.get_full_name", read_only=True)
    auteur_username = serializers.CharField(source="auteur.username", read_only=True)
    nb_reponses     = serializers.IntegerField(read_only=True)
    reponses        = ReponseSerializer(many=True, read_only=True)

    class Meta:
        model  = QuestionForum
        fields = [
            "id", "contenu", "source", "cree_le", "est_resolue", "nb_vues",
            "nb_reponses", "reponses",
            "lecon_id", "lecon_titre", "cours_id", "cours_titre",
            "exercice_id", "exercice_titre",
            "devoir_id", "devoir_titre",
            "auteur_nom", "auteur_username",
        ]


class QuestionForumCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = QuestionForum
        fields = [
            "contenu", "source",
            "lecon_id", "lecon_titre", "cours_id", "cours_titre",
            "exercice_id", "exercice_titre",
            "devoir_id", "devoir_titre",
        ]

    def create(self, validated_data):
        validated_data["auteur"] = self.context["request"].user
        return super().create(validated_data)


class ReponseCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ReponseQuestion
        fields = ["contenu"]

    def create(self, validated_data):
        validated_data["auteur"]   = self.context["request"].user
        validated_data["question"] = self.context["question"]
        return super().create(validated_data)
