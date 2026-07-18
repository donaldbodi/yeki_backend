from django.contrib import admin

from apps.core.models import ParametreSysteme


@admin.register(ParametreSysteme)
class ParametreSystemeAdmin(admin.ModelAdmin):
    list_display = ["cle", "valeur", "type", "modifiable_par", "description"]
    list_filter = ["type", "modifiable_par"]
    search_fields = ["cle", "description"]
    ordering = ["cle"]
