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

