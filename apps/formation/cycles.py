"""
Cycles d'un département : périodes d'abonnement ET de classement.

L'enseignant administrateur définit, pour chaque département :
- la date de début du premier cycle ;
- la durée d'un cycle, en mois (1 à 12) ;
- le nombre de cycles par an, au plus 12 // durée ;
- le placement des cycles : « à la suite » (sans trou entre deux cycles)
  ou « répartis sur l'année » (un cycle commence tous les 12 / nombre mois).

Les dates de chaque cycle s'en déduisent ; aucune n'est stockée. Une fois
l'année écoulée, les mêmes cycles recommencent automatiquement, décalés de
12 mois (décision produit : reprise automatique).

Abonnements (décision produit) : l'« Abonnement annuel » (type `annuel`,
prix `Departement.prix_annuel`, le prix d'un cycle) donne le Premium du
département pendant 365 jours à partir du paiement ; le mensuel, 30 jours.
Le forum n'est en plus ouvert que pendant un cycle (`est_dans_un_cycle`,
voir `AccesService.forum_accessible`).

Le classement est remis à zéro à la fin de chaque cycle : la période de
classement suit les cycles.

La même règle de calcul est reproduite côté app pour l'aperçu du formulaire
(`lib/core/utils/cycles_departement.dart`) : les deux doivent rester
identiques.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta
from django.utils import timezone

PLACEMENT_SUITE = "suite"
PLACEMENT_REPARTIS = "repartis"
PLACEMENTS = [
    (PLACEMENT_SUITE, "À la suite"),
    (PLACEMENT_REPARTIS, "Répartis sur l'année"),
]


@dataclass(frozen=True)
class Cycle:
    numero: int  # 1 à nombre de cycles
    annee: int  # 0 pour la première année, puis 1, 2…
    debut: date  # premier jour du cycle
    fin: date  # lendemain du dernier jour (borne exclue)

    @property
    def dernier_jour(self) -> date:
        return self.fin - timedelta(days=1)

    @property
    def debut_dt(self) -> datetime:
        return _minuit(self.debut)

    @property
    def fin_dt(self) -> datetime:
        return _minuit(self.fin)

    def en_json(self) -> dict:
        return {
            "numero": self.numero,
            "debut": self.debut.isoformat(),
            "fin": self.dernier_jour.isoformat(),
        }


def _minuit(jour: date) -> datetime:
    return timezone.make_aware(datetime.combine(jour, time.min), timezone.get_current_timezone())


def nombre_max_cycles(duree_mois: int) -> int:
    """Nombre maximal de cycles par an pour une durée donnée (12 // durée)."""
    if not isinstance(duree_mois, int) or not 1 <= duree_mois <= 12:
        return 0
    return 12 // duree_mois


def erreurs_configuration(date_debut, duree_mois, nombre, placement) -> list[str]:
    """Messages d'erreur (en français, pour l'enseignant) ; liste vide si valide."""
    erreurs = []
    if not isinstance(date_debut, date):
        erreurs.append("La date de début du cycle est obligatoire.")
    if not isinstance(duree_mois, int) or not 1 <= duree_mois <= 12:
        erreurs.append("La période du cycle doit être comprise entre 1 et 12 mois.")
    else:
        maximum = nombre_max_cycles(duree_mois)
        if not isinstance(nombre, int) or not 1 <= nombre <= maximum:
            erreurs.append(
                f"Avec des cycles de {duree_mois} mois, le nombre de cycles doit être "
                f"compris entre 1 et {maximum}."
            )
    if placement not in (PLACEMENT_SUITE, PLACEMENT_REPARTIS):
        erreurs.append("Le placement des cycles doit être « suite » ou « repartis ».")
    return erreurs


def decalages_mois(duree_mois: int, nombre: int, placement: str) -> list[int]:
    """Décalage, en mois depuis le début de l'année de cycles, de chaque cycle."""
    if placement == PLACEMENT_REPARTIS:
        return [(i * 12) // nombre for i in range(nombre)]
    return [i * duree_mois for i in range(nombre)]


def configuration(departement) -> tuple[date, int, int, str]:
    """
    (date de début, durée, nombre, placement) du département. Un département
    créé avant les cycles n'a pas de date de début : on retombe sur son
    ancienne période de classement (même rythme qu'avant).
    """
    duree = departement.cycle_duree_mois
    nombre = departement.cycle_nombre
    placement = departement.cycle_placement
    date_debut = departement.cycle_date_debut
    if date_debut is None:
        reference = departement.date_debut_periode or departement.created_at or timezone.now()
        date_debut = timezone.localtime(reference).date()
        duree = min(max(departement.periode or 12, 1), 12)
        nombre = nombre_max_cycles(duree)
        placement = PLACEMENT_SUITE
    return date_debut, duree, nombre, placement


def cycles_de_l_annee(departement, annee: int = 0) -> list[Cycle]:
    date_debut, duree, nombre, placement = configuration(departement)
    base = date_debut + relativedelta(months=12 * annee)
    return [
        Cycle(
            numero=i + 1,
            annee=annee,
            debut=base + relativedelta(months=decalage),
            fin=base + relativedelta(months=decalage + duree),
        )
        for i, decalage in enumerate(decalages_mois(duree, nombre, placement))
    ]


def cycle_pour(departement, quand=None) -> Cycle:
    """
    Cycle en cours à la date `quand` (maintenant par défaut) ; entre deux
    cycles, ou avant le tout premier, le cycle suivant.
    """
    if quand is None:
        quand = timezone.now()
    jour = timezone.localtime(quand).date() if isinstance(quand, datetime) else quand
    date_debut = configuration(departement)[0]
    if jour < date_debut:
        return cycles_de_l_annee(departement, 0)[0]
    ecart = relativedelta(jour, date_debut)
    annee = ecart.years
    for a in (annee, annee + 1):
        for cycle in cycles_de_l_annee(departement, a):
            if cycle.fin > jour:
                return cycle
    return cycles_de_l_annee(departement, annee + 2)[0]  # filet de sécurité


def est_dans_un_cycle(departement, quand=None) -> bool:
    """Vrai si `quand` (maintenant par défaut) tombe pendant un cycle, pas entre deux."""
    if quand is None:
        quand = timezone.now()
    jour = timezone.localtime(quand).date() if isinstance(quand, datetime) else quand
    return cycle_pour(departement, jour).debut <= jour


def _entier(valeur):
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


def _date(valeur):
    if isinstance(valeur, date):
        return valeur
    try:
        return date.fromisoformat(str(valeur)[:10])
    except (TypeError, ValueError):
        return None


def lire_configuration_cycles(donnees) -> tuple[dict, list[str]]:
    """
    Lit et valide les champs de cycles envoyés à la création d'un
    département (JSON ou multipart). Renvoie (champs du modèle, erreurs).

    Une ancienne version de l'app n'envoie que `periode` : on en déduit des
    cycles à la suite qui démarrent aujourd'hui, au même rythme.
    """
    duree = _entier(donnees.get("cycle_duree_mois"))
    if duree is None:
        periode = _entier(donnees.get("periode"))
        if periode is None or periode <= 0:
            return {}, ["La période du cycle est obligatoire."]
        duree = min(periode, 12)
        champs = {
            "cycle_date_debut": timezone.localdate(),
            "cycle_duree_mois": duree,
            "cycle_nombre": nombre_max_cycles(duree),
            "cycle_placement": PLACEMENT_SUITE,
        }
        return champs, []

    champs = {
        "cycle_date_debut": _date(donnees.get("cycle_date_debut")),
        "cycle_duree_mois": duree,
        "cycle_nombre": _entier(donnees.get("cycle_nombre")),
        "cycle_placement": (donnees.get("cycle_placement") or PLACEMENT_SUITE).strip(),
    }
    erreurs = erreurs_configuration(
        champs["cycle_date_debut"],
        champs["cycle_duree_mois"],
        champs["cycle_nombre"],
        champs["cycle_placement"],
    )
    return champs, erreurs


def libelle_abonnement_cycle(departement) -> str:
    """Nom de l'offre payée au prix du cycle : toujours « Abonnement annuel » (décision produit)."""
    return "Abonnement annuel"
