from rest_framework import serializers

from apps.accounts.models import Profile
from apps.forum.models import QuestionForum, ReponseQuestion


class ReponseSerializer(serializers.ModelSerializer):
    auteur_nom = serializers.CharField(source="auteur.get_full_name", read_only=True)
    auteur_username = serializers.CharField(source="auteur.username", read_only=True)
    auteur_est_enseignant = serializers.SerializerMethodField()
    nb_likes = serializers.SerializerMethodField()
    mon_like = serializers.SerializerMethodField()

    class Meta:
        model = ReponseQuestion
        fields = [
            "id",
            "contenu",
            "cree_le",
            "est_solution",
            "auteur_nom",
            "auteur_username",
            "auteur_est_enseignant",
            "nb_likes",
            "mon_like",
        ]

    def get_auteur_est_enseignant(self, obj):
        try:
            profile = obj.auteur.profile
            return profile.user_type in [
                "enseignant",
                "enseignant_principal",
                "enseignant_cadre",
                "enseignant_admin",
            ]
        except Profile.DoesNotExist:
            return False

    def get_nb_likes(self, obj):
        return obj.likes.count()

    def get_mon_like(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(utilisateur=request.user).exists()
        return False


class QuestionForumDetailSerializer(serializers.ModelSerializer):
    auteur_nom = serializers.SerializerMethodField()
    auteur_username = serializers.CharField(source="auteur.username", read_only=True)
    auteur_est_enseignant = serializers.SerializerMethodField()
    nb_reponses = serializers.IntegerField(read_only=True)
    reponses = ReponseSerializer(many=True, read_only=True)
    image_url = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = QuestionForum
        fields = [
            "id",
            "contenu",
            "source",
            "cree_le",
            "est_resolue",
            "nb_vues",
            "nb_reponses",
            "reponses",
            "lecon_id",
            "lecon_titre",
            "cours_id",
            "cours_titre",
            "exercice_id",
            "exercice_titre",
            "devoir_id",
            "devoir_titre",
            "auteur_nom",
            "auteur_username",
            "auteur_est_enseignant",
            "image_url",
            "audio_url",
        ]

    def get_auteur_nom(self, obj):
        user = obj.auteur
        nom = f"{user.first_name} {user.last_name}".strip()
        return nom if nom else user.username

    def get_auteur_est_enseignant(self, obj):
        try:
            profile = obj.auteur.profile
            return profile.user_type in [
                "enseignant",
                "enseignant_principal",
                "enseignant_cadre",
                "enseignant_admin",
            ]
        except Profile.DoesNotExist:
            return False

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

    def get_audio_url(self, obj):
        if obj.audio:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.audio.url)
            return obj.audio.url
        return None


class QuestionForumListSerializer(serializers.ModelSerializer):
    auteur_nom = serializers.SerializerMethodField()
    auteur_username = serializers.CharField(source="auteur.username", read_only=True)
    auteur_est_enseignant = serializers.SerializerMethodField()
    nb_reponses = serializers.IntegerField(read_only=True)
    image_url = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = QuestionForum
        fields = [
            "id",
            "contenu",
            "source",
            "cree_le",
            "est_resolue",
            "nb_vues",
            "nb_reponses",
            "lecon_id",
            "lecon_titre",
            "cours_id",
            "cours_titre",
            "exercice_id",
            "exercice_titre",
            "devoir_id",
            "devoir_titre",
            "auteur_nom",
            "auteur_username",
            "auteur_est_enseignant",
            "image_url",
            "audio_url",
        ]

    def get_auteur_nom(self, obj):
        user = obj.auteur
        nom = f"{user.first_name} {user.last_name}".strip()
        return nom if nom else user.username

    def get_auteur_est_enseignant(self, obj):
        try:
            profile = obj.auteur.profile
            return profile.user_type in [
                "enseignant",
                "enseignant_principal",
                "enseignant_cadre",
                "enseignant_admin",
            ]
        except Profile.DoesNotExist:
            return False

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

    def get_audio_url(self, obj):
        if obj.audio:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.audio.url)
            return obj.audio.url
        return None


class QuestionForumCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionForum
        fields = [
            "contenu",
            "source",
            "lecon_id",
            "lecon_titre",
            "cours_id",
            "cours_titre",
            "exercice_id",
            "exercice_titre",
            "devoir_id",
            "devoir_titre",
            "image",
            "audio",
        ]

    def create(self, validated_data):
        validated_data["auteur"] = self.context["request"].user
        return super().create(validated_data)


class ReponseCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReponseQuestion
        fields = ["contenu"]

    def create(self, validated_data):
        validated_data["auteur"] = self.context["request"].user
        validated_data["question"] = self.context["question"]
        return super().create(validated_data)
