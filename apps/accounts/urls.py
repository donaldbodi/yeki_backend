from django.urls import path

from apps.accounts.views import (
    LogoutView,
    RegisterView,
    LoginView,
    ChangePasswordView,
    ForgotPasswordView,
    VerifyOTPView,
    ResetPasswordView,
    ProfilMeView,
    ProfilUpdateView,
    ProfilDeleteView,
    ProfilStatsView,
    liste_enseignants,
    liste_enseignants_principaux,
    liste_enseignants_cadres,
    liste_enseignants_secondaires,
    ListeEnseignantsParRoleView,
    get_dashboard_data,
    AdminGeneralDashboardView,
    EnseignantAdminDashboardView,
    AdminGeneralSearchEnseignantsView,
    AdminGeneralModifierEnseignantView,
    AdminGeneralEnseignantsAttenteView,
    AdminGeneralActiverEnseignantView,
    AdminGeneralChangerTypeEnseignantView,
)

urlpatterns = [
    # ── AUTHENTIFICATION ──────────────────────────────────────────
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("auth/forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("auth/verify-otp/", VerifyOTPView.as_view(), name="verify-otp"),
    path("auth/reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    # ── PROFIL ────────────────────────────────────────────────────
    path("profil/me/", ProfilMeView.as_view(), name="profil-me"),
    path("profil/update/", ProfilUpdateView.as_view(), name="profil-update"),
    path("profil/delete/", ProfilDeleteView.as_view(), name="profil-delete"),
    path("profil/stats/", ProfilStatsView.as_view(), name="profil-stats"),
    # ── ENSEIGNANTS ───────────────────────────────────────────────
    path("enseignants/", liste_enseignants, name="liste-enseignants"),
    path(
        "enseignants_principaux/", liste_enseignants_principaux, name="liste-enseignants-principaux"
    ),
    path("enseignants_cadres/", liste_enseignants_cadres, name="enseignants-cadres"),
    path(
        "enseignants_secondaires/",
        liste_enseignants_secondaires,
        name="liste-enseignants-secondaires",
    ),
    path(
        "enseignants/liste/", ListeEnseignantsParRoleView.as_view(), name="enseignants-liste-role"
    ),
    # ── DASHBOARD ─────────────────────────────────────────────────
    path("enseignant/dashboard/", get_dashboard_data, name="enseignant-dashboard-data"),
    path(
        "admin-general/dashboard/",
        AdminGeneralDashboardView.as_view(),
        name="admin-general-dashboard",
    ),
    path(
        "enseignant/admin/dashboard/",
        EnseignantAdminDashboardView.as_view(),
        name="enseignant-admin-dashboard",
    ),
    # ── ADMIN GÉNÉRAL — Gestion des enseignants ──────────────────
    path(
        "admin-general/enseignants/search/",
        AdminGeneralSearchEnseignantsView.as_view(),
        name="admin-general-enseignants-search",
    ),
    path(
        "admin-general/enseignants/<int:profile_id>/modifier/",
        AdminGeneralModifierEnseignantView.as_view(),
        name="admin-general-modifier-enseignant",
    ),
    path(
        "admin-general/enseignants/attente/",
        AdminGeneralEnseignantsAttenteView.as_view(),
        name="admin-general-enseignants-attente",
    ),
    path(
        "admin-general/enseignants/<int:profile_id>/activer/",
        AdminGeneralActiverEnseignantView.as_view(),
        name="admin-general-activer-enseignant",
    ),
    path(
        "admin-general/enseignants/<int:profile_id>/changer-type/",
        AdminGeneralChangerTypeEnseignantView.as_view(),
        name="admin-general-changer-type-enseignant",
    ),
]
