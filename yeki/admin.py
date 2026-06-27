from django.contrib import admin

from .models import *

admin.site.register(Parcours)
admin.site.register(Departement)
admin.site.register(Cours)
admin.site.register(Profile)
admin.site.register(Lecon)
admin.site.register(Module)
admin.site.register(Exercice)
admin.site.register(SessionExercice)
admin.site.register(Question)
admin.site.register(Choix)
admin.site.register(SoumissionDevoir)
admin.site.register(Devoir)
admin.site.register(QuestionDevoir)
admin.site.register(ChoixReponse)
admin.site.register(Olympiade)
admin.site.register(InscriptionOlympiade)
admin.site.register(ReponseOlympiade)
admin.site.register(QuestionForum)
admin.site.register(ReponseQuestion)
admin.site.register(LikeReponse)
admin.site.register(AppVersion)
admin.site.register(CinetPayTransaction)
admin.site.register(WalletTransaction)

@admin.register(AppVersion)
class AppVersionAdmin(admin.ModelAdmin):
    list_display = [
        'version_name', 
        'version_code', 
        'platform', 
        'is_active', 
        'force_update',
        'release_date'
    ]
    list_filter = ['platform', 'is_active', 'force_update']
    search_fields = ['version_name', 'changelog']
    ordering = ['-version_code', '-release_date']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Informations', {
            'fields': ('platform', 'version_code', 'version_name', 'download_url', 'file_size')
        }),
        ('Détails', {
            'fields': ('changelog', 'release_date')
        }),
        ('Paramètres', {
            'fields': ('min_version_code', 'force_update', 'is_active')
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
