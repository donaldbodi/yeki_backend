from rest_framework import serializers
from django.contrib.auth import authenticate, get_user_model

from apps.accounts.models import Profile
from apps.formation.models import Departement, Parcours

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
        ]


class ProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Profile
        fields = [
            "id",
            "user",
            "user_type",
            "cursus",
            "sub_cursus",
            "niveau",
            "filiere",
            "licence",
            "is_active",
            "avatar",
            "bio",
        ]


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    name = serializers.CharField(required=True)
    username = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True)

    user_type = serializers.CharField(required=True)

    # CDC §13.2 (recette backend) : parcours/département/niveau obligatoires
    # à l'inscription. `parcours` n'est pas stocké (dérivé de
    # `departement.parcours`) : il sert uniquement à vérifier la cohérence
    # avec le `departement` envoyé.
    parcours = serializers.PrimaryKeyRelatedField(queryset=Parcours.objects.all(), required=True)
    departement = serializers.PrimaryKeyRelatedField(
        queryset=Departement.objects.all(), required=True
    )
    niveau = serializers.CharField(required=True, allow_blank=False)

    cursus = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    sub_cursus = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    filiere = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    licence = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate(self, data):
        parcours = data.get("parcours")
        departement = data.get("departement")
        if parcours and departement and departement.parcours_id != parcours.id:
            raise serializers.ValidationError(
                {"parcours": "Ce département n'appartient pas au parcours sélectionné."}
            )
        return data

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Ce nom d'utilisateur est déjà pris.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Cette adresse email est déjà utilisée.")
        return value

    def validate_password(self, value):
        if len(value) < 6:
            raise serializers.ValidationError(
                "Le mot de passe doit contenir au moins 6 caractères."
            )
        return value

    def validate_user_type(self, value):
        allowed = [
            "apprenant",
            "enseignant",
            "enseignant_principal",
            "enseignant_cadre",
            "enseignant_admin",
            "admin",
            "service_client",
        ]
        if value not in allowed:
            raise serializers.ValidationError(f"Type d'utilisateur invalide. Valeurs : {allowed}")
        return value

    def create(self, validated_data):
        email = validated_data.get("email")
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError({"email": "Cette adresse email est déjà utilisée."})

        user = User.objects.create(
            username=validated_data["username"],
            email=email,
        )
        user.set_password(validated_data["password"])
        user.save()

        profile = Profile.objects.create(
            user=user,
            user_type=validated_data.get("user_type"),
            departement=validated_data.get("departement"),
            cursus=validated_data.get("cursus"),
            sub_cursus=validated_data.get("sub_cursus"),
            niveau=validated_data.get("niveau"),
            filiere=validated_data.get("filiere"),
            licence=validated_data.get("licence"),
        )

        if profile.user_type == "apprenant":
            profile.is_active = True
            profile.save()

        return profile


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        identifier = data.get("identifier")
        password = data.get("password")

        user = authenticate(username=identifier, password=password)

        if user is None:
            try:
                user_obj = User.objects.get(email=identifier)
                user = authenticate(username=user_obj.username, password=password)
            except User.DoesNotExist:
                raise serializers.ValidationError("Identifiants incorrects.")

        if user is None:
            raise serializers.ValidationError("Identifiants incorrects.")

        if not user.profile.is_active:
            raise serializers.ValidationError("Compte non activé.")

        data["user"] = user
        return data


class EnseignantSerializer(serializers.ModelSerializer):
    user = UserSerializer()

    class Meta:
        model = Profile
        fields = ["id", "user", "user_type"]


class EnseignantCadreLightSerializer(serializers.ModelSerializer):
    user = UserSerializer()

    class Meta:
        model = Profile
        fields = ["id", "user", "user_type"]


class ProfilDetailSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    avatar = serializers.SerializerMethodField()

    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Profile
        fields = [
            "id",
            "user",
            "user_type",
            "first_name",
            "last_name",
            "email",
            "username",
            "phone",
            "bio",
            "ville",
            "cursus",
            "sub_cursus",
            "niveau",
            "filiere",
            "licence",
            "is_active",
            "avatar",
        ]

    def get_avatar(self, obj):
        if obj.avatar:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.avatar.url)
            return obj.avatar.url
        return None
