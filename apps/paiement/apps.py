from django.apps import AppConfig


class PaiementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.paiement"

    def ready(self):
        import apps.paiement.signals  # noqa: F401
