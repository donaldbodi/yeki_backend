"""
Lieu unique de calcul pour tout ce qui touche à la notation d'exercices et
au classement (P6.1). Remplace :

- `_enregistrer_evaluation_finale` (auparavant dupliquée dans
  `apps/evaluation/views/exercices.py`) — note officielle d'UN exercice.
- `RankingService` (auparavant `apps/evaluation/views/classement.py`,
  un stub non fonctionnel — `obtenir_classement_departement` et consorts
  n'existaient pas sur la classe) — score de classement à travers
  PLUSIEURS exercices.
- Les `Avg(EvaluationExercice.score)` de
  `apps/accounts/views/dashboards.py` et
  `apps/formation/views/dashboards.py`.

Règle métier actée (P6.1, aucune ambiguïté) : la note officielle d'un
exercice, ce sont les points de la DERNIÈRE tentative comprise dans le
nombre normal de tentatives (`Exercice.tentatives_max`) — jamais une
moyenne, jamais un maximum.

Le classement à travers plusieurs exercices reste une SOMME (pas une
moyenne, décision P6.1 inchangée) mais est désormais PONDÉRÉE par étoile
d'exercice (P6.3, décision qui REMPLACE explicitement le choix P6.1 de
« pas de pondération » — le commanditaire est revenu dessus : « il faut
faire une différence entre les exercices de 5,4,3,2,1 étoiles »). Poids
lus depuis `ParametreClassement` (jamais en dur), progression
volontairement NON LINÉAIRE (un 5★ vaut bien plus que 5× un 1★).
"""

from django.contrib.auth.models import User
from django.db.models import Sum

from apps.evaluation.models import (
    EvaluationExercice,
    ParametreClassement,
    RangApprenant,
    ScoreDetail,
)
from apps.formation.models import Cours, Departement


