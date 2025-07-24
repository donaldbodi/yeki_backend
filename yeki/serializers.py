from rest_framework import serializers
from .models import CustomUser, Parcours
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    class Meta:
        model = CustomUser
        fields = [
            'username', 'email', 'password', 'name',
            'user_type', 'cursus', 'sub_cursus', 'niveau', 'filiere', 'licence'
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
            cursus=validated_data['cursus'],
            sub_cursus=validated_data['sub_cursus'],
            niveau=validated_data['niveau'],
            filiere=validated_data['filiere'],
            licence=validated_data['licence'],
        )
        user.set_password(validated_data['password'])
        if user.user_type == 'apprenant':
            user.is_active = True
        user.save()
        return user



class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        identifier = data.get('identifier')
        password = data.get('password')
        user = authenticate(username=identifier, password=password)

        if user is None:
            try:
                user_obj = User.objects.get(email=identifier)
                user = authenticate(username=user_obj.username, password=password)
            except User.DoesNotExist:
                pass
        elif not user:
            raise serializers.ValidationError("Identifiants incorrects.")
        elif not user.is_active:
            raise serializers.ValidationError("Le compte n'est pas activé. Contactez le service client")
        if user is None:
            raise serializers.ValidationError("Identifiants invalides.")
        data['user'] = user
        return data

class EnseignantSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'name', 'user_type', 'email']

class ParcoursSerializer(serializers.ModelSerializer):
    admin = EnseignantSerializer()
    
    class Meta:
        model = Parcours
        fields = ['id', 'nom', 'admin', 'cours', 'apprenants', 'moyenne']
