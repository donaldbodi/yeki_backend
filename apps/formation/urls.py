from django.urls import path

from apps.formation.views import (
    ChangerEnseignantPrincipalView,
    EnseignantCadreDashboardView,
    statistiques_globales,
    EnseignantAdminStatsView,
    liste_parcours,
    parcours_unique,
    ParcoursListCreateView,
    AssignAdminView,
    departements_par_parcours,
    CreerParcoursView,
    NommerAdminParcoursView,
    CreerDepartementView,
    DepartementUpdateView,
    DepartementNiveauxAPIView,
    ChangerCadreDepartementView,
    CoursParDepartementView,
    CoursCreateView,
    ApprenantCursusAPIView,
    AddEnseignantSecondaireView,
    RemoveEnseignantSecondaireView,
    ModifierCoursParCadreView,
    AjouterLeconView,
    LecturesRecentesView,
    MarquerLeconVueView,
    LeconUpdateView,
    LeconDeleteView,
    LeconLikeView,
    ModuleCreateView,
    ModuleListByCoursView,
    ModuleUpdateView,
    ModuleDeleteView,
    ListeNiveauxView,
    PaletteCouleursCoursView,
    ApprenantConcoursFormationsView,
    ApprenantDepartementDetailView,
    ApprenantsParDepartementView,
    EnseignantCadreDepartementDetailView,
    EnseignantCadreDepartementUpdateView,
    DemandeAccesFormationView,
    DemandesAccesDepartementView,
    GererDemandeAccesView,
    VerifierAccesDepartementView,
    AdminUpdateDepartementView,
    AdminGeneralModifierParcoursView,
    PrincipalDashboardAPIView,
    PrincipalApprenantsCoursAPIView,
    PrincipalRendusDevoirsAPIView,
    enseignant_principal_cours,
)

