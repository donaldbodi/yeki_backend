from rest_framework import serializers

from apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "type", "titre", "contenu", "est_lue", "cree_le", "action_url"]


class NotificationCreateSerializer(serializers.Serializer):
    utilisateur_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=Notification.TYPE_CHOICES)
    titre = serializers.CharField()
    contenu = serializers.CharField()
    objet_id = serializers.IntegerField(required=False, allow_null=True)
    objet_type = serializers.CharField(required=False, allow_blank=True)
    action_url = serializers.CharField(required=False, allow_blank=True)

    def create(self, validated_data):
        return Notification.objects.create(**validated_data)
