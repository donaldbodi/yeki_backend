"""
Services partagés de l'app paiement (P9.2, étendu P9.7).
"""

from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.core.models import ParametreSysteme
from apps.evaluation.models import Olympiade
from apps.formation.models import Departement, DemandeAccesFormation
from apps.paiement.models import (
    AbonnementPremium,
    Paiement,
    PaiementOlympiade,
    YekiWallet,
)


def repartir_et_crediter(
    montant: int,
    part_yeki_pourcent: float,
    profile_cadre,
    description: str,
    reference: str,
) -> int:
    """
    Répartit `montant` entre la part Yéki et la part du cadre bénéficiaire
    (organisateur d'olympiade ou cadre de département formation). Crédite
    le wallet du cadre si `profile_cadre` est renseigné et a un `user`
    associé. Retourne la part Yéki (le reste), destinée à
    `Paiement.commission_yeki`.

    Ne débite RIEN côté apprenant : le flux de paiement manuel (P9.2) reçoit
    l'argent hors application, contrairement au paiement par portefeuille
    (`apps/evaluation/views/olympiades.py`, qui débite le wallet de
    l'apprenant) — cette fonction n'est PAS un remplacement de ce chemin-là,
    seulement du calcul de répartition + crédit du cadre, réutilisé ici.
    """
    part_yeki = int(montant * part_yeki_pourcent / 100)
    part_cadre = montant - part_yeki
    if profile_cadre is not None and getattr(profile_cadre, "user_id", None):
        wallet_cadre = YekiWallet.get_or_create_wallet(profile_cadre.user)
        wallet_cadre.crediter(part_cadre, description=description, reference=reference)
    return part_yeki


def finaliser_paiement(
    *,
    user_apprenant,
    categorie: str,
    montant: int,
    moyen: str,
    transaction_id: str = "",
    reference: str = "",
    objet_id=None,
    departement=None,
    type_abonnement=None,
    demande_manuelle=None,
) -> Paiement:
    """
    Point d'entrée UNIQUE de crédit/déblocage post-paiement, quel que soit
    le fournisseur (P9.7 : `ManuelProvider`/`CinetPayProvider` délèguent
    tous les deux ici). Extrait du branchement par catégorie auparavant
    codé uniquement dans `ValiderPaiementManuelView` — avant cette
    extraction, un paiement CinetPay réussi ne passait JAMAIS par cette
    logique (ne créditait aucun cadre, ne débloquait aucun accès
    département/olympiade), un écart de comportement réel entre
    fournisseurs que cette fonction unique élimine.

    `categorie` suit le vocabulaire de `DemandePaiementManuelle.CATEGORIES`
    ("recharge"|"abonnement"|"olympiade"|"formation"|"presentiel") — au
    fournisseur appelant de traduire son propre vocabulaire vers celui-ci
    (ex. CinetPay : "acces_departement" → "formation").

    `objet_id` est l'ID olympiade (categorie="olympiade") ou département
    (categorie="formation") si `departement` n'est pas déjà résolu.
    """
    commission_yeki = 0
    olympiade = None
    type_paiement_trace = ""

    if categorie == "recharge":
        YekiWallet.get_or_create_wallet(user_apprenant).crediter(
            montant,
            description=f"Recharge {moyen} — {reference or transaction_id}",
            reference=reference or transaction_id,
        )
        type_paiement_trace = "recharge_wallet"

    elif categorie == "abonnement":
        type_abonnement = type_abonnement or (
            "annuel" if montant >= AbonnementPremium.TARIFS["annuel"] else "mensuel"
        )
        type_paiement_trace = f"abonnement_{type_abonnement}"

    elif categorie == "olympiade":
        olympiade = get_object_or_404(Olympiade, pk=objet_id)
        pct = float(ParametreSysteme.get("part_yeki_olympiade", default=80))
        commission_yeki = repartir_et_crediter(
            montant,
            pct,
            olympiade.organisateur,
            description=f"Participation — olympiade « {olympiade.titre} »",
            reference=reference or f"OLYMP-{objet_id}-{user_apprenant.id}",
        )
        PaiementOlympiade.objects.update_or_create(
            apprenant=user_apprenant,
            olympiade=olympiade,
            defaults={"montant": montant, "statut": "paye", "paye_le": timezone.now()},
        )
        type_paiement_trace = "olympiade_participation"

    elif categorie == "formation":
        departement = departement or get_object_or_404(Departement, pk=objet_id)
        pct = float(ParametreSysteme.get("part_yeki_formation", default=30))
        commission_yeki = repartir_et_crediter(
            montant,
            pct,
            departement.cadre,
            description=f"Inscription — {departement.nom}",
            reference=reference or f"FORM-{departement.id}-{user_apprenant.id}",
        )
        # Réplique EXACTE de GererDemandeAccesView (apps/formation/views/
        # departements.py) : accepter le statut SEUL ne débloque rien,
        # get_est_accessible vérifie apprenants_autorises, pas
        # DemandeAccesFormation.statut.
        DemandeAccesFormation.objects.update_or_create(
            apprenant=user_apprenant,
            departement=departement,
            defaults={"statut": "acceptee", "traite_le": timezone.now()},
        )
        departement.apprenants_autorises.add(user_apprenant)
        type_paiement_trace = "acces_departement"

    else:  # presentiel — aucun modèle de déblocage dédié n'existe
        type_paiement_trace = "supplement_presentiel"

    paiement = Paiement.objects.create(
        utilisateur=user_apprenant,
        type_paiement=type_paiement_trace,
        moyen=moyen,
        montant=montant,
        statut="succes",
        transaction_id=transaction_id,
        reference=reference,
        commission_yeki=commission_yeki,
        demande_manuelle=demande_manuelle,
        departement=departement if categorie == "formation" else None,
        olympiade_liee=olympiade if categorie == "olympiade" else None,
    )

    if categorie == "abonnement":
        # Réplique exacte du pattern déjà utilisé par
        # WalletRechargerView._google_play (apps/paiement/views.py).
        jours = 30 if type_abonnement == "mensuel" else 365
        try:
            abo = user_apprenant.abonnement
            abo.renouveler(type_abonnement)
            abo.paiement = paiement
            abo.save()
        except AbonnementPremium.DoesNotExist:
            AbonnementPremium.objects.create(
                utilisateur=user_apprenant,
                type_abonnement=type_abonnement,
                actif=True,
                fin=timezone.now() + timedelta(days=jours),
                paiement=paiement,
            )

    return paiement
