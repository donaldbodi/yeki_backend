from django.contrib import admin

from apps.core.models import ParametreSysteme

# `AppVersion` a déjà son admin — `yeki/admin.py:30-44` (`AppVersionAdmin`,
# legacy mais actif et fonctionnel, confirmé en essayant d'en enregistrer
# un second ici : `AlreadyRegistered`). Pas de doublon ajouté (règle 1) —
# la commande `publier_version_android` suffit pour publier la ligne
# Android réelle ; l'admin déjà existant permet de gérer les suivantes.


@admin.register(ParametreSysteme)
class ParametreSystemeAdmin(admin.ModelAdmin):
    list_display = ["cle", "valeur", "type", "modifiable_par", "description"]
    list_filter = ["type", "modifiable_par"]
    search_fields = ["cle", "description"]
    ordering = ["cle"]
