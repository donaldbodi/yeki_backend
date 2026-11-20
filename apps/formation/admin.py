from django.contrib import admin

from apps.formation.models import Niveau


@admin.register(Niveau)
class NiveauAdmin(admin.ModelAdmin):
    list_display = ("nom", "section", "ordre", "actif")
    list_filter = ("section", "actif")
    list_editable = ("ordre", "actif")
    search_fields = ("nom",)
