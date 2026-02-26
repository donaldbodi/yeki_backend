from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from .views import *
from . import views

urlpatterns = [
    # --- LANDING PAGE & VERSION ---
    path("landing/", landing, name="landing"),

    path('auth/logout/', LogoutView.as_view(), name='logout'),

    # --- AUTHENTIFICATION ---
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),

    # --- UTILISATEURS ---
    path('enseignants/', liste_enseignants, name='liste-enseignants'), # ne sert pas
    path('enseignants_principaux/', liste_enseignants_principaux, name='liste-enseignants-principaux'),
    path("enseignants_cadres/", liste_enseignants_cadres, name="enseignants-cadres"),
    path('enseignants_secondaires/', liste_enseignants_secondaires, name='liste-enseignants-secondaires'),

    # --- DASHBOARD ---
    path('enseignant/dashboard/', get_dashboard_data, name='enseignant-dashboard-data'),

    # --- STATISTIQUES ---
    path("statistiques-globales/", statistiques_globales, name="statistiques-globales"),
    path('stats/enseignant-admin/<int:pk>/', EnseignantAdminStatsView.as_view(), name="enseignant-admin-stats"),

    # --- PARCOURS ---
    path('parcours/', liste_parcours, name='liste-parcours'),
    path('parcours/<int:parcours_id>/', parcours_unique, name='parcours-unique'),
    path('parcours/list-create/', ParcoursListCreateView.as_view(), name='parcours-list-create'),
    path('parcours/<int:pk>/assign-admin/', AssignAdminView.as_view(), name="assign-admin"),
    path('parcours/<int:parcours_id>/departements/', departements_par_parcours, name="departements-par-parcours"),

    # --- DEPARTEMENTS ---
    path("departements/", DepartementCreateView.as_view(), name="departement-create"),
    path("departements/<int:pk>/", DepartementUpdateView.as_view(), name="departement-update"),
    path("departements/<int:departement_id>/niveaux/", DepartementNiveauxAPIView.as_view()),

    # --- COURS ---
    path('cours/create/', CoursCreateView.as_view(), name='cours-create'),
    path("apprenant/cursus/", ApprenantCursusAPIView.as_view(), name="apprenant-cursus"),
    #path('cours/<int:pk>/', CoursDetailView.as_view(), name='cours-detail'),

    # --- GESTION ENSEIGNANTS SECONDAIRES ---
    path('cours/<int:cours_id>/add-enseignant/', AddEnseignantSecondaireView.as_view(), name='add-enseignant-secondaire'),
    path('cours/<int:cours_id>/remove-enseignant/', RemoveEnseignantSecondaireView.as_view(), name='remove-enseignant-secondaire'),

    # --- LEÇONS ---
    #path('lecons/create/', LeconCreateView.as_view(), name='lecon-create'),
    #path('lecons/<int:pk>/', LeconDetailView.as_view(), name='lecon-detail'),
    path('cours/<int:cours_id>/lecons/', AjouterLeconView.as_view(),name='ajouter-lecon'),

    # --- MODULES --
    path('cours/<int:cours_id>/modules/', ModuleCreateView.as_view(), name='module-create'),
    # urls.py
    path('cours/<int:cours_id>/liste-modules/',ModuleListByCoursView.as_view(),name='cours-modules'),
    path("cours/<int:cours_id>/exercices/", ListeExercicesCoursView.as_view()),
    path("exercices/<int:exercice_id>/evaluer/", SoumettreEvaluationView.as_view()),
    path("evaluations/historique/", HistoriqueEvaluationsView.as_view()),
    path("api/exercices/<int:exercice_id>/", ExerciceDetailView.as_view()),
    path("exercices/<int:exercice_id>/demarrer/", DemarrerExerciceView.as_view()),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

