from rest_framework import serializers

from apps.core.models import HistoriqueActivite, AppVersion


class HistoriqueActiviteSerializer(serializers.ModelSerializer):
    action_label = serializers.CharField(source="get_action_display", read_only=True)
    user_nom = serializers.SerializerMethodField()

    class Meta:
        model = HistoriqueActivite
        fields = [
            "id",
            "action",
            "action_label",
            "description",
            "data",
            "timestamp",
            "objet_id",
            "objet_type",
            "user_nom",
        ]

    def get_user_nom(self, obj):
        u = obj.user
        return f"{u.first_name} {u.last_name}".strip() or u.username


class AppVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppVersion
        fields = [
            "id",
            "platform",
            "version_code",
            "version_name",
            "download_url",
            "changelog",
            "min_version_code",
            "force_update",
            "is_active",
            "file_size",
            "release_date",
            "created_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class AppVersionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppVersion
        fields = [
            "platform",
            "version_code",
            "version_name",
            "download_url",
            "changelog",
            "min_version_code",
            "force_update",
            "is_active",
            "file_size",
        ]
