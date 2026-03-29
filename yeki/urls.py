from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from .views import *
from . import views

# Import des nouvelles vues

urlpatterns = [
    # ── LANDING PAGE ──────────────────────────────────────────────
    path("landing/", landing, name="landing"),

    # ── AUTHENTIFICATION ──────────────────────────────────────────
    path('auth/logout/',          LogoutView.as_view(),        name='logout'),
    path('auth/register/',        RegisterView.as_view(),       name='register'),
    path('auth/login/',           LoginView.as_view(),          name='login'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('auth/forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('auth/verify-otp/',      VerifyOTPView.as_view(),      name='verify-otp'),
    path('auth/reset-password/',  ResetPasswordView.as_view(),  name='reset-password'),

    # ── PROFIL ────────────────────────────────────────────────────
    path('profil/me/',     ProfilMeView.as_view(),     name='profil-me'),
    path('profil/update/', ProfilUpdateView.as_view(),  name='profil-update'),
    path('profil/delete/', ProfilDeleteView.as_view(),  name='profil-delete'),
    path('profil/stats/',  ProfilStatsView.as_view(),   name='profil-stats'),

    # ── ENSEIGNANTS ───────────────────────────────────────────────
    path('enseignants/',             liste_enseignants,            name='liste-enseignants'),
    path('enseignants_principaux/',  liste_enseignants_principaux, name='liste-enseignants-principaux'),
    path('enseignants_cadres/',      liste_enseignants_cadres,     name='enseignants-cadres'),
    path('enseignants_secondaires/', liste_enseignants_secondaires,name='liste-enseignants-secondaires'),
    path('enseignants/liste/', ListeEnseignantsParRoleView.as_view(), name='enseignants-liste-role'),

    # ── DASHBOARD ─────────────────────────────────────────────────
    path('enseignant/dashboard/', get_dashboard_data, name='enseignant-dashboard-data'),
    path('admin-general/dashboard/', AdminGeneralDashboardView.as_view(), name='admin-general-dashboard'),
    path('enseignant/admin/dashboard/', EnseignantAdminDashboardView.as_view(), name='enseignant-admin-dashboard'),
    path('cours/<int:cours_id>/changer-enseignant-principal/', ChangerEnseignantPrincipalView.as_view(), name='changer-ep'),
    path('enseignant/cadre/dashboard/', EnseignantCadreDashboardView.as_view(), name='enseignant-cadre-dashboard'),

    # ── STATISTIQUES ──────────────────────────────────────────────
    path('statistiques-globales/', statistiques_globales, name='statistiques-globales'),
    path('stats/enseignant-admin/<int:pk>/', EnseignantAdminStatsView.as_view(), name='enseignant-admin-stats'),

    # ── PARCOURS ──────────────────────────────────────────────────
    path('parcours/', liste_parcours, name='liste-parcours'),
    path('parcours/<int:parcours_id>/', parcours_unique, name='parcours-unique'),
    path('parcours/list-create/', ParcoursListCreateView.as_view(), name='parcours-list-create'),
    path('parcours/<int:pk>/assign-admin/', AssignAdminView.as_view(), name='assign-admin'),
    path('parcours/<int:parcours_id>/departements/', departements_par_parcours, name='departements-par-parcours'),
    path('parcours/creer/', CreerParcoursView.as_view(), name='parcours-creer'),
    path('parcours/<int:parcours_id>/nommer-admin/', NommerAdminParcoursView.as_view(), name='parcours-nommer-admin'),

    # ── DÉPARTEMENTS ──────────────────────────────────────────────
    path('departements/', DepartementCreateView.as_view(), name='departement-create'),
    path('departements/<int:pk>/', DepartementUpdateView.as_view(), name='departement-update'),
    path('departements/<int:departement_id>/niveaux/', DepartementNiveauxAPIView.as_view()),
    path('departements/creer/', CreerDepartementView.as_view(), name='departements-creer'),
    path('departements/<int:departement_id>/changer-cadre/', ChangerCadreDepartementView.as_view(), name='departements-changer-cadre'),
    path('departements/<int:departement_id>/cours/', CoursParDepartementView.as_view(), name='departements-cours'),

    # ── COURS ─────────────────────────────────────────────────────
    path('cours/create/', CoursCreateView.as_view(), name='cours-create'),
    path('apprenant/cursus/', ApprenantCursusAPIView.as_view(), name='apprenant-cursus'),
    path('cours/<int:cours_id>/add-enseignant/', AddEnseignantSecondaireView.as_view(), name='add-enseignant-secondaire'),
    path('cours/<int:cours_id>/remove-enseignant/', RemoveEnseignantSecondaireView.as_view(), name='remove-enseignant-secondaire'),
    path('cours/<int:cours_id>/update/', ModifierCoursParCadreView.as_view(), name='cours-modifier-cadre'),

    # ── LEÇONS ────────────────────────────────────────────────────
    path('cours/<int:cours_id>/lecons/', AjouterLeconView.as_view(), name='ajouter-lecon'),
    path('apprenant/lectures-recentes/', LecturesRecentesView.as_view(), name='lectures-recentes'),
    path('apprenant/marquer-lecon/', MarquerLeconVueView.as_view(), name='marquer-lecon'),
    path('lecons/<int:lecon_id>/modifier/', views.LeconUpdateView.as_view(), name='lecon-modifier'),
    path('lecons/<int:lecon_id>/supprimer/', views.LeconDeleteView.as_view(), name='lecon-supprimer'),

    # ── MODULES ───────────────────────────────────────────────────
    path('cours/<int:cours_id>/modules/', ModuleCreateView.as_view(), name='module-create'),
    path('cours/<int:cours_id>/liste-modules/', ModuleListByCoursView.as_view(), name='cours-modules'),
    path('modules/<int:module_id>/modifier/', views.ModuleUpdateView.as_view(), name='module-modifier'),
    path('modules/<int:module_id>/supprimer/', views.ModuleDeleteView.as_view(), name='module-supprimer'),

    # ── EXERCICES ─────────────────────────────────────────────────
    path('cours/<int:cours_id>/exercices/', ListeExercicesCoursView.as_view()),
    path('exercices/<int:exercice_id>/evaluer/', SoumettreEvaluationView.as_view()),
    path('evaluations/historique/', HistoriqueEvaluationsView.as_view()),
    path('exercices/<int:exercice_id>/', ExerciceDetailView.as_view()),
    path('exercices/<int:exercice_id>/demarrer/', DemarrerExerciceView.as_view()),
    path('cours/<int:cours_id>/exercices/ajouter/', views.AjouterExerciceView.as_view(), name='exercice-ajouter'),
    path('exercices/<int:exercice_id>/questions/', views.ListeQuestionsExerciceView.as_view(), name='question-liste'),
    path('exercices/<int:exercice_id>/questions/ajouter/', views.AjouterQuestionView.as_view(), name='question-ajouter'),

    # ── DEVOIRS ───────────────────────────────────────────────────
    path('devoirs/', ListeDevoirsView.as_view(), name='liste-devoirs'),
    path('cours/<int:cours_id>/devoirs/', DevoirsCoursView.as_view()),
    path('devoirs/<int:devoir_id>/', DetailDevoirView.as_view(), name='detail-devoir'),
    path('devoirs/<int:devoir_id>/demarrer/', DemarrerDevoirView.as_view(), name='demarrer-devoir'),
    path('devoirs/<int:devoir_id>/soumettre/', SoumettreDevoirView.as_view(), name='soumettre-devoir'),
    path('devoirs/<int:devoir_id>/focus-perdu/', SignalerFocusDevoirView.as_view(), name='focus-devoir'),
    path('devoirs/mes-soumissions/', MesSoumissionsView.as_view(), name='mes-soumissions'),
    path('devoirs/<int:devoir_id>/resultat/', ResultatDevoirView.as_view(), name='resultat-devoir'),
    path('cours/<int:cours_id>/devoirs/creer/', CreerDevoirCoursView.as_view(), name='devoir-creer'),
    path('devoirs/<int:devoir_id>/modifier/', ModifierDevoirView.as_view(), name='devoir-modifier'),
    path('devoirs/<int:devoir_id>/questions/', ListeQuestionsDevoirView.as_view(), name='devoir-questions-liste'),
    path('devoirs/<int:devoir_id>/questions/ajouter/', AjouterQuestionDevoirView.as_view(), name='devoir-question-ajouter'),
    path('devoirs/<int:devoir_id>/soumissions/', SoumissionsDevoirEnseignantView.as_view(), name='devoir-soumissions'),
    path('soumissions/<int:soumission_id>/detail/', DetailSoumissionEnseignantView.as_view(), name='soumission-detail'),
    path('soumissions/<int:soumission_id>/corriger/', CorrigerSoumissionView.as_view(), name='soumission-corriger'),
    path('devoirs/<int:devoir_id>/soumettre-fichier/', SoumettreDevoirFichierView.as_view(), name='devoir-soumettre-fichier'),
    path('devoirs/<int:devoir_id>/stats/', StatsDevoirEnseignantView.as_view(), name='devoir-stats'),

    # ── OLYMPIADES ────────────────────────────────────────────────
    path('olympiades/cadre/creer/', CreerOlympiadeParCadreView.as_view(), name='olympiade-creer-cadre'),
    path('olympiades/', ListeOlympiadesView.as_view(), name='liste-olympiades'),
    path('olympiades/<int:olympiade_id>/', DetailOlympiadeView.as_view(), name='detail-olympiade'),
    path('olympiades/<int:olympiade_id>/inscrire/', SInscrireOlympiadeView.as_view(), name='inscrire-olympiade'),
    path('olympiades/<int:olympiade_id>/demarrer/', DemarrerOlympiadeView.as_view(), name='demarrer-olympiade'),
    path('olympiades/<int:olympiade_id>/soumettre/', SoumettreOlympiadeView.as_view(), name='soumettre-olympiade'),
    path('olympiades/<int:olympiade_id>/focus-perdu/', FocusPeduOlympiadeView.as_view(), name='focus-olympiade'),
    path('olympiades/<int:olympiade_id>/classement/', ClassementOlympiadeView.as_view(), name='classement-olympiade'),
    path('olympiades/<int:olympiade_id>/calculer-classement/', CalculerClassementView.as_view(), name='calculer-classement'),
    path('olympiades/<int:olympiade_id>/mon-inscription/', MonInscriptionOlympiadeView.as_view(), name='mon-inscription-olympiade'),

    # ── FORUM ─────────────────────────────────────────────────────
    path('forum/messages/', ForumMessagesListAPIView.as_view(), name='forum-messages-list'),
    path('forum/messages/create/', ForumMessageCreateAPIView.as_view(), name='forum-message-create'),
    path('forum/questions/', ListeQuestionsView.as_view()),
    path('forum/questions/<int:pk>/', DetailQuestionView.as_view()),
    path('forum/questions/<int:pk>/resoudre/', ResoudreQuestionView.as_view()),
    path('forum/questions/<int:pk>/repondre/', RepondreQuestionView.as_view()),
    path('forum/reponses/<int:pk>/liker/', LikerReponseView.as_view()),
    path('forum/reponses/<int:pk>/solution/', MarquerSolutionView.as_view()),
    path('forum/stats/', StatsForumView.as_view()),
    # NOUVEAU : Yeki IA dans le forum
    path('forum/questions/<int:pk>/ia-repondre/', YekiIARepondreForumView.as_view(), name='forum-ia-repondre'),
    #path('forum/questions/<int:pk>/ia-discussion/', YekiIADiscussionView.as_view(), name='forum-ia-discussion'),

    # ── YEKI IA ───────────────────────────────────────────────────
    #path('ia/generer-exercices/', YekiIAGenererExercicesView.as_view(), name='ia-exercices'),
    #path('ia/corriger/', YekiIACorrigerTexteView.as_view(), name='ia-corriger'),
    #path('ia/creer-formation/', YekiIACreerFormationView.as_view(), name='ia-creer-formation'),


    # ── PAIEMENT ──────────────────────────────────────────────────
    # POST /api/paiements/initier/
    path('paiements/initier/', InitierPaiementView.as_view(), name='paiement-initier'),
    # GET /api/paiements/<reference>/verifier/
    path('paiements/<str:reference>/verifier/', VerifierPaiementView.as_view(), name='paiement-verifier'),
    # GET /api/paiements/historique/
    path('paiements/historique/', HistoriquePaiementsView.as_view(), name='paiements-historique'),
    # GET /api/abonnement/statut/
    path('abonnement/statut/', StatutAbonnementView.as_view(), name='abonnement-statut'),

    # ── HISTORIQUE ────────────────────────────────────────────────
    path('historique/', HistoriqueActiviteView.as_view(), name='historique'),
    path('historique/stats/', HistoriqueStatsView.as_view(), name='historique-stats'),


    # ── APPRENANT : Prépa Concours ────────────────────────────────
    # Retourne les départements (= concours) du parcours "Prépa Concours"
    # filtrés par profile.sub_cursus, groupés par département.
    # Exemple : concours ENS, concours Polytechnique, etc.
    path(
        'apprenant/prepa-concours/',
        ApprenantPrepaConcoursAPIView.as_view(),
        name='apprenant-prepa-concours',
    ),

    # ── APPRENANT : Formations ────────────────────────────────────
    # Retourne les départements (= formations classiques/métier) du
    # parcours "Formations" filtrés par profile.sub_cursus.
    # Paramètre optionnel : ?parcours=NomDuParcours
    path(
        'apprenant/formations/',
        ApprenantFormationsAPIView.as_view(),
        name='apprenant-formations',
    ),

    # ── APPRENANT : Détail d'un département ──────────────────────
    path(
        'apprenant/departement/<int:pk>/',
        ApprenantDepartementDetailView.as_view(),
        name='apprenant-departement-detail',
    ),

    # ── OLYMPIADES : filtrées pour l'apprenant ───────────────────
    # Remplace ListeOlympiadesView pour les apprenants.
    # Filtre par profile.sub_cursus et ne retourne que les olympiades
    # validées (Devoir.est_publie=True).
    # Paramètres : ?statut=inscription|en_cours|terminee  ?matiere=  ?niveau=
    path(
        'olympiades/pour-moi/',
        OlympiadesPourMoiView.as_view(),
        name='olympiades-pour-moi',
    ),

    # ── ADMIN : Validation olympiades ────────────────────────────
    # Liste des olympiades en attente de validation (prix vides = gratuit)
    path(
        'admin/olympiades/a-valider/',
        AdminOlympiadesAValiderView.as_view(),
        name='admin-olympiades-a-valider',
    ),
    # Valider ou refuser une olympiade spécifique
    # Body: {} → valider  |  {"refuser": true, "motif": "..."} → refuser
    path(
        'admin/olympiades/<int:pk>/valider/',
        AdminValiderOlympiadeView.as_view(),
        name='admin-valider-olympiade',
    ),

    # ── ADMIN : Validation départements ──────────────────────────
    # Liste des départements sans cadre ou avec devoirs en attente
    path(
        'admin/departements/a-valider/',
        AdminDepartementsAValiderView.as_view(),
        name='admin-departements-a-valider',
    ),
    # Valider un département : assigner cadre, publier devoirs, désactiver
    # Body: {"cadre_id": 12} | {"publier_devoirs": true} | {"desactiver": true}
    path(
        'admin/departements/<int:pk>/valider/',
        AdminValiderDepartementView.as_view(),
        name='admin-valider-departement',
    ),

    # ── YEKI IA ──────────────────────────────────────────────────
    # Répondre automatiquement à une question du forum
    path(
        'ia/forum/<int:question_id>/repondre/',
        YekiIARepondreForumView.as_view(),
        name='ia-forum-repondre',
    ),
    # Chat direct avec Yeki IA dans le contexte d'un cours
    path(
        'ia/cours/<int:cours_id>/chat/',
        YekiIAChatView.as_view(),
        name='ia-cours-chat',
    ),


    # ── YEKI IA — CHAT PRIVÉ AVEC HISTORIQUE ─────────────────────
    path(
        'ia/cours/<int:cours_id>/historique/',
        YekiIAChatHistoriqueView.as_view(),
        name='ia-chat-historique',
    ),
    path(
        'ia/cours/<int:cours_id>/chat/',
        YekiIAChatAvecHistoriqueView.as_view(),
        name='ia-chat',
    ),


    # ── WALLET — PORTEFEUILLE YEKI ────────────────────────────────
    path('wallet/solde/',        WalletSoldeView.as_view(),     name='wallet-solde'),
    path('wallet/recharger/',    WalletRechargerView.as_view(), name='wallet-recharger'),
    path('wallet/payer/',        WalletPayerView.as_view(),     name='wallet-payer'),
    path('wallet/verifier-iap/', WalletVerifierIAPView.as_view(), name='wallet-verifier-iap'),

    # ── ADMIN : Dashboard enrichi ─────────────────────────────────
    # Extension du dashboard existant avec olympiades + formations
    path(
        'enseignant/admin/dashboard/enrichi/',
        EnseignantAdminDashboardEnrichiView.as_view(),
        name='admin-dashboard-enrichi',
    ),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
