from rest_framework.permissions import BasePermission

from apps.core.services import AccesService


class AccesMatricePermission(BasePermission):
    """
    Permission DRF déléguant à AccesService (P9.1, CDC_BACKEND §5.2) —
    première permission_class custom du projet : le reste du code fait
    IsAuthenticated + logique inline, mais le ticket exige explicitement
    qu'aucune vue ne réimplémente la matrice Gratuit/Premium.

    Usage : la vue déclare
        permission_classes = [IsAuthenticated, AccesMatricePermission]
        acces_modele = Exercice          # classe du modèle concerné
        acces_action = "voir"            # ou "soumettre" (défaut "voir")

    `has_permission` tranche déjà pour les vues liste sans instance
    (Devoir/QuestionForum, tout-ou-rien). Pour les vues détail/action,
    DRF n'appelle `has_object_permission` que via
    `self.check_object_permissions(request, objet)` — jamais
    automatiquement dans ce projet, car aucune vue n'utilise
    `generics.RetrieveAPIView.get_object()` (toutes utilisent
    `get_object_or_404` à la main) : chaque vue concernée doit donc
    appeler explicitement cette méthode après avoir récupéré l'objet.
    """

    message = "Cette fonctionnalité est réservée aux abonnés Premium."

    def _methode(self, view):
        action = getattr(view, "acces_action", "voir")
        return AccesService.peut_soumettre if action == "soumettre" else AccesService.peut_voir

    def _departement_liste(self, request, view):
        """Résout un département pour les vues LISTE (sans objet) à
        partir d'un `cours_id` déjà disponible — soit en paramètre
        d'URL (`cours/<cours_id>/exercices/`, `.../devoirs/`), soit en
        paramètre de requête optionnel (`/devoirs/?cours_id=`,
        `/forum/questions/?cours_id=`). Le Premium devient ainsi
        réellement PAR DÉPARTEMENT dès que le contexte le permet ; sans
        `cours_id` (ex. liste globale non filtrée), `None` fait retomber
        `AccesService` sur son filet de sécurité (« premium dans
        n'importe quel département »), comportement déjà correct."""
        cours_id = getattr(view, "kwargs", {}).get("cours_id") or getattr(
            request, "query_params", {}
        ).get("cours_id")
        if not cours_id:
            return None
        from apps.formation.models import Cours

        try:
            return Cours.objects.select_related("departement").get(pk=cours_id).departement
        except (Cours.DoesNotExist, ValueError, TypeError):
            return None

    def has_permission(self, request, view):
        modele = getattr(view, "acces_modele", None)
        if modele is None:
            return True
        departement = self._departement_liste(request, view)
        return self._methode(view)(request.user, modele, departement=departement)

    def has_object_permission(self, request, view, obj):
        return self._methode(view)(request.user, obj)
