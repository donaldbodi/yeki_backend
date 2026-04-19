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

