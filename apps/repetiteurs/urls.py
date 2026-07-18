from django.urls import path

from apps.repetiteurs.views import RepetiteursSearchView

urlpatterns = [
    path("repetiteurs/search/", RepetiteursSearchView.as_view(), name="repetiteurs-search"),
]
