from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from .views import *
from . import views

urlpatterns = [
    # ── LANDING PAGE ──────────────────────────────────────────────
    path("landing/", landing, name="landing"),

    # ── AUTHENTIFICATION ──────────────────────────────────────────
    path('auth/logout/',          LogoutView.as_view(),        name='logout'),
    path('auth/register/',        RegisterView.as_view(),       name='register'),
    path('auth/login/',           LoginView.as_view(),          name='login'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='change-password'),

    # ── PROFIL ────────────────────────────────────────────────────
    path('profil/me/',     ProfilMeView.as_view(),     name='profil-me'),
    path('profil/update/', ProfilUpdateView.as_view(),  name='profil-update'),
    path('profil/delete/', ProfilDeleteView.as_view(),  name='profil-delete'),
    path('profil/stats/',  ProfilStatsView.as_view(),   name='profil-stats'),

    # ── ENSEIGNANTS (listes) ──────────────────────────────────────
    path('enseignants/',             liste_enseignants,            name='liste-enseignants'),
    path('enseignants_principaux/',  liste_enseignants_principaux, name='liste-enseignants-principaux'),
    path('enseignants_cadres/',      liste_enseignants_cadres,     name='enseignants-cadres'),
    path('enseignants_secondaires/', liste_enseignants_secondaires,name='liste-enseignants-secondaires'),

    # NOUVEAU ► Liste par rôle (utilisée par les pages Flutter admin)
    # GET /api/enseignants/liste/?role=admin|cadre|principal|enseignant
    path('enseignants/liste/', ListeEnseignantsParRoleView.as_view(), name='enseignants-liste-role'),

    # ── DASHBOARD ─────────────────────────────────────────────────
    path('enseignant/dashboard/', get_dashboard_data, name='enseignant-dashboard-data'),

    # NOUVEAU ► Dashboard admin général
    # GET /api/admin-general/dashboard/
    path('admin-general/dashboard/', AdminGeneralDashboardView.as_view(), name='admin-general-dashboard'),

    # NOUVEAU ► Dashboard enseignant administrateur
    # GET /api/enseignant/admin/dashboard/
    path('enseignant/admin/dashboard/', EnseignantAdminDashboardView.as_view(), name='enseignant-admin-dashboard'),

    # Dashboard enseignant cadre
    path('cours/<int:cours_id>/changer-enseignant-principal/', ChangerEnseignantPrincipalView.as_view(), name='changer-ep'),
    path('enseignant/cadre/dashboard/', EnseignantCadreDashboardView.as_view(), name='enseignant-cadre-dashboard'),
    
    # ── STATISTIQUES ──────────────────────────────────────────────
    path('statistiques-globales/',              statistiques_globales,              name='statistiques-globales'),
    path('stats/enseignant-admin/<int:pk>/',    EnseignantAdminStatsView.as_view(), name='enseignant-admin-stats'),

    # ── PARCOURS ──────────────────────────────────────────────────
    path('parcours/',                         liste_parcours,                name='liste-parcours'),
    path('parcours/<int:parcours_id>/',       parcours_unique,               name='parcours-unique'),
    path('parcours/list-create/',             ParcoursListCreateView.as_view(),name='parcours-list-create'),
    path('parcours/<int:pk>/assign-admin/',   AssignAdminView.as_view(),     name='assign-admin'),
    path('parcours/<int:parcours_id>/departements/', departements_par_parcours, name='departements-par-parcours'),

    # NOUVEAU ► Créer un parcours (admin général)
    # POST /api/parcours/creer/
    path('parcours/creer/', CreerParcoursView.as_view(), name='parcours-creer'),

    # NOUVEAU ► Nommer / changer l'enseignant admin d'un parcours
    # PATCH /api/parcours/<id>/nommer-admin/
    path('parcours/<int:parcours_id>/nommer-admin/', NommerAdminParcoursView.as_view(), name='parcours-nommer-admin'),

    # ── DÉPARTEMENTS ──────────────────────────────────────────────
    path('departements/',            DepartementCreateView.as_view(),  name='departement-create'),
    path('departements/<int:pk>/',   DepartementUpdateView.as_view(),  name='departement-update'),
    path('departements/<int:departement_id>/niveaux/', DepartementNiveauxAPIView.as_view()),

    # NOUVEAU ► Créer un département (enseignant admin, sur son parcours)
    # POST /api/departements/creer/
    path('departements/creer/', CreerDepartementView.as_view(), name='departements-creer'),

    # NOUVEAU ► Nommer / changer le cadre d'un département
    # PATCH /api/departements/<id>/changer-cadre/
    path('departements/<int:departement_id>/changer-cadre/', ChangerCadreDepartementView.as_view(), name='departements-changer-cadre'),

    # NOUVEAU ► Cours d'un département
    # GET /api/departements/<id>/cours/
    path('departements/<int:departement_id>/cours/', CoursParDepartementView.as_view(), name='departements-cours'),

    # ── COURS ─────────────────────────────────────────────────────
    path('cours/create/', CoursCreateView.as_view(), name='cours-create'),
    path('apprenant/cursus/', ApprenantCursusAPIView.as_view(), name='apprenant-cursus'),
    path('cours/<int:cours_id>/add-enseignant/',  AddEnseignantSecondaireView.as_view(),    name='add-enseignant-secondaire'),
    path('cours/<int:cours_id>/remove-enseignant/', RemoveEnseignantSecondaireView.as_view(), name='remove-enseignant-secondaire'),

    # ── LEÇONS ────────────────────────────────────────────────────
    path('cours/<int:cours_id>/lecons/', AjouterLeconView.as_view(), name='ajouter-lecon'),

    # ── MODULES ───────────────────────────────────────────────────
    path('cours/<int:cours_id>/modules/',       ModuleCreateView.as_view(),       name='module-create'),
    path('cours/<int:cours_id>/liste-modules/', ModuleListByCoursView.as_view(),  name='cours-modules'),

    # ── EXERCICES ─────────────────────────────────────────────────
    path('cours/<int:cours_id>/exercices/',         ListeExercicesCoursView.as_view()),
    path('exercices/<int:exercice_id>/evaluer/',    SoumettreEvaluationView.as_view()),
    path('evaluations/historique/',                 HistoriqueEvaluationsView.as_view()),
    path('exercices/<int:exercice_id>/',            ExerciceDetailView.as_view()),
    path('exercices/<int:exercice_id>/demarrer/',   DemarrerExerciceView.as_view()),

    # ── DEVOIRS ───────────────────────────────────────────────────
    path('devoirs/',                           ListeDevoirsView.as_view(),     name='liste-devoirs'),
    path('cours/<int:cours_id>/devoirs/',      DevoirsCoursView.as_view()),
    path('devoirs/<int:devoir_id>/',           DetailDevoirView.as_view(),     name='detail-devoir'),
    path('devoirs/<int:devoir_id>/demarrer/',  DemarrerDevoirView.as_view(),   name='demarrer-devoir'),
    path('devoirs/<int:devoir_id>/soumettre/', SoumettreDevoirView.as_view(),  name='soumettre-devoir'),
    path('devoirs/<int:devoir_id>/focus-perdu/', SignalerFocusDevoirView.as_view(), name='focus-devoir'),
    path('devoirs/mes-soumissions/',           MesSoumissionsView.as_view(),   name='mes-soumissions'),
    path('devoirs/<int:devoir_id>/resultat/',  ResultatDevoirView.as_view(),   name='resultat-devoir'),

    # ── OLYMPIADES ────────────────────────────────────────────────
    path('olympiades/',                                        ListeOlympiadesView.as_view(),       name='liste-olympiades'),
    path('olympiades/<int:olympiade_id>/',                     DetailOlympiadeView.as_view(),       name='detail-olympiade'),
    path('olympiades/<int:olympiade_id>/inscrire/',            SInscrireOlympiadeView.as_view(),    name='inscrire-olympiade'),
    path('olympiades/<int:olympiade_id>/demarrer/',            DemarrerOlympiadeView.as_view(),     name='demarrer-olympiade'),
    path('olympiades/<int:olympiade_id>/soumettre/',           SoumettreOlympiadeView.as_view(),    name='soumettre-olympiade'),
    path('olympiades/<int:olympiade_id>/focus-perdu/',         FocusPeduOlympiadeView.as_view(),    name='focus-olympiade'),
    path('olympiades/<int:olympiade_id>/classement/',          ClassementOlympiadeView.as_view(),   name='classement-olympiade'),
    path('olympiades/<int:olympiade_id>/calculer-classement/', CalculerClassementView.as_view(),    name='calculer-classement'),
    path('olympiades/<int:olympiade_id>/mon-inscription/',     MonInscriptionOlympiadeView.as_view(), name='mon-inscription-olympiade'),

    # ── FORUM ─────────────────────────────────────────────────────
    path('forum/messages/',          ForumMessagesListAPIView.as_view(),  name='forum-messages-list'),
    path('forum/messages/create/',   ForumMessageCreateAPIView.as_view(), name='forum-message-create'),
    path('forum/questions/',                   ListeQuestionsView.as_view()),
    path('forum/questions/<int:pk>/',          DetailQuestionView.as_view()),
    path('forum/questions/<int:pk>/resoudre/', ResoudreQuestionView.as_view()),
    path('forum/questions/<int:pk>/repondre/', RepondreQuestionView.as_view()),
    path('forum/reponses/<int:pk>/liker/',     LikerReponseView.as_view()),
    path('forum/reponses/<int:pk>/solution/',  MarquerSolutionView.as_view()),
    path('forum/stats/',                       StatsForumView.as_view()),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
