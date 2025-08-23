from django.urls import path
from .views import (
    CoursCreateView,
    DepartementCreateView,
    DepartementUpdateView,
    RegisterView,
    LoginView,
    departements_par_parcours,
    liste_enseignants_cadres,
    ParcoursListCreateView,
    AssignAdminView,
    EnseignantAdminStatsView,
    latest_version,
    get_dashboard_data,
    landing,
    liste_parcours,
    liste_enseignants,
    statistiques_globales,
    AddEnseignantSecondaireView,
    RemoveEnseignantSecondaireView,
    CoursListCreateView,
    CoursDetailView,
    LeconCreateView,
    LeconDetailView,
)
from . import views

urlpatterns = [
    # --- LANDING PAGE & VERSION ---
    path("landing/", landing, name="landing"),
    path("latest-version/", latest_version, name="latest_version"),

    # --- AUTHENTIFICATION ---
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),

    # --- UTILISATEURS ---
    path('enseignants/', liste_enseignants, name='liste-enseignants'),
    path("enseignants_cadres/", liste_enseignants_cadres, name="enseignants-cadres"),

    # --- DASHBOARD ---
    path('enseignant/dashboard/', get_dashboard_data, name='enseignant-dashboard-data'),

    # --- STATISTIQUES ---
    path("statistiques-globales/", statistiques_globales, name="statistiques-globales"),
    path('stats/enseignant-admin/<int:pk>/', EnseignantAdminStatsView.as_view(), name="enseignant-admin-stats"),

    # --- PARCOURS ---
    path('parcours/', liste_parcours, name='liste-parcours'),
    path('parcours/list-create/', ParcoursListCreateView.as_view(), name='parcours-list-create'),
    path('parcours/<int:pk>/assign-admin/', AssignAdminView.as_view(), name="assign-admin"),
    path('parcours/<int:parcours_id>/departements/', departements_par_parcours, name="departements-par-parcours"),

    # --- DEPARTEMENTS ---
    path("departements/", DepartementCreateView.as_view(), name="departement-create"),
    path("departements/<int:pk>/", DepartementUpdateView.as_view(), name="departement-update"),

    # --- COURS ---
    path('cours/create/', CoursCreateView.as_view(), name='cours-create'),
    #path('cours/<int:pk>/', CoursDetailView.as_view(), name='cours-detail'),

    # --- GESTION ENSEIGNANTS SECONDAIRES ---
    path('cours/<int:cours_id>/add-enseignant/', AddEnseignantSecondaireView.as_view(), name='add-enseignant-secondaire'),
    path('cours/<int:cours_id>/remove-enseignant/', RemoveEnseignantSecondaireView.as_view(), name='remove-enseignant-secondaire'),

    # --- LEÇONS ---
    #path('lecons/create/', LeconCreateView.as_view(), name='lecon-create'),
    #path('lecons/<int:pk>/', LeconDetailView.as_view(), name='lecon-detail'),
]