urlpatterns = [
    # ── DASHBOARD ─────────────────────────────────────────────────
    path(
        "cours/<int:cours_id>/changer-enseignant-principal/",
        ChangerEnseignantPrincipalView.as_view(),
        name="changer-ep",
    ),
    path(
        "enseignant/cadre/dashboard/",
        EnseignantCadreDashboardView.as_view(),
        name="enseignant-cadre-dashboard",
    ),
    # ── STATISTIQUES ──────────────────────────────────────────────
    path("statistiques-globales/", statistiques_globales, name="statistiques-globales"),
    path(
        "stats/enseignant-admin/<int:pk>/",
        EnseignantAdminStatsView.as_view(),
        name="enseignant-admin-stats",
    ),
    # ── PARCOURS ──────────────────────────────────────────────────
    path("parcours/", liste_parcours, name="liste-parcours"),
    path("parcours/<int:parcours_id>/", parcours_unique, name="parcours-unique"),
    path("parcours/list-create/", ParcoursListCreateView.as_view(), name="parcours-list-create"),
    path("parcours/<int:pk>/assign-admin/", AssignAdminView.as_view(), name="assign-admin"),
    path(
        "parcours/<int:parcours_id>/departements/",
        departements_par_parcours,
        name="departements-par-parcours",
    ),
    path("parcours/creer/", CreerParcoursView.as_view(), name="parcours-creer"),
    path(
        "parcours/<int:parcours_id>/nommer-admin/",
        NommerAdminParcoursView.as_view(),
        name="parcours-nommer-admin",
    ),
    path(
        "parcours/<int:parcours_id>/modifier/",
        AdminGeneralModifierParcoursView.as_view(),
        name="parcours-modifier-admin",
    ),
    # ── DÉPARTEMENTS ──────────────────────────────────────────────
    path("departements/", CreerDepartementView.as_view(), name="departement-create"),
    path("departements/<int:pk>/", DepartementUpdateView.as_view(), name="departement-update"),
    path("departements/<int:departement_id>/niveaux/", DepartementNiveauxAPIView.as_view()),
    path("departements/creer/", CreerDepartementView.as_view(), name="departements-creer"),
    path(
        "departements/<int:departement_id>/changer-cadre/",
        ChangerCadreDepartementView.as_view(),
        name="departements-changer-cadre",
    ),
    path(
        "departements/<int:departement_id>/cours/",
        CoursParDepartementView.as_view(),
        name="departements-cours",
    ),
    # ── COURS ─────────────────────────────────────────────────────
    path("cours/create/", CoursCreateView.as_view(), name="cours-create"),
    path("apprenant/cursus/", ApprenantCursusAPIView.as_view(), name="apprenant-cursus"),
    path(
        "cours/<int:cours_id>/add-enseignant/",
        AddEnseignantSecondaireView.as_view(),
        name="add-enseignant-secondaire",
    ),
    path(
        "cours/<int:cours_id>/remove-enseignant/",
        RemoveEnseignantSecondaireView.as_view(),
        name="remove-enseignant-secondaire",
    ),
    path(
        "cours/<int:cours_id>/update/",
        ModifierCoursParCadreView.as_view(),
        name="cours-modifier-cadre",
    ),
    # ── LEÇONS ────────────────────────────────────────────────────
    path("cours/<int:cours_id>/lecons/", AjouterLeconView.as_view(), name="ajouter-lecon"),
    path("apprenant/lectures-recentes/", LecturesRecentesView.as_view(), name="lectures-recentes"),
    path("apprenant/marquer-lecon/", MarquerLeconVueView.as_view(), name="marquer-lecon"),
    path("lecons/<int:lecon_id>/modifier/", LeconUpdateView.as_view(), name="lecon-modifier"),
    path("lecons/<int:lecon_id>/supprimer/", LeconDeleteView.as_view(), name="lecon-supprimer"),
    path("apprenant/lecon/<int:lecon_id>/like/", LeconLikeView.as_view(), name="lecon-like"),
    # ── MODULES ───────────────────────────────────────────────────
    path("cours/<int:cours_id>/modules/", ModuleCreateView.as_view(), name="module-create"),
    path(
        "cours/<int:cours_id>/liste-modules/", ModuleListByCoursView.as_view(), name="cours-modules"
    ),
    path("modules/<int:module_id>/modifier/", ModuleUpdateView.as_view(), name="module-modifier"),
    path("modules/<int:module_id>/supprimer/", ModuleDeleteView.as_view(), name="module-supprimer"),
    path("niveaux/", ListeNiveauxView.as_view(), name="liste-niveaux"),
    path(
        "cours/palette-couleurs/", PaletteCouleursCoursView.as_view(), name="palette-couleurs-cours"
    ),
    # ── APPRENANT : Prépa Concours / Formations ──────────────────
    path(
        "apprenant/prepa-concours/",
        ApprenantConcoursFormationsView.as_view(),
        name="apprenant-prepa-concours",
    ),
    path(
        "apprenant/formations/",
        ApprenantConcoursFormationsView.as_view(),
        name="apprenant-formations",
    ),
    path(
        "apprenant/departement/<int:pk>/",
        ApprenantDepartementDetailView.as_view(),
        name="apprenant-departement-detail",
    ),
    path(
        "apprenant/departement/<int:pk>/acces/",
        VerifierAccesDepartementView.as_view(),
        name="verifier-acces",
    ),
    # ── Cadre - Apprenants / départements ────────────────────────
    path(
        "departements/<int:departement_id>/apprenants/",
        ApprenantsParDepartementView.as_view(),
        name="departement-apprenants",
    ),
    path(
        "enseignant/cadre/departement/<int:departement_id>/",
        EnseignantCadreDepartementDetailView.as_view(),
        name="enseignant-cadre-departement",
    ),
    path(
        "enseignant/cadre/departement/<int:departement_id>/update/",
        EnseignantCadreDepartementUpdateView.as_view(),
        name="enseignant-cadre-departement-update",
    ),
    path(
        "departements/<int:departement_id>/demander-acces/",
        DemandeAccesFormationView.as_view(),
        name="demander-acces",
    ),
    path(
        "departements/<int:departement_id>/demandes/",
        DemandesAccesDepartementView.as_view(),
        name="demandes-acces",
    ),
    path(
        "departements/<int:departement_id>/demandes/<int:demande_id>/traiter/",
        GererDemandeAccesView.as_view(),
        name="gerer-demande",
    ),
    # ── Admin - Mise à jour département ──────────────────────────
    path(
        "admin/departements/<int:pk>/update/",
        AdminUpdateDepartementView.as_view(),
        name="admin-departement-update",
    ),
    # ── PRINCIPAL dashboard/apprenants/rendus ────────────────────
    path(
        "principal/dashboard_stats/",
        PrincipalDashboardAPIView.as_view(),
        name="principal-dashboard-stats",
    ),
    path(
        "principal/apprenants_cours/",
        PrincipalApprenantsCoursAPIView.as_view(),
        name="principal-apprenants-cours",
    ),
    path(
        "principal/rendus_devoirs/",
        PrincipalRendusDevoirsAPIView.as_view(),
        name="principal-rendus-devoirs",
    ),
    path(
        "enseignant_principal/cours/", enseignant_principal_cours, name="enseignant_principal_cours"
    ),
]
