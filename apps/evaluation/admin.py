from django.contrib import admin

from apps.evaluation.models import ParametreClassement


@admin.register(ParametreClassement)
class ParametreClassementAdmin(admin.ModelAdmin):
    list_display = ["source", "poids"]
    ordering = ["source"]
