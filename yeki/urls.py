from django.urls import path
from .views import DepartementCreateView, DepartementUpdateView, RegisterView, LoginView, departements_par_parcours, liste_enseignants_cadres
from . import views

urlpatterns = [
    path("enseignants_cadres/", liste_enseignants_cadres, name="enseignants-cadres"),
    path("parcours/<int:parcours_id>/departements/", departements_par_parcours, name="departements-par-parcours"),
    path("departements/", DepartementCreateView.as_view(), name="departement-create"),
    path("departements/<int:pk>/", DepartementUpdateView.as_view(), name="departement-update"),
    path('parcours/<int:pk>/assign-admin/', views.AssignAdminView.as_view(), name="assign-admin"),
    path('stats/enseignant-admin/<int:pk>/', views.EnseignantAdminStatsView.as_view(), name="enseignant-admin-stats"),
    path("latest-version/", views.latest_version, name="latest_version"),
    path('enseignant/dashboard/', views.get_dashboard_data, name='enseignant-dashboard-data'),
    path('parcours/', views.liste_parcours),
    path('enseignants/', views.liste_enseignants),
    path('statistiques-globales/', views.statistiques_globales),
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),
]
