from rest_framework import serializers
from .models import CustomUser
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import User
from django.contrib.auth import authenticate


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    class Meta:
        model = CustomUser
        fields = [
            'username', 'email', 'password', 'name',
            'user_type', 'cursus', 'sub_cursus', 'niveau', 'filiere', 'licence'
        ]

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

        if user is None:
            raise serializers.ValidationError("Identifiants invalides.")
        data['user'] = user
        return data
