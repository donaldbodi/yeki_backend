from django.db.models import Avg

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from apps.accounts.models import Profile
from apps.accounts.services import _nom_profil
from apps.formation.models import Parcours, Departement, Cours, Lecon
from apps.formation.serializers import ParcoursSerializer, DepartementSerializer, CoursSerializer

from drf_spectacular.utils import extend_schema, extend_schema_view
from drf_spectacular.types import OpenApiTypes
from apps.core.schema_examples import ERREURS_COURANTES


@extend_schema_view(
    get=extend_schema(
        summary="Tableau de bord de l'administrateur général",
        description=(
            "Retourne le tableau de bord complet réservé au profil `admin` : "
            "statistiques globales (nb_parcours, nb_departements, nb_cours, "
            "nb_apprenants, nb_enseignants, nb_lecons), la liste des parcours "
            "et des départements avec leurs compteurs, le top 10 des "
            "enseignants par score moyen, et la liste complète des enseignants."
        ),
        tags=["accounts"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class AdminGeneralDashboardView(APIView):
    """
    GET /api/admin-general/dashboard/
    Dashboard complet pour l'administrateur général avec :
    - Stats globales
    - Liste des parcours
    - Liste des départements
    - Top enseignants
    - Liste complète des enseignants (avec filtres)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "admin":
            return Response({"detail": "Accès réservé à l'administrateur général."}, status=403)

        # Parcours
        parcours_qs = Parcours.objects.prefetch_related("departements__cours", "admin__user").all()

        parcours_data = []
        for p in parcours_qs:
            depts = p.departements.all()
            nb_depts = depts.count()
            nb_app = 0
            nb_cours = 0

            for d in depts:
                for c in d.cours.all():
                    nb_app += c.nb_apprenants
                    nb_cours += 1

            admin_data = None
            if p.admin:
                admin_data = {
                    "id": p.admin.id,
                    "nom": _nom_profil(p.admin),
                    "username": p.admin.user.username,
                    "email": p.admin.user.email,
                    "user_type": p.admin.user_type,
                }

            parcours_data.append(
                {
                    "id": p.id,
                    "nom": p.nom,
                    "type_parcours": p.type_parcours,
                    "nb_departements": nb_depts,
                    "nb_apprenants": nb_app,
                    "nb_cours": nb_cours,
                    "taux_moyen": 0,
                    "enseignant_admin": admin_data,
                }
            )

        # Départements
        departements_qs = (
            Departement.objects.select_related("parcours", "cadre__user")
            .prefetch_related("cours")
            .all()
        )

        depts_data = []
        for d in departements_qs:
            nb_cours = d.cours.count()
            nb_app = 0
            for c in d.cours.all():
                nb_app += c.nb_apprenants

            depts_data.append(
                {
                    "id": d.id,
                    "nom": d.nom,
                    "parcours": d.parcours.nom if d.parcours else "",
                    "parcours_id": d.parcours.id if d.parcours else None,
                    "nb_cours": nb_cours,
                    "nb_apprenants": nb_app,
                    "taux_moyen": 0,
                    "cadre": (
                        {
                            "id": d.cadre.id,
                            "nom": _nom_profil(d.cadre),
                        }
                        if d.cadre
                        else None
                    ),
                }
            )

        # Statistiques globales
        stats = {
            "nb_parcours": Parcours.objects.count(),
            "nb_departements": Departement.objects.count(),
            "nb_cours": Cours.objects.count(),
            "nb_apprenants": Profile.objects.filter(user_type="apprenant").count(),
            "nb_enseignants": Profile.objects.filter(
                user_type__in=[
                    "enseignant_admin",
                    "enseignant_cadre",
                    "enseignant_principal",
                    "enseignant",
                ]
            ).count(),
            "nb_lecons": Lecon.objects.count(),
        }

        top_enseignants = []
        enseignants_top = (
            Profile.objects.filter(user_type__in=["enseignant_principal", "enseignant"])
            .annotate(score_moyen=Avg("cours_principal__exercices__evaluationexercice__score"))
            .order_by("-score_moyen")[:10]
        )

        for e in enseignants_top:
            if e.score_moyen:
                top_enseignants.append(
                    {
                        "id": e.id,
                        "nom": _nom_profil(e),
                        "role": e.user_type,
                        "score": round(e.score_moyen / 20 * 20, 1) if e.score_moyen else 0,
                    }
                )

        # ✅ Liste complète des enseignants (tous types, triés par date de création)
        enseignants = (
            Profile.objects.filter(
                user_type__in=[
                    "enseignant",
                    "enseignant_principal",
                    "enseignant_cadre",
                    "enseignant_admin",
                ]
            )
            .select_related("user")
            .order_by("-user__date_joined")
        )

        enseignants_data = []
        for e in enseignants:
            enseignants_data.append(
                {
                    "id": e.id,
                    "username": e.user.username,
                    "email": e.user.email,
                    "nom": _nom_profil(e),
                    "user_type": e.user_type,
                    "is_active": e.is_active,
                    "date_joined": e.user.date_joined.isoformat(),
                    "bio": e.bio or "",
                    "phone": e.phone or "",
                    "avatar": request.build_absolute_uri(e.avatar.url) if e.avatar else None,
                }
            )

        nom_complet = _nom_profil(profile)

        return Response(
            {
                "nom": nom_complet,
                "stats": stats,
                "parcours": parcours_data,
                "departements": depts_data,
                "top_enseignants": top_enseignants,
                "enseignants": enseignants_data,
            },
            status=200,
        )


@extend_schema_view(
    get=extend_schema(
        summary="Tableau de bord de l'enseignant administrateur de parcours",
        description=(
            "Retourne le tableau de bord complet réservé au profil "
            "`enseignant_admin` : les départements de son parcours (avec "
            "cadres, cours, effectifs), les cadres associés, les olympiades en "
            "attente de validation (prix_global=0, devoir non publié) et des "
            "statistiques globales. Retourne une structure vide si aucun "
            "parcours n'est encore associé à cet enseignant."
        ),
        tags=["accounts"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class EnseignantAdminDashboardView(APIView):
    """
    GET /api/enseignant/admin/dashboard/

    Dashboard complet pour l'enseignant_admin incluant :
    - Départements du parcours
    - Cadres du parcours
    - Départements (sans validation)
    - Statistiques globales
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_admin":
            return Response(
                {"detail": "Accès réservé aux enseignants administrateurs."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Récupérer le parcours de l'admin ────────────────────
        try:
            parcours_qs = Parcours.objects.prefetch_related(
                "departements__cours",
                "departements__cadre__user",
            ).get(admin=profile)
        except Parcours.DoesNotExist:
            return Response(
                {
                    "nom": _nom_profil(profile),
                    "stats": {},
                    "departements": [],
                    "cadres": [],
                    "nom_parcours": "",
                    "id_parcours": 0,
                    "type_parcours": "",
                }
            )

        # ── Départements ─────────────────────────────────────────
        departements_data = []
        cadres_dict = {}

        for dept in parcours_qs.departements.all():
            nb_cours = dept.cours.count()
            nb_app = sum(c.nb_apprenants for c in dept.cours.all())

            cadre_data = None
            if dept.cadre:
                cadre_data = {
                    "id": dept.cadre.id,
                    "nom": _nom_profil(dept.cadre),
                    "email": dept.cadre.user.email,
                }
                if dept.cadre.id not in cadres_dict:
                    cadres_dict[dept.cadre.id] = {
                        "id": dept.cadre.id,
                        "nom": cadre_data["nom"],
                        "username": dept.cadre.user.username,
                        "email": dept.cadre.user.email,
                        "nb_cours": nb_cours,
                        "nb_apprenants": nb_app,
                    }

            dept_info = {
                "id": dept.id,
                "nom": dept.nom,
                "parcours": parcours_qs.nom,
                "parcours_id": parcours_qs.id,
                "type_dept": dept.type_departement,
                "description": dept.description,
                "nb_cours": nb_cours,
                "nb_apprenants": nb_app,
                "nb_inscrits": nb_app,  # Alias pour le frontend
                "prix": dept.prix,
                "prix_presentiel": dept.prix_presentiel,
                "couleur": dept.couleur,
                "taux_moyen": 0,
                "cadre": cadre_data,
                "est_actif": dept.est_actif,
                "acces_restreint": dept.acces_restreint,
                # Champs spécifiques au type
                "est_prepa_concours": dept.est_prepa_concours,
                "est_formation_metier": dept.est_formation_metier,
                "est_formation_classique": dept.est_formation_classique,
                "nom_concours": dept.nom_concours,
                "organisme_concours": dept.organisme_concours,
                "date_limite_inscription": dept.date_limite_inscription,
                "date_examen": dept.date_examen,
                "duree_formation": dept.duree_formation,
                "mode": dept.mode,
                "certificat_delivre": dept.certificat_delivre,
                "domaine": dept.domaine,
                "ville": dept.ville,
                "est_certifiante": dept.est_certifiante,
                # ✅ Ajout du niveau_formation
                "niveau_formation": (
                    dept.niveau_formation if hasattr(dept, "niveau_formation") else None
                ),
            }
            departements_data.append(dept_info)

        # ── Stats globales ───────────────────────────────────────
        stats = {
            "nb_departements": len(departements_data),
            "nb_cours": sum(d["nb_cours"] for d in departements_data),
            "nb_apprenants": sum(d["nb_apprenants"] for d in departements_data),
            "nb_enseignants": len(cadres_dict),
        }

        return Response(
            {
                "nom": _nom_profil(profile),
                "stats": stats,
                "nom_parcours": parcours_qs.nom,
                "id_parcours": parcours_qs.id,
                "type_parcours": parcours_qs.type_parcours,
                "departements": departements_data,
                "cadres": list(cadres_dict.values()),
            }
        )


@extend_schema(
    summary="Données de tableau de bord génériques selon le rôle",
    description=(
        "Retourne des données de tableau de bord adaptées au rôle de "
        "l'utilisateur connecté : toujours `role` et `nom` ; puis, selon le "
        "rôle, `parcours` (admin, enseignant_admin), `departements` "
        "(enseignant_cadre) ou `cours` (enseignant_principal, enseignant). "
        "Renvoie 403 pour les rôles non gérés ici (ex : apprenant)."
    ),
    tags=["accounts"],
    responses={200: OpenApiTypes.OBJECT},
    examples=[*ERREURS_COURANTES],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_dashboard_data(request):
    try:
        user = request.user
        profile = Profile.objects.get(user=user)
    except Profile.DoesNotExist:
        return Response({"error": "Profil introuvable"}, status=status.HTTP_404_NOT_FOUND)

    role = getattr(profile, "user_type", None)

    data = {
        "role": role,
        "nom": f"{profile.user.first_name} {profile.user.last_name}".strip()
        or profile.user.username,
    }

    # Pas de try/except Exception ici : une erreur inattendue (requête DB en
    # échec, etc.) doit remonter à EXCEPTION_HANDLER (apps/core/exceptions.py)
    # qui la journalise avec traceback + request_id et renvoie un SERVER_ERROR
    # propre, plutôt que de fuiter le message technique `str(e)` au client
    # comme le faisait l'ancien code.
    if role == "admin":
        parcours = Parcours.objects.select_related("admin").all()
        data["parcours"] = ParcoursSerializer(parcours, many=True).data

    elif role == "enseignant_admin":
        parcours = Parcours.objects.filter(admin=profile)
        data["parcours"] = ParcoursSerializer(parcours, many=True).data

    elif role == "enseignant_cadre":
        departements = Departement.objects.filter(cadre=profile)
        data["departements"] = DepartementSerializer(departements, many=True).data

    elif role == "enseignant_principal":
        cours = Cours.objects.filter(enseignant_principal=profile)
        data["cours"] = CoursSerializer(cours, many=True).data

    elif role == "enseignant":
        cours = profile.cours_secondaires.all()
        data["cours"] = CoursSerializer(cours, many=True).data

    else:
        return Response({"error": "Rôle non géré ici."}, status=status.HTTP_403_FORBIDDEN)

    return Response(data, status=status.HTTP_200_OK)
