# yeki/permissions.py
# ═══════════════════════════════════════════════════════════════════════════
# Permissions DRF réutilisables — YÉKI backend.
#
# `IsAuthenticated` (désormais le défaut, voir settings.py) garantit qu'un
# utilisateur est connecté, mais PAS qu'il est le propriétaire de la
# ressource demandée, ni qu'il a le bon rôle. Ces classes couvrent les deux
# axes manquants :
#   - rôle   (IsApprenant, IsEnseignant, IsAdminGeneral, ...)
#   - portée (IsOwner, IsCadreDuDepartement, IsPrincipalDuCours,
#             IsEnseignantAdminDuParcours) via `has_object_permission`.
#
# Toujours composer avec IsAuthenticated (déjà le défaut global) :
#     permission_classes = [IsApprenant]                 # rôle seul
#     permission_classes = [IsAuthenticated, IsOwner]     # portée seule
#     permission_classes = [IsEnseignant, IsPrincipalDuCours]  # les deux
#
# `has_object_permission` n'est appelé par DRF QUE si la vue appelle
# explicitement `self.check_object_permissions(request, obj)` (ce que font
# `get_object()` des generics DRF, mais PAS un `Model.objects.get(pk=...)`
# manuel dans une APIView — voir docs/AUDIT_PERMISSIONS.md pour les vues où
# ce filtre doit être ajouté à la main).
# ═══════════════════════════════════════════════════════════════════════════

from rest_framework.permissions import BasePermission, SAFE_METHODS


def _profile(request):
    """Profil de l'utilisateur authentifié, ou None (jamais d'exception ici :
    une permission doit répondre False proprement, pas planter la vue)."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return None
    return getattr(user, 'profile', None)


class _HasUserType(BasePermission):
    """Base commune : vrai si le profil de l'utilisateur a l'un des
    `user_types` autorisés (voir Profile.USER_TYPES dans models.py)."""
    user_types: tuple[str, ...] = ()

    def has_permission(self, request, view):
        profile = _profile(request)
        return bool(profile and profile.user_type in self.user_types)


class IsApprenant(_HasUserType):
    user_types = ('apprenant',)


class IsEnseignant(_HasUserType):
    """Vrai pour tout profil enseignant, quel que soit son niveau
    hiérarchique (enseignant, cadre, principal, admin). Pour restreindre à
    un niveau précis, combiner avec IsCadreDuDepartement /
    IsPrincipalDuCours / IsEnseignantAdminDuParcours selon le cas."""
    user_types = ('enseignant', 'enseignant_cadre', 'enseignant_principal', 'enseignant_admin')


class IsAdminGeneral(_HasUserType):
    user_types = ('admin',)


class IsOwner(BasePermission):
    """Permission d'objet générique : vrai si l'objet appartient à
    `request.user`, quel que soit le nom du champ propriétaire dans ce
    modèle (le projet n'a pas de convention unique : `utilisateur` sur
    SoumissionDevoir/YekiWallet, `apprenant` sur ProgressionLecon/
    DemandeAccesFormation, `user` sur Profile). On essaie les noms connus
    dans l'ordre ; à défaut, on refuse (fail-closed) plutôt que de supposer.
    """
    owner_fields = ('utilisateur', 'apprenant', 'user')

    def has_object_permission(self, request, view, obj):
        user = request.user
        for field in self.owner_fields:
            if hasattr(obj, field):
                owner = getattr(obj, field)
                return owner is not None and owner == user
        return False


class IsCadreDuDepartement(BasePermission):
    """Vrai si l'utilisateur est le `cadre` (Profile, user_type=
    'enseignant_cadre') du Departement concerné. Accepte en objet soit un
    Departement directement, soit tout objet ayant un attribut
    `.departement` (Cours, DemandeAccesFormation, ...)."""

    def has_object_permission(self, request, view, obj):
        departement = obj if type(obj).__name__ == 'Departement' else getattr(obj, 'departement', None)
        if departement is None or departement.cadre_id is None:
            return False
        return departement.cadre.user_id == request.user.id


class IsPrincipalDuCours(BasePermission):
    """Vrai si l'utilisateur est l'`enseignant_principal` (Profile) du Cours
    concerné. Accepte en objet soit un Cours directement, soit tout objet
    ayant un attribut `.cours` (Devoir, SoumissionDevoir via devoir.cours,
    ...)."""

    def has_object_permission(self, request, view, obj):
        cours = obj if type(obj).__name__ == 'Cours' else getattr(obj, 'cours', None)
        if cours is None or cours.enseignant_principal_id is None:
            return False
        return cours.enseignant_principal.user_id == request.user.id


class IsEnseignantAdminDuParcours(BasePermission):
    """Vrai si l'utilisateur est l'`admin` (Profile, user_type=
    'enseignant_admin') du Parcours concerné. Accepte en objet soit un
    Parcours directement, soit tout objet ayant un attribut `.parcours`
    (Departement, ...)."""

    def has_object_permission(self, request, view, obj):
        parcours = obj if type(obj).__name__ == 'Parcours' else getattr(obj, 'parcours', None)
        if parcours is None or parcours.admin_id is None:
            return False
        return parcours.admin.user_id == request.user.id


# ─────────────────────────────────────────────────────────────────────────
# TODO(arbitrage) : IsServiceClient demandée dans la tâche « fermer l'API
# par défaut », mais aucun rôle « service client » n'existe dans
# Profile.USER_TYPES ni ailleurs dans le modèle de données actuel (seule
# trace : le texte « Contactez le service client » affiché à l'apprenant,
# pas un rôle backend). Fail-closed en attendant une réponse : cette
# permission refuse tout le monde plutôt que de deviner un mapping vers un
# rôle existant (ex. admin). Voir question posée dans la conversation.
# ─────────────────────────────────────────────────────────────────────────
class IsServiceClient(BasePermission):
    def has_permission(self, request, view):
        return False