class ClassementService:
    """Unique lieu de calcul des notes d'exercice et du classement."""

    @staticmethod
    def enregistrer_evaluation_finale(user, exercice, tentative):
        """
        Met à jour (ou crée) l'`EvaluationExercice` "officielle" de
        l'utilisateur pour cet exercice : elle reflète TOUJOURS les points
        de la tentative fournie — jamais une moyenne, jamais un maximum.
        `tentative` est déjà garantie être la dernière tentative autorisée
        par l'appelant (la création de nouvelles tentatives est plafonnée
        par `exercice.tentatives_max` avant d'atteindre ce point).

        Ne recopie plus le détail par question dans `ReponseExercice`
        (P6.2, décision actée) — ce modèle est devenu redondant depuis que
        `tentative.reponses` porte lui-même le snapshot complet et
        auto-suffisant de la tentative (voir
        `apps/evaluation/views/exercices.py::_corriger_reponses_exercice`).
        `ReponseExercice` n'est plus alimenté ; modèle et table conservés
        (règle « ne rien perdre »).
        """
        evaluation, _created = EvaluationExercice.objects.update_or_create(
            user=user,
            exercice=exercice,
            defaults={
                "score": tentative.score,
                "total": tentative.total_points,
                "tentative_finale": tentative,
            },
        )
        return evaluation

    @staticmethod
    def poids_par_etoile() -> dict:
        """
        Poids de classement par étoile d'exercice (1 à 5), lus depuis
        `ParametreClassement` — jamais en dur (P6.3, exigence explicite :
        modifiables sans redéploiement). Repli à 1.0 si une valeur n'a
        pas encore été semée (ne devrait pas arriver après migration,
        évite un crash plutôt qu'une KeyError sur une base incomplète).
        """
        poids_bruts = dict(
            ParametreClassement.objects.filter(
                source__in=["etoile_1", "etoile_2", "etoile_3", "etoile_4", "etoile_5"]
            ).values_list("source", "poids")
        )
        return {etoiles: poids_bruts.get(f"etoile_{etoiles}", 1.0) for etoiles in range(1, 6)}

    @classmethod
    def score_departement(cls, apprenant, departement: Departement, poids_par_etoile=None) -> float:
        """
        Somme PONDÉRÉE (P6.3) des points de la dernière évaluation de
        chaque exercice du département : `evaluation.score × poids de
        l'étoile de l'exercice` — pas de moyenne, pas de pourcentage.
        `apprenant` peut être un `User` ou un id (Django résout les deux
        de façon identique pour un filtre exact). `poids_par_etoile`
        permet à un appelant qui traite plusieurs apprenants (voir
        `calculer_classement_departement`) de ne charger les poids
        qu'une seule fois plutôt qu'à chaque apprenant.
        """
        if poids_par_etoile is None:
            poids_par_etoile = cls.poids_par_etoile()

        cours_ids = Cours.objects.filter(departement=departement).values_list("id", flat=True)
        evaluations = EvaluationExercice.objects.filter(
            user=apprenant, exercice__cours_id__in=cours_ids
        ).values_list("score", "exercice__etoiles")
        return sum(score * poids_par_etoile.get(etoiles, 1.0) for score, etoiles in evaluations)

    @staticmethod
    def score_total_exercices_enseignant(enseignant, departements=None) -> float:
        """
        Somme brute des points de toutes les évaluations d'exercices des
        cours de cet enseignant — remplace les anciens
        `Avg(EvaluationExercice.score)` des dashboards (accounts/formation).
        `departements` restreint optionnellement aux cours de ces
        départements (dashboard cadre de département).
        """
        qs = EvaluationExercice.objects.filter(exercice__cours__enseignant_principal=enseignant)
        if departements is not None:
            qs = qs.filter(exercice__cours__departement__in=departements)
        return qs.aggregate(total=Sum("score"))["total"] or 0.0

    @classmethod
    def calculer_classement_departement(cls, departement: Departement, limit=None) -> list[dict]:
        """
        Classe, par score décroissant, tous les apprenants ayant au moins
        une évaluation d'exercice dans ce département.
        """
        cours_ids = Cours.objects.filter(departement=departement).values_list("id", flat=True)
        apprenant_ids = (
            EvaluationExercice.objects.filter(exercice__cours_id__in=cours_ids)
            .values_list("user_id", flat=True)
            .distinct()
        )

        # Poids chargés UNE SEULE FOIS pour tout le département (P6.3),
        # pas à chaque apprenant de la boucle ci-dessous.
        poids_par_etoile = cls.poids_par_etoile()

        # `nom`/`username` chargés en masse (une requête, pas une par
        # apprenant) — absents jusqu'ici de la réponse alors que le
        # frontend les lisait déjà (`item['nom']`/`item['username']`),
        # rendant les noms systématiquement vides dans le classement
        # affiché (P11.8, bug confirmé en même temps que le câblage de
        # `YkLeaderboard`).
        utilisateurs = {
            u["id"]: u
            for u in User.objects.filter(id__in=apprenant_ids).values(
                "id", "first_name", "last_name", "username"
            )
        }

        resultats = []
        for apprenant_id in apprenant_ids:
            rang_existant = RangApprenant.objects.filter(
                apprenant_id=apprenant_id, departement=departement
            ).first()
            u = utilisateurs.get(apprenant_id, {})
            nom = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or u.get("username", "")
            resultats.append(
                {
                    "apprenant_id": apprenant_id,
                    "nom": nom,
                    "username": u.get("username", ""),
                    "score": cls.score_departement(apprenant_id, departement, poids_par_etoile),
                    "progression": rang_existant.progression_semaine if rang_existant else 0.0,
                }
            )

        resultats.sort(key=lambda r: r["score"], reverse=True)
        for position, r in enumerate(resultats, start=1):
            r["rang"] = position

        if limit is not None:
            resultats = resultats[:limit]
        return resultats

    @classmethod
    def mettre_a_jour_rangs_departement(cls, departement: Departement) -> int:
        """Recalcule et persiste le classement d'un département dans
        `RangApprenant` (+ `ScoreDetail` catégorie "exercices")."""
        classement = cls.calculer_classement_departement(departement)
        for entree in classement:
            rang_apprenant, _created = RangApprenant.objects.update_or_create(
                apprenant_id=entree["apprenant_id"],
                departement=departement,
                defaults={"score": entree["score"], "rang": entree["rang"]},
            )
            ScoreDetail.objects.update_or_create(
                rang_apprenant=rang_apprenant,
                categorie="exercices",
                defaults={"score": entree["score"]},
            )
        return len(classement)

    @classmethod
    def mettre_a_jour_tous_les_rangs(cls) -> int:
        total = 0
        for departement in Departement.objects.all():
            total += cls.mettre_a_jour_rangs_departement(departement)
        return total

    @classmethod
    def recalculer_et_detecter_gain(cls, user, departement: Departement) -> dict | None:
        """
        Recalcule le classement du département (P6.3, appelé après
        chaque soumission d'exercice) et détecte si LE RANG de `user`
        s'est amélioré (un nombre plus petit) par rapport à sa valeur
        juste avant ce recalcul. Retourne
        `{"rang_gagne": True, "ancien_rang", "nouveau_rang"}` si
        amélioré, sinon `None` (pas de changement, ça empire, ou premier
        calcul — pas d'« ancien rang » à comparer).

        Recalcule TOUT le département à chaque appel (comme
        `mettre_a_jour_rangs_departement`) — accepté comme compromis pour
        la taille actuelle de la plateforme, pas d'optimisation
        supplémentaire dans ce ticket.
        """
        rang_avant = RangApprenant.objects.filter(apprenant=user, departement=departement).first()
        ancien_rang = rang_avant.rang if rang_avant else None

        cls.mettre_a_jour_rangs_departement(departement)

        rang_apres = RangApprenant.objects.filter(apprenant=user, departement=departement).first()
        nouveau_rang = rang_apres.rang if rang_apres else None

        if ancien_rang is not None and nouveau_rang is not None and nouveau_rang < ancien_rang:
            return {
                "rang_gagne": True,
                "ancien_rang": ancien_rang,
                "nouveau_rang": nouveau_rang,
            }
        return None
