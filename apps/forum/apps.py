from django.apps import AppConfig


class ForumConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.forum"

    def ready(self):
        import apps.forum.signals  # noqa: F401
