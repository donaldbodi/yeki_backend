"""
Abstraction fournisseur de paiement (P9.7).

`ParametreSysteme['mode_paiement']` (`'manuel'|'cinetpay'|'les_deux'`)
décide À L'EXÉCUTION quel(s) fournisseur(s) sont actifs, sans redéploiement
— voir `mode_paiement_actif()`. Les deux implémentations partagent un corps
IDENTIQUE (délèguent à `finaliser_paiement`) : c'est précisément ce qui
garantit que le reste de l'application ignore quel fournisseur a traité un
paiement donné, et rend la bascule manuel ↔ CinetPay instantanée et
réversible.
"""

from abc import ABC, abstractmethod

from apps.core.models import ParametreSysteme
from apps.paiement.models import Paiement
from apps.paiement.services import finaliser_paiement


def mode_paiement_actif() -> str:
    """Point de lecture unique de `ParametreSysteme['mode_paiement']` —
    tout code qui a besoin de savoir quel(s) parcours sont autorisés
    aujourd'hui doit passer par ici, jamais relire la clé directement."""
    return ParametreSysteme.get("mode_paiement", default="manuel")


class PaiementProvider(ABC):
    """Interface commune — un seul point d'extension (`finaliser`), pour
    qu'aucune logique métier ne puisse diverger entre fournisseurs."""

    @abstractmethod
    def finaliser(self, **kwargs) -> Paiement:
        ...


class ManuelProvider(PaiementProvider):
    def finaliser(self, **kwargs) -> Paiement:
        return finaliser_paiement(**kwargs)


class CinetPayProvider(PaiementProvider):
    def finaliser(self, **kwargs) -> Paiement:
        return finaliser_paiement(**kwargs)
