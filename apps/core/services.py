from django.core.exceptions import PermissionDenied
from django.utils import timezone


class AccesService:
    """
    Source UNIQUE de la matrice d'accès Gratuit/Premium (P9.1,
    CDC_BACKEND §5.2). Toute vue qui a besoin de savoir si un apprenant
    peut VOIR ou SOUMETTRE un objet doit passer par ici — jamais
    réimplémenter la règle dans une vue (voir `apps.core.permissions.
    AccesMatricePermission`).

    En mode gratuit, l'apprenant VOIT les exercices 1★ et 2★ mais ne peut
    SOUMETTRE que les 1★ : ce n'est pas une incohérence, c'est une
    vitrine — il voit ce qu'il rate. D'où les deux méthodes distinctes.

    Rectification (demande explicite) : le Premium est désormais PAR
    DÉPARTEMENT, plus un abonnement global unique — `AbonnementPremium`
    porte maintenant un `departement`. Chaque méthode accepte un
    paramètre `departement` optionnel : fourni, elle vérifie l'abonnement
    de CE département précisément ; absent (contenu structurellement
    sans département résolvable — question de forum "libre", devoir lié
    à une olympiade), elle retombe sur la règle « premium dans N'IMPORTE
    QUEL département » — filet de sécurité, pas une réintroduction du
    global.
    """

    # Seuils fixés par le CDC lui-même (pas un paramètre produit ajustable
    # comme solde_min_ia) — constantes Python documentées, pas
    # ParametreSysteme.
    ETOILES_VITRINE_GRATUIT = 2
    ETOILES_SOUMISSION_GRATUIT = 1

    @staticmethod
    def _est_apprenant(user) -> bool:
        if not getattr(user, "is_authenticated", False):
            return False
        profile = getattr(user, "profile", None)
        return bool(profile) and profile.user_type == "apprenant"

    @staticmethod
    def est_premium(user, departement=None) -> bool:
        """Vrai si l'utilisateur a un AbonnementPremium actif — dans
        `departement` précisément si fourni, dans N'IMPORTE LEQUEL sinon
        (filet de sécurité pour le contenu sans département résolvable)."""
        if not getattr(user, "is_authenticated", False):
            return False
        from apps.paiement.models import AbonnementPremium

        qs = AbonnementPremium.objects.filter(
            utilisateur=user, actif=True, fin__gt=timezone.now()
        )
        if departement is not None:
            qs = qs.filter(departement=departement)
        return qs.exists()

    @staticmethod
    def _resoudre_departement(objet):
        """Département de `objet` si résolvable depuis son propre graphe
        de relations, sinon `None` (ex. `objet` est une CLASSE, pas une
        instance — vue liste ; ou un Devoir lié à une olympiade,
        `cours_lie` alors `None`)."""
        from apps.evaluation.models import Exercice, Devoir
        from apps.formation.models import Lecon

        if isinstance(objet, Lecon):
            return objet.cours.departement
        if isinstance(objet, Exercice):
            return objet.cours.departement
        if isinstance(objet, Devoir):
            return objet.cours_lie.departement if objet.cours_lie else None
        return None

    @staticmethod
    def _est_ou_est_classe(objet, modele) -> bool:
        """objet peut être une INSTANCE (vue détail/action) ou la CLASSE
        du modèle elle-même (vue liste sans filtrage fin possible, ex.
        Devoir/QuestionForum en tout-ou-rien)."""
        if isinstance(objet, modele):
            return True
        return isinstance(objet, type) and issubclass(objet, modele)

    @classmethod
    def _olympiade_est_payee(cls, user, olympiade) -> bool:
        from apps.paiement.models import PaiementOlympiade

        if not olympiade.demande_paiement_participants or olympiade.prix_participation <= 0:
            return True
        return PaiementOlympiade.objects.filter(
            apprenant=user, olympiade=olympiade, statut="paye"
        ).exists()

    @classmethod
    def peut_voir(cls, user, objet, departement=None) -> bool:
        from apps.evaluation.models import Exercice, Devoir, Olympiade
        from apps.forum.models import QuestionForum
        from apps.repetiteurs.models import Repetiteur
        from apps.formation.models import Lecon

        if not cls._est_apprenant(user):
            return True
        if cls.est_premium(user, departement or cls._resoudre_departement(objet)):
            return True

        if isinstance(objet, Exercice):
            return objet.etoiles <= cls.ETOILES_VITRINE_GRATUIT
        if objet is Exercice:
            # Liste : le tout-ou-rien ne s'applique pas, voir
            # etoiles_max_visibles() pour filtrer le queryset.
            return True
        if cls._est_ou_est_classe(objet, Devoir):
            return False
        if cls._est_ou_est_classe(objet, QuestionForum):
            return False
        if cls._est_ou_est_classe(objet, Repetiteur):
            return True
        if cls._est_ou_est_classe(objet, Olympiade):
            # Il faut voir l'olympiade pour décider de payer : toujours
            # visible, gratuit comme premium.
            return True
        if isinstance(objet, Lecon):
            # Le PDF reste toujours visible en gratuit — seule la vidéo
            # est démasquée séparément, voir peut_voir_video_lecon().
            return True

        raise TypeError(f"AccesService.peut_voir : type non géré ({type(objet)!r}).")

    @classmethod
    def peut_soumettre(cls, user, objet, departement=None) -> bool:
        from apps.evaluation.models import Exercice, Devoir, Olympiade
        from apps.forum.models import QuestionForum
        from apps.repetiteurs.models import Repetiteur

        if not cls._est_apprenant(user):
            return True

        # Olympiade AVANT le raccourci Premium ci-dessous : le paiement par
        # olympiade (P8.x, PaiementOlympiade) est un axe de revenu séparé
        # que le statut Premium ne dispense PAS de régler — sinon un
        # abonné Premium participerait gratuitement à toutes les
        # olympiades payantes, ce qui n'a aucun sens vis-à-vis du système
        # de paiement par olympiade déjà construit et testé.
        if isinstance(objet, Olympiade):
            return cls._olympiade_est_payee(user, objet)
        if objet is Olympiade:
            return True

        if cls.est_premium(user, departement or cls._resoudre_departement(objet)):
            return True

        if isinstance(objet, Exercice):
            return objet.etoiles <= cls.ETOILES_SOUMISSION_GRATUIT
        if objet is Exercice:
            return True
        if cls._est_ou_est_classe(objet, Devoir):
            return False
        if cls._est_ou_est_classe(objet, QuestionForum):
            return False
        if cls._est_ou_est_classe(objet, Repetiteur):
            return True

        raise TypeError(f"AccesService.peut_soumettre : type non géré ({type(objet)!r}).")

    @classmethod
    def etoiles_max_visibles(cls, user, departement=None) -> int | None:
        """None = illimité (premium — dans `departement` si fourni — ou
        non-apprenant). Sinon le seuil ★ maximum visible — sert à
        FILTRER un queryset de liste (ListeExercicesCoursView) sans
        appeler peut_voir en boucle sur chaque ligne. Reste cohérent avec
        peut_voir (testé)."""
        if not cls._est_apprenant(user) or cls.est_premium(user, departement):
            return None
        return cls.ETOILES_VITRINE_GRATUIT

    @classmethod
    def peut_voir_video_lecon(cls, user, lecon=None) -> bool:
        """Pas une 3e méthode de la matrice au sens strict du ticket : ne
        décide pas si un OBJET de la matrice est visible, mais démasque
        un CHAMP (video) d'une Lecon déjà visible (peut_voir(Lecon) est
        toujours True). GRATUIT = PDF seulement, PREMIUM = vidéo incluse
        — Premium DU DÉPARTEMENT de `lecon` si fourni (résolu via
        `lecon.cours.departement`), sinon repli sur la règle globale."""
        if not cls._est_apprenant(user):
            return True
        departement = lecon.cours.departement if lecon is not None else None
        return cls.est_premium(user, departement)


def check_role(user, allowed_roles):
    """
    Raise PermissionDenied si user.user_type n'est pas dans allowed_roles.
    """
    if not hasattr(user, "user_type"):
        raise PermissionDenied("Utilisateur non valide.")
    if user.user_type not in allowed_roles:
        raise PermissionDenied("Vous n’avez pas les permissions nécessaires.")


def _get_client_ip(request):
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
