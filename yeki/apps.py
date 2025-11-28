from django.apps import AppConfig


class YekiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "yeki"

    def ready(self):
        return yeki.signals
