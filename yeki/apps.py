from django.apps import AppConfig

from yeki_backend import yeki


class YekiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "yeki"

def ready(self):
    return yeki.signals
