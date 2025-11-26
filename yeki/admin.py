from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import *

admin.site.register(Parcours)
admin.site.register(Departement)
admin.site.register(Cours)
admin.site.register(Lecon)
admin.site.register(Profile)
