from django.contrib import admin

from apps.repetiteurs.models import Repetiteur


@admin.register(Repetiteur)
class RepetiteurAdmin(admin.ModelAdmin):
    list_display = ["enseignant", "cours", "ville", "tarif_mensuel", "disponible", "note_moyenne"]
    list_filter = ["disponible", "ville"]
    search_fields = ["enseignant__user__username", "cours__titre", "ville"]
    ordering = ["-disponible", "ville"]
