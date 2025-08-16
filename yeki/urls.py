from django.urls import path
from .views import RegisterView, LoginView
from . import views

urlpatterns = [
    path("latest-version/", views.latest_version, name="latest_version"),
    path('enseignant/dashboard/', views.get_dashboard_data, name='enseignant-dashboard-data'),
    path('parcours/', views.liste_parcours),
    path('enseignants/', views.liste_enseignants),
    path('parcours/<int:parcours_id>/changer-admin/', views.changer_admin),
    path('statistiques-globales/', views.statistiques_globales),
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),
]
