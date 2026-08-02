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
            "phone",
            "date_naissance",
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

    # Ajoutés à la demande explicite du produit (aucune règle CDC ne les
    # rend obligatoires, mais aucune ne l'interdit non plus — voir
    # docs/ecarts/p2_inscription_cursus_root_cause.md).
    phone = serializers.CharField(required=True, max_length=20)
    date_naissance = serializers.DateField(required=True)

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
        # P5.4 : l'auto-inscription publique (AllowAny) ne doit JAMAIS
        # permettre de choisir un rôle privilégié — faille trouvée lors de
        # la refonte de l'écran d'inscription (n'importe qui pouvait
        # s'auto-créer admin/enseignant_admin/service_client et recevoir
        # un token immédiatement utilisable). La création des autres rôles
        # reste réservée à apps/accounts/views/admin_enseignants.py,
        # authentifié et réservé aux administrateurs.
        allowed = ["apprenant", "enseignant"]
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
        # P5.4 : "name" était exigé mais jamais persisté nulle part (ni
        # User.first_name/last_name, ni Profile) — bug corrigé ici. Un seul
        # champ "nom complet" côté écran/API, scindé sur le premier espace.
        name = (validated_data.get("name") or "").strip()
        if name:
            first, *rest = name.split(" ", 1)
            user.first_name = first
            user.last_name = rest[0] if rest else ""
        user.set_password(validated_data["password"])
        user.save()

        # Bug corrigé : `cursus` n'était jamais envoyé par le frontend
        # (champ resté optionnel, toujours `None` en pratique) alors que
        # `ApprenantCursusAPIView` (apps/formation/views/cours.py) exige
        # `profile.cursus` non vide pour lister le moindre cours — un
        # nouvel apprenant ne voyait donc jamais aucun cours. `parcours`
        # est déjà obligatoire à l'inscription : dérivé directement de
        # l'objet réellement sélectionné plutôt que d'une chaîne
        # re-saisie, garantit par construction la correspondance avec
        # `Parcours.nom` attendue par cette vue.
        parcours = validated_data.get("parcours")
        cursus = parcours.nom if parcours else validated_data.get("cursus")

        profile = Profile.objects.create(
            user=user,
            user_type=validated_data.get("user_type"),
            departement=validated_data.get("departement"),
            cursus=cursus,
            sub_cursus=validated_data.get("sub_cursus"),
            niveau=validated_data.get("niveau"),
            filiere=validated_data.get("filiere"),
            licence=validated_data.get("licence"),
            phone=validated_data.get("phone", ""),
            date_naissance=validated_data.get("date_naissance"),
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
            "date_naissance",
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
