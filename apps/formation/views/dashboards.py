import logging

from django.db.models import Avg, F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.core.schema_examples import ERREURS_COURANTES
from apps.evaluation.models import Devoir, SoumissionDevoir, EvaluationExercice
from apps.formation.models import Departement, Cours, Lecon, ProgressionLecon

logger = logging.getLogger(__name__)


@extend_schema_view(
    get=extend_schema(
        summary="Dashboard de l'enseignant cadre",
        description=(
            "Retourne tous les départements gérés par l'enseignant cadre "
            "connecté, avec leurs cours, enseignants principaux et "
            "statistiques agrégées. Réservé aux profils de type "
            "'enseignant_cadre'. Réponse : `{nom, departements: [...], "
            "enseignants_principaux: [...], stats: {nb_departements, "
            "nb_cours, nb_apprenants, nb_enseignants, taux_moyen}}`."
        ),
        tags=["formation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class EnseignantCadreDashboardView(APIView):
    """
    GET /api/enseignant/cadre/dashboard/

    Retourne tous les départements gérés par l'enseignant cadre,
    avec leurs cours, enseignants principaux et statistiques.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_cadre":
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ✅ Récupérer TOUS les départements du cadre
        departements = (
            Departement.objects.filter(cadre=profile, est_actif=True)
            .select_related("parcours")
            .prefetch_related("cours__enseignant_principal__user", "cours__enseignants__user")
        )

        nom_complet = (
            f"{profile.user.first_name} {profile.user.last_name}".strip() or profile.user.username
        )

        # Si aucun département, retourner une structure vide
        if not departements.exists():
            return Response(
                {
                    "nom": nom_complet,
                    "departements": [],
                    "stats": {
                        "nb_departements": 0,
                        "nb_cours": 0,
                        "nb_apprenants": 0,
                        "nb_enseignants": 0,
                        "taux_moyen": 0,
                    },
                },
                status=status.HTTP_200_OK,
            )

        # ── Construire les données pour chaque département ──
        departements_data = []
        stats_globales = {
            "nb_departements": departements.count(),
            "nb_cours": 0,
            "nb_apprenants": 0,
            "nb_enseignants": 0,
            "taux_moyen": 0,
        }

        # Pour éviter les doublons d'enseignants
        enseignants_ids = set()
        total_taux = 0

        for dept in departements:
            # Récupérer les cours du département
            cours_qs = Cours.objects.filter(departement=dept).select_related(
                "enseignant_principal__user"
            )

            cours_data = []
            for c in cours_qs:
                ep_data = None
                if c.enseignant_principal:
                    ep = c.enseignant_principal
                    ep_data = {
                        "id": ep.id,
                        "nom": f"{ep.user.first_name} {ep.user.last_name}".strip()
                        or ep.user.username,
                        "username": ep.user.username,
                        "photo": request.build_absolute_uri(ep.avatar.url) if ep.avatar else None,
                    }
                    enseignants_ids.add(ep.id)

                # Calcul du taux de complétion moyen du cours
                taux_completion = self._calculer_taux_completion_cours(c, request.user)

                cours_data.append(
                    {
                        "id": c.id,
                        "titre": c.titre,
                        "niveau": c.niveau,
                        "nb_apprenants": c.nb_apprenants,
                        "taux_completion": taux_completion,
                        "color_code": c.color_code,
                        "icon_name": c.icon_name,
                        "enseignant_principal": ep_data,
                        "nb_lecons": c.nb_lecons,
                        "nb_devoirs": c.nb_devoirs,
                    }
                )

                stats_globales["nb_cours"] += 1
                total_taux += taux_completion

            # Récupérer les apprenants du parcours (calcul dynamique)
            parcours_nom = dept.parcours.nom if dept.parcours else ""
            nb_apprenants = Profile.objects.filter(
                user_type="apprenant", cursus=parcours_nom, is_active=True
            ).count()
            stats_globales["nb_apprenants"] += nb_apprenants

            # Données du département
            dept_data = {
                "id": dept.id,
                "nom": dept.nom,
                "description": getattr(dept, "description", ""),
                "parcours": dept.parcours.nom if dept.parcours else "",
                "parcours_id": dept.parcours.id if dept.parcours else None,
                "couleur": dept.couleur,
                "prix": dept.prix,
                "est_actif": dept.est_actif,
                "type_departement": dept.type_departement,
                "image_url": request.build_absolute_uri(dept.image.url) if dept.image else None,
                # Champs spécifiques
                "est_prepa_concours": dept.est_prepa_concours,
                "nom_concours": dept.nom_concours,
                "organisme_concours": dept.organisme_concours,
                "date_limite_inscription": dept.date_limite_inscription,
                "date_examen": dept.date_examen,
                "est_formation_metier": dept.est_formation_metier,
                "est_formation_classique": dept.est_formation_classique,
                "duree_formation": dept.duree_formation,
                "mode": dept.mode,
                "certificat_delivre": dept.certificat_delivre,
                "ville": dept.ville,
                "domaine": dept.domaine,
                "est_certifiante": dept.est_certifiante,
                # Statistiques
                "nb_cours": cours_qs.count(),
                "nb_apprenants": nb_apprenants,
                "taux_moyen": self._calculer_taux_moyen_departement(cours_qs, request.user),
                "cours": cours_data,
            }
            departements_data.append(dept_data)

        # ── Enseignants principaux distincts ──
        enseignants_data = []
        for ep_id in enseignants_ids:
            try:
                ep = Profile.objects.get(id=ep_id)
                nb_cours_ep = Cours.objects.filter(
                    enseignant_principal=ep, departement__in=departements
                ).count()
                nb_app_ep = sum(
                    c.nb_apprenants
                    for c in Cours.objects.filter(
                        enseignant_principal=ep, departement__in=departements
                    )
                )

                # Score moyen à partir des évaluations
                avg = EvaluationExercice.objects.filter(
                    exercice__cours__enseignant_principal=ep,
                    exercice__cours__departement__in=departements,
                ).aggregate(moy=Avg("score"))["moy"]
                score_moyen = round((avg or 0) / 20 * 20, 1)

                enseignants_data.append(
                    {
                        "id": ep.id,
                        "nom": f"{ep.user.first_name} {ep.user.last_name}".strip()
                        or ep.user.username,
                        "username": ep.user.username,
                        "email": ep.user.email,
                        "photo": request.build_absolute_uri(ep.avatar.url) if ep.avatar else None,
                        "nb_cours": nb_cours_ep,
                        "nb_apprenants": nb_app_ep,
                        "score_moyen": score_moyen,
                    }
                )
            except Profile.DoesNotExist:
                pass

        # Calcul des moyennes globales
        if stats_globales["nb_cours"] > 0:
            stats_globales["taux_moyen"] = round(total_taux / stats_globales["nb_cours"], 1)
        stats_globales["nb_enseignants"] = len(enseignants_data)

        return Response(
            {
                "nom": nom_complet,
                "departements": departements_data,
                "enseignants_principaux": enseignants_data,
                "stats": stats_globales,
            },
            status=status.HTTP_200_OK,
        )

    def _calculer_taux_completion_cours(self, cours, user):
        """Calcule le taux de complétion d'un cours pour un apprenant donné."""
        total_lecons = Lecon.objects.filter(cours=cours).count()
        if total_lecons == 0:
            return 0.0
        terminees = ProgressionLecon.objects.filter(
            apprenant=user, cours=cours, terminee=True
        ).count()
        return round((terminees / total_lecons) * 100, 1)

    def _calculer_taux_moyen_departement(self, cours_qs, user):
        """Calcule le taux de complétion moyen d'un département."""
        if not cours_qs.exists():
            return 0.0
        total = 0
        count = 0
        for cours in cours_qs:
            taux = self._calculer_taux_completion_cours(cours, user)
            total += taux
            count += 1
        return round(total / count, 1) if count > 0 else 0.0


@extend_schema_view(
    get=extend_schema(
        summary="Statistiques du dashboard de l'enseignant principal",
        description=(
            "Retourne les statistiques agrégées du dashboard de l'enseignant "
            "principal connecté : compteurs globaux, détail des devoirs par "
            "cours, liste des apprenants à risque (taux de rendu < 50%) et "
            "tendance des rendus sur 7 jours. Réservé aux profils de type "
            "'enseignant_principal'. Réponse : `{nom, stats: {nb_cours, "
            "nb_lecons, nb_devoirs, nb_apprenants, taux_rendu_global, "
            "moyenne_globale, nb_retards}, devoirs_par_cours: [...], "
            "apprenants_risque: [...], tendance_rendus: [...]}`."
        ),
        tags=["formation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class PrincipalDashboardAPIView(APIView):
    """
    GET /api/principal/dashboard_stats/
    Retourne les statistiques du dashboard pour l'enseignant principal.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_principal":
            return Response({"detail": "Accès réservé aux enseignants principaux."}, status=403)

        # Récupérer les cours du principal
        cours = Cours.objects.filter(enseignant_principal=profile)
        cours_ids = cours.values_list("id", flat=True)

        # Si pas de cours, retourner des données vides
        if not cours_ids:
            return Response(
                {
                    "nom": f"{profile.user.first_name} {profile.user.last_name}".strip()
                    or profile.user.username,
                    "stats": {
                        "nb_cours": 0,
                        "nb_lecons": 0,
                        "nb_devoirs": 0,
                        "nb_apprenants": 0,
                        "taux_rendu_global": 0,
                        "moyenne_globale": 0,
                        "nb_retards": 0,
                    },
                    "devoirs_par_cours": [],
                    "apprenants_risque": [],
                    "tendance_rendus": [],
                }
            )

        # Statistiques de base
        nb_cours = cours.count()
        nb_lecons = Lecon.objects.filter(cours__in=cours_ids).count()
        nb_devoirs = Devoir.objects.filter(cours_lie__in=cours_ids).count()

        # Compter les apprenants
        parcours_noms = (
            Departement.objects.filter(cours__in=cours_ids)
            .values_list("parcours__nom", flat=True)
            .distinct()
        )

        apprenants = (
            Profile.objects.filter(user_type="apprenant", cursus__in=parcours_noms, is_active=True)
            .distinct()
            .count()
        )

        # Taux de rendu global
        total_rendus = SoumissionDevoir.objects.filter(
            devoir__cours_lie__in=cours_ids,  # NOTE: Vérifiez le nom du champ
            statut__in=["soumis", "corrige", "en_retard"],
        ).count()
        total_attendu = nb_devoirs * apprenants if apprenants > 0 else 1
        taux_rendu = (total_rendus / total_attendu * 100) if total_attendu > 0 else 0

        # Moyenne globale
        moyenne_globale = (
            SoumissionDevoir.objects.filter(
                devoir__cours_lie__in=cours_ids,  # NOTE: Vérifiez le nom du champ
                note__isnull=False,
            ).aggregate(Avg("note"))["note__avg"]
            or 0
        )

        # Retards
        retards = SoumissionDevoir.objects.filter(
            devoir__cours_lie__in=cours_ids,  # NOTE: Vérifiez le nom du champ
            soumis_le__gt=F("devoir__date_limite"),
        ).count()

        # Apprenants à risque
        apprenants_risque = []
        for p in Profile.objects.filter(
            user_type="apprenant", cursus__in=parcours_noms, is_active=True
        ).select_related("user"):
            soumissions = SoumissionDevoir.objects.filter(
                devoir__cours_lie__in=cours_ids,  # NOTE: Vérifiez le nom du champ
                utilisateur=p.user,
            )
            nb_rendus = soumissions.filter(statut__in=["soumis", "corrige", "en_retard"]).count()
            nb_devoirs_total = Devoir.objects.filter(cours__in=cours_ids).count()

            if nb_devoirs_total > 0:
                taux = nb_rendus / nb_devoirs_total * 100
                if taux < 50:
                    moyenne = (
                        soumissions.filter(note__isnull=False).aggregate(Avg("note"))["note__avg"]
                        or 0
                    )

                    raison = "Taux de rendu faible" if taux < 30 else "Taux de rendu moyen"

                    apprenants_risque.append(
                        {
                            "id": p.id,
                            "nom": p.user.last_name or "",
                            "prenom": p.user.first_name or "",
                            "email": p.user.email or "",
                            "taux_rendu": round(taux, 1),
                            "moyenne": round(moyenne, 1),
                            "raison": raison,
                        }
                    )

        # Devoirs par cours
        devoirs_par_cours = []
        for c in cours:
            try:
                devoirs = Devoir.objects.filter(cours_lie=c)  # NOTE: Vérifiez le nom du champ
                nb_devoirs_cours = devoirs.count()

                apprenants_cours = Profile.objects.filter(
                    user_type="apprenant",
                    cursus=(
                        c.departement.parcours.nom
                        if c.departement and c.departement.parcours
                        else ""
                    ),
                    is_active=True,
                ).count()

                rendus_cours = SoumissionDevoir.objects.filter(
                    devoir__in=devoirs, statut__in=["soumis", "corrige", "en_retard"]
                )
                total_rendus_cours = rendus_cours.count()
                total_attendu_cours = (
                    nb_devoirs_cours * apprenants_cours if apprenants_cours > 0 else 1
                )
                taux_cours = (
                    (total_rendus_cours / total_attendu_cours * 100)
                    if total_attendu_cours > 0
                    else 0
                )

                details_devoirs = []
                for devoir in devoirs:
                    try:
                        # Date limite avec gestion None
                        date_limite = None
                        if devoir.date_limite:
                            date_limite = devoir.date_limite.isoformat()

                        # Retards avec gestion None
                        nb_retards = 0
                        if devoir.date_limite:
                            nb_retards = rendus_cours.filter(
                                soumis_le__gt=devoir.date_limite
                            ).count()

                        # Note moyenne
                        note_moyenne = (
                            rendus_cours.filter(note__isnull=False).aggregate(Avg("note"))[
                                "note__avg"
                            ]
                            or 0
                        )

                        details_devoirs.append(
                            {
                                "id": devoir.id,
                                "titre": devoir.titre,
                                "date_limite": date_limite,
                                "nb_rendus": rendus_cours.filter(devoir=devoir).count(),
                                "nb_retards": nb_retards,
                                "taux_rendu": (
                                    (
                                        rendus_cours.filter(devoir=devoir).count()
                                        / apprenants_cours
                                        * 100
                                    )
                                    if apprenants_cours > 0
                                    else 0
                                ),
                                "note_moyenne": round(note_moyenne, 1) if note_moyenne else 0,
                                "type_correction": getattr(
                                    devoir, "type_correction", "auto"
                                ),  # NOTE: Vérifiez le nom du champ
                            }
                        )
                    except Exception:
                        # Volontairement large : une ligne de devoir
                        # défectueuse ne doit pas faire tomber tout le
                        # dashboard, seulement être ignorée.
                        logger.exception(
                            "Erreur traitement devoir %s (dashboard principal)", devoir.id
                        )
                        continue

                devoirs_par_cours.append(
                    {
                        "cours_id": c.id,
                        "cours_titre": c.titre,
                        "nb_devoirs": nb_devoirs_cours,
                        "taux_rendu": round(taux_cours, 1),
                        "details_devoirs": details_devoirs,
                    }
                )
            except Exception:
                # Volontairement large (idem ci-dessus).
                logger.exception("Erreur traitement cours %s (dashboard principal)", c.id)
                continue

        # Tendance des rendus (7 derniers jours)
        # timezone.localtime() (pas timezone.now() directement) : .date() sur
        # un datetime aware sans conversion donne le jour calendaire en UTC,
        # pas en heure locale Douala (UTC+1) — une soumission entre 23h et
        # minuit heure locale serait comptée sur le mauvais jour.
        tendance_rendus = []
        for i in range(6, -1, -1):
            date = timezone.localtime(timezone.now()).date() - timedelta(days=i)
            nb_rendus_jour = SoumissionDevoir.objects.filter(
                devoir__cours_lie__in=cours_ids,  # NOTE: Vérifiez le nom du champ
                soumis_le__date=date,
                statut__in=["soumis", "corrige", "en_retard"],
            ).count()
            tendance_rendus.append({"date": date.isoformat(), "nb_rendus": nb_rendus_jour})

        return Response(
            {
                "nom": f"{profile.user.first_name} {profile.user.last_name}".strip()
                or profile.user.username,
                "stats": {
                    "nb_cours": nb_cours,
                    "nb_lecons": nb_lecons,
                    "nb_devoirs": nb_devoirs,
                    "nb_apprenants": apprenants,
                    "taux_rendu_global": round(taux_rendu, 1),
                    "moyenne_globale": round(moyenne_globale, 1) if moyenne_globale else 0,
                    "nb_retards": retards,
                },
                "devoirs_par_cours": devoirs_par_cours,
                "apprenants_risque": apprenants_risque,
                "tendance_rendus": tendance_rendus,
            }
        )


@extend_schema_view(
    get=extend_schema(
        summary="Lister les apprenants d'un cours avec leurs statistiques",
        description=(
            "Retourne la liste des apprenants d'un cours de l'enseignant "
            "principal connecté, avec taux de rendu, moyenne, dernier rendu "
            "et nombre de retards. Réservé aux profils de type "
            "'enseignant_principal'."
        ),
        tags=["formation"],
        parameters=[
            OpenApiParameter(
                "cours_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=True,
                description="Id du cours dont on veut la liste des apprenants.",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class PrincipalApprenantsCoursAPIView(APIView):
    """
    GET /api/principal/apprenants_cours/
    Query param: ?cours_id=123
    Retourne la liste des apprenants d'un cours avec leurs statistiques.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_principal":
            return Response({"detail": "Accès réservé aux enseignants principaux."}, status=403)

        cours_id = request.query_params.get("cours_id")
        if not cours_id:
            return Response({"detail": "cours_id requis."}, status=400)

        try:
            cours = Cours.objects.get(id=cours_id, enseignant_principal=profile)
        except Cours.DoesNotExist:
            return Response({"detail": "Cours non trouvé ou non assigné."}, status=404)

        # Récupérer les apprenants du cours via le parcours
        apprenants = Profile.objects.filter(
            user_type="apprenant", cursus=cours.departement.parcours.nom, is_active=True
        ).select_related("user")

        result = []
        for apprenant in apprenants:
            # Récupérer les soumissions de l'apprenant pour ce cours
            soumissions = SoumissionDevoir.objects.filter(
                devoir__cours_lie=cours, utilisateur=apprenant.user
            )

            nb_rendus = soumissions.filter(statut__in=["soumis", "corrige", "en_retard"]).count()
            nb_devoirs_total = Devoir.objects.filter(cours_lie=cours).count()
            taux_rendu = (nb_rendus / nb_devoirs_total * 100) if nb_devoirs_total > 0 else 0

            moyenne = (
                soumissions.filter(note__isnull=False).aggregate(Avg("note"))["note__avg"] or 0
            )

            dernier_rendu = soumissions.order_by("-soumis_le").first()

            nb_retards = soumissions.filter(soumis_le__gt=F("devoir__date_limite")).count()

            result.append(
                {
                    "id": apprenant.id,
                    "nom": f"{apprenant.user.first_name} {apprenant.user.last_name}".strip()
                    or apprenant.user.username,
                    "email": apprenant.user.email,
                    "taux_rendu": round(taux_rendu, 1),
                    "moyenne": round(moyenne, 1),
                    "dernier_rendu": dernier_rendu.soumis_le.isoformat() if dernier_rendu else None,
                    "nb_retards": nb_retards,
                }
            )

        return Response(result)


@extend_schema_view(
    get=extend_schema(
        summary="Détail des rendus pour un devoir ou un cours",
        description=(
            "Retourne les détails des soumissions de devoir pour un devoir "
            "précis (`devoir_id`) ou tous les devoirs d'un cours (`cours_id`), "
            "de l'enseignant principal connecté. L'un des deux paramètres est "
            "requis."
        ),
        tags=["formation"],
        parameters=[
            OpenApiParameter(
                "devoir_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Id du devoir (alternative à cours_id).",
            ),
            OpenApiParameter(
                "cours_id",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Id du cours (alternative à devoir_id).",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class PrincipalRendusDevoirsAPIView(APIView):
    """
    GET /api/principal/rendus_devoirs/
    Query param: ?devoir_id=123 (ou ?cours_id=123)
    Retourne les détails des rendus pour un devoir ou un cours.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_principal":
            return Response({"detail": "Accès réservé aux enseignants principaux."}, status=403)

        devoir_id = request.query_params.get("devoir_id")
        cours_id = request.query_params.get("cours_id")

        if not devoir_id and not cours_id:
            return Response({"detail": "devoir_id ou cours_id requis."}, status=400)

        soumissions = SoumissionDevoir.objects.all()

        if devoir_id:
            try:
                devoir = Devoir.objects.get(id=devoir_id, cours_lie__enseignant_principal=profile)
                soumissions = soumissions.filter(devoir=devoir)
            except Devoir.DoesNotExist:
                return Response({"detail": "Devoir non trouvé."}, status=404)
        elif cours_id:
            try:
                cours = Cours.objects.get(id=cours_id, enseignant_principal=profile)
                soumissions = soumissions.filter(devoir__cours_lie=cours)
            except Cours.DoesNotExist:
                return Response({"detail": "Cours non trouvé."}, status=404)

        result = []
        for s in soumissions.select_related("utilisateur", "devoir"):
            result.append(
                {
                    "id": s.id,
                    "apprenant": f"{s.utilisateur.first_name} {s.utilisateur.last_name}".strip()
                    or s.utilisateur.username,
                    "devoir": s.devoir.titre,
                    "date_rendu": s.soumis_le.isoformat() if s.soumis_le else None,
                    "note": s.note,
                    "est_en_retard": s.est_en_retard,
                    "statut": s.statut,
                }
            )

        return Response({"rendus": result, "total": len(result)})


@extend_schema_view(
    get=extend_schema(
        summary="Statistiques globales d'un enseignant administrateur",
        description=(
            "Retourne le nombre de départements, cours et leçons administrés "
            "par un enseignant_admin donné. Accessible uniquement à "
            "l'enseignant_admin concerné lui-même ou à l'administrateur "
            "général."
        ),
        tags=["formation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class EnseignantAdminStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        admin_user = get_object_or_404(User, pk=pk, user_type="enseignant_admin")

        # ── Audit d'appartenance ──────────────────────────────────────
        # IsAuthenticated seul laissait n'importe quel utilisateur connecté
        # (même un apprenant) consulter les stats de n'importe quel
        # enseignant_admin en changeant `pk`. Seuls l'admin général et
        # l'enseignant_admin concerné lui-même y ont droit.
        profile = getattr(request.user, "profile", None)
        est_lui_meme = request.user.pk == admin_user.pk
        est_admin_general = bool(profile and profile.user_type == "admin")
        if not (est_lui_meme or est_admin_general):
            return Response(
                {"error": "Vous n'avez pas accès à ces statistiques."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # départements où le parcours est administré par admin_user
        departements_count = Departement.objects.filter(parcours__admin=admin_user).count()

        # cours et leçons reliés aux parcours adminés par admin_user
        cours_count = Cours.objects.filter(departement__parcours__admin=admin_user).count()
        lecons_count = Lecon.objects.filter(cours__departement__parcours__admin=admin_user).count()

        stats = {"departements": departements_count, "cours": cours_count, "lecons": lecons_count}
        return Response(stats, status=status.HTTP_200_OK)


@extend_schema(
    summary="Lister les cours de l'enseignant principal connecté",
    description=(
        "Retourne la liste complète (non paginée) des cours dont l'utilisateur "
        "connecté est enseignant principal, avec département et enseignants "
        "secondaires imbriqués. Réservé aux profils de type "
        "'enseignant_principal'."
    ),
    tags=["formation"],
    responses={200: OpenApiTypes.OBJECT},
    examples=[*ERREURS_COURANTES],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def enseignant_principal_cours(request):
    """
    GET /api/enseignant_principal/cours/
    Retourne la liste des cours de l'enseignant principal connecté.
    """
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        return Response({"detail": "Profil introuvable."}, status=404)

    if profile.user_type != "enseignant_principal":
        return Response(
            {"detail": "Accès réservé aux enseignants principaux."},
            status=status.HTTP_403_FORBIDDEN,
        )

    cours = (
        Cours.objects.filter(enseignant_principal=profile)
        .select_related("departement", "enseignant_principal__user")
        .prefetch_related("enseignants__user")
    )

    data = []
    for c in cours:
        enseignants_data = []
        for e in c.enseignants.all():
            enseignants_data.append(
                {
                    "id": e.id,
                    "username": e.user.username,
                    "email": e.user.email,
                    "user": {
                        "username": e.user.username,
                        "email": e.user.email,
                    },
                }
            )

        data.append(
            {
                "id": c.id,
                "titre": c.titre,
                "niveau": c.niveau,
                "description_brief": c.description_brief,
                "color_code": c.color_code,
                "icon_name": c.icon_name,
                "nb_lecons": c.nb_lecons,
                "nb_devoirs": c.nb_devoirs,
                "nb_apprenants": c.nb_apprenants,
                "departement": (
                    {
                        "id": c.departement.id,
                        "nom": c.departement.nom,
                    }
                    if c.departement
                    else None
                ),
                "enseignant_principal": (
                    {
                        "id": c.enseignant_principal.id,
                        "nom": f"{c.enseignant_principal.user.first_name} {c.enseignant_principal.user.last_name}".strip()
                        or c.enseignant_principal.user.username,
                        "username": c.enseignant_principal.user.username,
                    }
                    if c.enseignant_principal
                    else None
                ),
                "enseignants": enseignants_data,
            }
        )

    return Response(data, status=status.HTTP_200_OK)
