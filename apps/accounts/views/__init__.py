from apps.accounts.views.auth import (  # noqa: F401
    RegisterView,
    LoginView,
    ForgotPasswordView,
    VerifyOTPView,
    ResetPasswordView,
    ChangePasswordView,
    LogoutView,
)
from apps.accounts.views.profil import (  # noqa: F401
    ProfilMeView,
    ProfilUpdateView,
    ProfilDeleteView,
    ProfilStatsView,
)
from apps.accounts.views.admin_enseignants import (  # noqa: F401
    AdminGeneralEnseignantsListView,
    AdminGeneralDesactiverEnseignantView,
    AdminGeneralEnseignantsAttenteView,
    AdminGeneralActiverEnseignantView,
    AdminGeneralChangerTypeEnseignantView,
    liste_enseignants_cadres,
    liste_enseignants_secondaires,
    liste_enseignants,
    AdminGeneralModifierEnseignantView,
    AdminGeneralSearchEnseignantsView,
    ListeEnseignantsParRoleView,
    liste_enseignants_principaux,
)
from apps.accounts.views.dashboards import (  # noqa: F401
    AdminGeneralDashboardView,
    EnseignantAdminDashboardView,
    get_dashboard_data,
)
