from django.contrib import admin

from .models import *

admin.site.register(CustomUser)
admin.site.register(Parcours)
admin.site.register(AppVersion)
admin.site.register(Departement)
admin.site.register(Cours)
admin.site.register(Lecon)

