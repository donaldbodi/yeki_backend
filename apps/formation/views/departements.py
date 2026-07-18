import json

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status, generics
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.accounts.services import _get_profile, _nom_profil
from apps.core.exceptions import ConflictError
from apps.core.models import enregistrer_activite
from apps.core.pagination import PaginatedListMixin, YekiPageNumberPagination
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_CONFLICT,
    EXEMPLE_NOT_FOUND,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
)
from apps.formation.models import Parcours, Departement, Cours, DemandeAccesFormation
from apps.formation.serializers import DepartementSerializer, DepartementUpdateSerializer
from apps.formation.services import _progression_cours, _serialise_departement_detail


@extend_schema_view(
    post=extend_schema(
        summary="Créer un département",
        description=(
            "Crée un département enrichi selon le type du parcours parent "
            "(prépa concours, formation métier/classique, ou autre). Réservé "
            "aux profils de type 'enseignant_admin'. Accepte multipart/"
            "form-data (champ `image` optionnel)."
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={201: DepartementSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class CreerDepartementView(APIView):
    """
    POST /api/departements/creer/
    Crée un département enrichi selon le type du parcours parent.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_admin":
            return Response(
                {"detail": "Accès réservé aux enseignants administrateurs."},
                status=status.HTTP_403_FORBIDDEN,
            )

        nom = request.data.get("nom", "").strip()
        if not nom:
            return Response(
                {"detail": "Le nom du département est obligatoire."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # P2.3 (CDC §6.4/§7.4) : « periode obligatoire lors de la création »
        # — le default=6 du modèle est conservé pour ne pas casser les
        # lignes existantes, mais cette vue (le vrai chemin de création,
        # DepartementCreateSerializer n'étant câblé nulle part) l'exige
        # désormais explicitement.
        periode_brute = request.data.get("periode")
        if periode_brute in (None, ""):
            return Response(
                {"detail": "La période de classement (periode) est obligatoire."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            periode = int(periode_brute)
            if periode <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"detail": "La période de classement (periode) doit être un entier positif."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parcours_id = request.data.get("parcours_id")
        if parcours_id:
            parcours = get_object_or_404(Parcours, pk=parcours_id, admin=profile)
        else:
            parcours_qs = Parcours.objects.filter(admin=profile)
            if not parcours_qs.exists():
                return Response({"detail": "Aucun parcours ne vous est assigné."}, status=403)
            if parcours_qs.count() > 1:
                return Response({"detail": "Spécifier parcours_id."}, status=400)
            parcours = parcours_qs.first()

        def _b(key, default=False):
            v = request.data.get(key, default)
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes")
            return bool(v)

        def _i(key, default=0):
            try:
                return int(request.data.get(key, default) or default)
            except (ValueError, TypeError):
                return default

        def _s(key, default=""):
            v = request.data.get(key, default)
            return v if v else default

        # Récupérer les niveaux accessibles
        niveaux_accessibles = request.data.get("niveaux_accessibles", [])
        if isinstance(niveaux_accessibles, str):
            try:
                niveaux_accessibles = json.loads(niveaux_accessibles)
            except json.JSONDecodeError:
                niveaux_accessibles = [
                    n.strip() for n in niveaux_accessibles.split(",") if n.strip()
                ]
        elif not isinstance(niveaux_accessibles, list):
            niveaux_accessibles = []

        # === CONSTRUCTION DES CHAMPS DE BASE ===
        prix = _i("prix")
        prix_presentiel = _i("prix_presentiel")
        type_parc = parcours.type_parcours

        if type_parc == "prepa":
            est_prepa_concours = True
            est_formation_metier = False
            est_formation_classique = False
        elif type_parc == "formation":
            est_prepa_concours = False
            est_formation_metier = _b("est_formation_metier")
            est_formation_classique = _b("est_formation_classique")
            if not est_formation_metier and not est_formation_classique:
                return Response(
                    {
                        "detail": "Veuillez sélectionner au moins un type de formation (Métier ou Classique)."
                    },
                    status=400,
                )
        else:
            est_prepa_concours = False
            est_formation_metier = False
            est_formation_classique = False

        kwargs = {
            "nom": nom,
            "parcours": parcours,
            "periode": periode,
            "description": _s("description"),
            "couleur": "#2884A0",  # Couleur par défaut, retirée du formulaire
            "prix": prix,
            "prix_presentiel": prix_presentiel,
            "est_actif": True,
            "mode": _s("mode", "hybride"),
            "acces_restreint": _b("acces_restreint"),
            "niveaux_accessibles": ",".join(niveaux_accessibles) if niveaux_accessibles else "",
            "est_prepa_concours": est_prepa_concours,
            "est_formation_metier": est_formation_metier,
            "est_formation_classique": est_formation_classique,
        }

        # ✅ Ajout du champ niveau_formation pour les formations métier
        if type_parc == "formation" and est_formation_metier:
            niveau_formation = request.data.get("niveau_formation", "debutant")
            if niveau_formation not in ["debutant", "intermediaire", "avance"]:
                niveau_formation = "debutant"
            kwargs["niveau_formation"] = niveau_formation

        if request.FILES.get("image"):
            kwargs["image"] = request.FILES["image"]

        # === PARCOURS PRÉPA CONCOURS ===
        if type_parc == "prepa":
            kwargs.update(
                {
                    "nom_concours": _s("nom_concours"),
                    "organisme_concours": _s("organisme_concours"),
                    "date_limite_inscription": request.data.get("date_limite_inscription") or None,
                    "date_examen": request.data.get("date_examen") or None,
                    "arrete_ministeriel": _s("arrete_ministeriel"),
                    "places_disponibles": _i("places_disponibles") or None,
                    "debouches": _s("debouches"),
                }
            )

        # === PARCOURS FORMATION ===
        elif type_parc == "formation":
            kwargs.update(
                {
                    "duree_formation": _s("duree_formation"),
                    "mode": _s("mode", "hybride"),
                    "certificat_delivre": _s("certificat_delivre"),
                    "prerequis": _s("prerequis"),
                    "objectifs": _s("objectifs"),
                    "domaine": _s("domaine"),
                    "ville": _s("ville"),
                    "est_certifiante": _b("est_certifiante"),
                }
            )

        # === CRÉATION DU DÉPARTEMENT ===
        departement = Departement.objects.create(**kwargs)

        enregistrer_activite(
            user=request.user,
            action="department_created",
            description=f"Département {departement.nom} créé dans {parcours.nom}",
            data={
                "departement": departement.nom,
                "parcours": parcours.nom,
                "type": type_parc,
                "prix": kwargs.get("prix", 0),
            },
            objet_id=departement.id,
            objet_type="Departement",
        )

        return Response(
            DepartementSerializer(departement, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    patch=extend_schema(
        summary="Modifier un département (enseignant admin)",
        description=(
            "Modifie un département. Réservé à l'enseignant_admin du parcours "
            "auquel appartient le département."
        ),
        tags=["formation"],
        request=DepartementUpdateSerializer,
        responses={200: DepartementSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AdminUpdateDepartementView(APIView):
    """
    PATCH /api/admin/departements/<pk>/update/
    Permet à l'enseignant admin de modifier un département.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, pk):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_admin":
            return Response(
                {"detail": "Accès réservé aux enseignants administrateurs."}, status=403
            )

        departement = get_object_or_404(Departement, pk=pk)

        # Vérifier que le département appartient au parcours de l'admin
        if departement.parcours.admin != profile:
            return Response(
                {"detail": "Ce département n'appartient pas à votre parcours."}, status=403
            )

        data = request.data.copy()

        # ── Validation et nettoyage des données ──────────────────

        # Gérer les niveaux accessibles
        if "niveaux_accessibles" in data:
            niveaux = data.get("niveaux_accessibles", [])
            if isinstance(niveaux, str):
                try:
                    niveaux = json.loads(niveaux)
                except json.JSONDecodeError:
                    niveaux = [n.strip() for n in niveaux.split(",") if n.strip()]
            elif not isinstance(niveaux, list):
                niveaux = []
            # Le serializer attend une string, on convertit
            data["niveaux_accessibles"] = ",".join(niveaux) if niveaux else ""

        # Supprimer les champs qui ne sont pas dans le serializer
        # Ces champs existent dans le modèle mais pas dans le serializer
        champs_a_supprimer = ["couleur", "created_at", "image_url", "type"]
        for champ in champs_a_supprimer:
            if champ in data:
                data.pop(champ)

        # Si le type de parcours est 'formation', valider les champs spécifiques
        if departement.parcours.type_parcours == "formation":
            # Si est_formation_metier ou est_formation_classique sont présents
            if "est_formation_metier" not in data and "est_formation_classique" not in data:
                # Conserver les valeurs existantes
                pass
            else:
                est_metier = data.get("est_formation_metier", departement.est_formation_metier)
                est_classique = data.get(
                    "est_formation_classique", departement.est_formation_classique
                )
                if not est_metier and not est_classique:
                    return Response(
                        {
                            "detail": "Veuillez sélectionner au moins un type de formation (Métier ou Classique)"
                        },
                        status=400,
                    )

        # ── Utiliser le serializer ────────────────────────────────
        serializer = DepartementUpdateSerializer(
            departement, data=data, partial=True, context={"request": request}
        )

        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        enregistrer_activite(
            user=request.user,
            action="department_modified",
            description=f"Département {updated.nom} modifié",
            objet_id=updated.id,
            objet_type="Departement",
        )
        return Response(
            DepartementSerializer(updated, context={"request": request}).data, status=200
        )


# TODO(audit): vue CONFIRMÉE CASSÉE (docs/AUDIT_BACKEND.md §5.2) —
# compare `user_type` sur `User` (django.contrib.auth) au lieu de
# `Profile` : `User` n'a pas cet attribut, la fonctionnalité de
# changement de cadre échoue à 100%. Déplacée telle quelle
# ("déplacer, ne pas réécrire"), correction à faire dans une tâche
# séparée après confirmation.
@extend_schema_view(
    get=extend_schema(
        summary="Consulter un département (détail)",
        description="Retourne le détail d'un département identifié par son id.",
        tags=["formation"],
        responses={200: DepartementSerializer},
        examples=[*ERREURS_COURANTES],
    ),
    patch=extend_schema(
        summary="Modifier un département (nom, enseignant cadre)",
        description=(
            "Modifie le nom et/ou l'enseignant cadre (`enseignant_cadre`) d'un "
            "département. Connue pour être cassée (comparaison de user_type "
            "sur le mauvais modèle) — voir docs/AUDIT_BACKEND.md §5.2."
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: DepartementSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class DepartementUpdateView(generics.UpdateAPIView, generics.RetrieveAPIView):
    queryset = Departement.objects.select_related("parcours", "cadre")
    serializer_class = DepartementSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_target_parcours(self):
        dep = self.get_object()
        return dep.parcours

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        dep = self.get_object()
        payload = request.data

        if "enseignant_cadre" in payload:
            cadre_id = payload.get("enseignant_cadre")
            if cadre_id in [None, "", "null"]:
                dep.cadre = None
            else:
                from django.contrib.auth import get_user_model

                User = get_user_model()
                cadre = get_object_or_404(User, pk=cadre_id)
                if getattr(cadre, "user_type", None) != "enseignant_cadre":
                    return Response(
                        {"detail": "L'utilisateur choisi n'est pas un enseignant_cadre."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                dep.cadre = cadre

        if "nom" in payload:
            nom = (payload.get("nom") or "").strip()
            if not nom:
                return Response(
                    {"detail": "Le nom ne peut pas être vide."}, status=status.HTTP_400_BAD_REQUEST
                )
            dep.nom = nom

        dep.save()
        return Response(DepartementSerializer(dep).data, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        summary="Vérifier l'accès de l'apprenant à un département",
        description=(
            "Indique si l'apprenant connecté a accès à un département : accès "
            "libre, autorisé explicitement, ou statut de sa demande d'accès "
            "(en_attente / refusee / non_demandee). Réservé aux profils de "
            "type 'apprenant'."
        ),
        tags=["formation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class VerifierAccesDepartementView(APIView):
    """
    GET /api/apprenant/departement/<pk>/acces/
    Vérifie si l'apprenant a accès au département.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "apprenant":
            return Response({"detail": "Accès réservé aux apprenants."}, status=403)

        departement = get_object_or_404(Departement, pk=pk)

        # Si pas d'accès restreint, tout le monde a accès
        if not departement.acces_restreint:
            return Response(
                {"acces": True, "statut": "libre", "message": "Cette formation est en accès libre."}
            )

        # Vérifier si l'apprenant est autorisé
        if request.user in departement.apprenants_autorises.all():
            return Response(
                {
                    "acces": True,
                    "statut": "autorise",
                    "message": "Vous avez accès à cette formation.",
                }
            )

        # Vérifier si une demande existe
        try:
            demande = DemandeAccesFormation.objects.get(
                apprenant=request.user, departement=departement
            )
            return Response(
                {
                    "acces": False,
                    "statut": demande.statut,
                    "message": (
                        "Votre demande d'accès est en attente de traitement."
                        if demande.statut == "en_attente"
                        else "Votre demande d'accès a été refusée. Contactez le service client."
                    ),
                }
            )
        except DemandeAccesFormation.DoesNotExist:
            return Response(
                {
                    "acces": False,
                    "statut": "non_demandee",
                    "message": "Vous devez demander l'accès à cette formation.",
                }
            )


@extend_schema_view(
    patch=extend_schema(
        summary="Assigner un enseignant cadre à un département",
        description=(
            "Nomme l'enseignant cadre d'un département. Réservé à "
            "l'enseignant_admin du parcours auquel appartient le département. "
            'Corps attendu : `{"cadre_id": <int>}`.'
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class ChangerCadreDepartementView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_admin":
            return Response(
                {"detail": "Accès réservé aux enseignants administrateurs."},
                status=status.HTTP_403_FORBIDDEN,
            )

        departement = get_object_or_404(Departement, pk=departement_id)

        # SÉCURITÉ : vérifier que ce département appartient à un parcours géré
        if departement.parcours.admin != profile:
            return Response(
                {"detail": "Ce département n'appartient pas à votre parcours."},
                status=status.HTTP_403_FORBIDDEN,
            )

        cadre_id = request.data.get("cadre_id")
        if not cadre_id:
            return Response({"detail": "cadre_id est requis."}, status=status.HTTP_400_BAD_REQUEST)

        cadre = get_object_or_404(Profile, pk=cadre_id)
        if cadre.user_type != "enseignant_cadre":
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant cadre."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        departement.cadre = cadre
        departement.save()
        enregistrer_activite(
            user=request.user,
            action="cadre_assigned",
            description=f"{cadre.user.get_full_name() or cadre.user.username} nommé cadre du département « {departement.nom} »",
            data={
                "cadre": cadre.user.get_full_name() or cadre.user.username,
                "departement": departement.nom,
                "parcours": departement.parcours.nom if departement.parcours else "",
            },
            objet_id=departement.id,
            objet_type="Departement",
        )
        return Response(
            {"detail": "Enseignant cadre mis à jour avec succès."}, status=status.HTTP_200_OK
        )


@extend_schema_view(
    get=extend_schema(
        summary="Détail d'un département pour l'enseignant cadre",
        description=(
            "Retourne les détails complets d'un département (dont il est le "
            "cadre) avec la liste de ses cours. Réservé aux profils de type "
            "'enseignant_cadre'."
        ),
        tags=["formation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class EnseignantCadreDepartementDetailView(APIView):
    """
    GET /api/enseignant/cadre/departement/<departement_id>/

    Retourne les détails complets d'un département pour l'enseignant cadre.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_cadre":
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=status.HTTP_403_FORBIDDEN,
            )

        departement = get_object_or_404(Departement, pk=departement_id, cadre=profile)

        cours_qs = Cours.objects.filter(departement=departement).select_related(
            "enseignant_principal__user"
        )

        cours_data = []
        for c in cours_qs:
            ep_data = None
            if c.enseignant_principal:
                ep = c.enseignant_principal
                ep_data = {
                    "id": ep.id,
                    "nom": f"{ep.user.first_name} {ep.user.last_name}".strip() or ep.user.username,
                }
            cours_data.append(
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
                    "enseignant_principal": ep_data,
                }
            )

        return Response(
            {
                "id": departement.id,
                "nom": departement.nom,
                "description": departement.description,
                "parcours": departement.parcours.nom if departement.parcours else "",
                "couleur": departement.couleur,
                "prix": departement.prix,
                "type_departement": departement.type_departement,
                "cours": cours_data,
                "nb_cours": cours_qs.count(),
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    patch=extend_schema(
        summary="Modifier un département (enseignant cadre)",
        description=(
            "Met à jour nom, description, couleur, prix et/ou est_actif d'un "
            "département dont l'utilisateur connecté est le cadre. Réservé "
            "aux profils de type 'enseignant_cadre'."
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class EnseignantCadreDepartementUpdateView(APIView):
    """
    PATCH /api/enseignant/cadre/departement/<departement_id>/update/

    Met à jour les informations d'un département.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_cadre":
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=status.HTTP_403_FORBIDDEN,
            )

        departement = get_object_or_404(Departement, pk=departement_id, cadre=profile)

        data = request.data
        updates = {}

        if "nom" in data:
            updates["nom"] = data["nom"].strip()
        if "description" in data:
            updates["description"] = data["description"].strip()
        if "couleur" in data:
            updates["couleur"] = data["couleur"]
        if "prix" in data:
            updates["prix"] = int(data["prix"])
        if "est_actif" in data:
            updates["est_actif"] = data["est_actif"]

        if updates:
            for key, value in updates.items():
                setattr(departement, key, value)
            departement.save()

        return Response(
            {
                "detail": "Département mis à jour avec succès.",
                "departement": {
                    "id": departement.id,
                    "nom": departement.nom,
                    "description": departement.description,
                    "couleur": departement.couleur,
                    "prix": departement.prix,
                    "est_actif": departement.est_actif,
                },
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    summary="Lister les départements d'un parcours (public)",
    description=(
        "Retourne, paginés, les départements d'un parcours donné. Vue "
        "publique consultée depuis le formulaire d'inscription, avant "
        "connexion."
    ),
    tags=["formation"],
    parameters=[*PARAMS_PAGINATION],
    responses={200: DepartementSerializer(many=True)},
    examples=[EXEMPLE_PAGINATION, EXEMPLE_NOT_FOUND],
)
@api_view(["GET"])
@permission_classes([AllowAny])  # public : consulté depuis le formulaire d'inscription
# (register_page.dart → _fetchDepartements), avant connexion
def departements_par_parcours(request, parcours_id):
    parcours = get_object_or_404(Parcours, pk=parcours_id)
    deps = Departement.objects.filter(parcours=parcours).select_related("cadre")
    paginator = YekiPageNumberPagination()
    page = paginator.paginate_queryset(deps, request)
    data = DepartementSerializer(page, many=True).data
    return paginator.get_paginated_response(data)


@extend_schema_view(
    post=extend_schema(
        summary="Demander l'accès à une formation à accès restreint",
        description=(
            "L'apprenant connecté demande l'accès à une formation à accès "
            "restreint. Une demande déjà en attente ou déjà acceptée déclenche "
            "un conflit (409) ; une demande refusée peut être renvoyée (elle "
            "repasse en_attente). Réservé aux profils de type 'apprenant'. "
            'Corps optionnel : `{"message": "..."}`.'
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_CONFLICT, *ERREURS_ECRITURE],
    ),
)
class DemandeAccesFormationView(APIView):
    """
    POST /api/departements/<departement_id>/demander-acces/
    L'apprenant demande l'accès à une formation à accès restreint.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "apprenant":
            return Response(
                {"detail": "Seuls les apprenants peuvent demander l'accès."}, status=403
            )

        departement = get_object_or_404(Departement, pk=departement_id)

        if not departement.acces_restreint:
            return Response({"detail": "Cette formation est en accès libre."}, status=400)

        message = request.data.get("message", "").strip()

        demande, created = DemandeAccesFormation.objects.get_or_create(
            apprenant=request.user, departement=departement, defaults={"message": message}
        )

        if not created:
            if demande.statut == "en_attente":
                raise ConflictError("Votre demande est déjà en attente de traitement.")
            elif demande.statut == "acceptee":
                raise ConflictError("Vous avez déjà accès à cette formation.")
            elif demande.statut == "refusee":
                # Permettre de refaire une demande après refus
                demande.statut = "en_attente"
                demande.message = message or demande.message
                demande.traite_le = None
                demande.reponse_cadre = ""
                demande.save()
                return Response(
                    {"detail": "Votre nouvelle demande a été envoyée.", "statut": "en_attente"}
                )

        return Response(
            {"detail": "Votre demande d'accès a été envoyée au cadre.", "statut": "en_attente"},
            status=201,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Traiter une demande d'accès à un département",
        description=(
            "Accepte ou refuse une demande d'accès d'un apprenant à un "
            "département à accès restreint. Réservé à l'enseignant cadre du "
            "département. Corps attendu : "
            '`{"action": "accepter"|"refuser", "reponse": "..."}`.'
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class GererDemandeAccesView(APIView):
    """
    POST /api/departements/<departement_id>/demandes/<demande_id>/traiter/
    Body: { "action": "accepter" | "refuser", "reponse": "..." }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, departement_id, demande_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_cadre":
            return Response(
                {"detail": "Seuls les enseignants cadres peuvent traiter les demandes."}, status=403
            )

        departement = get_object_or_404(Departement, pk=departement_id, cadre=profile)
        demande = get_object_or_404(DemandeAccesFormation, pk=demande_id, departement=departement)

        action = request.data.get("action", "").lower()
        reponse = request.data.get("reponse", "").strip()

        if action not in ["accepter", "refuser"]:
            return Response({"detail": "L'action doit être 'accepter' ou 'refuser'."}, status=400)

        if action == "accepter":
            demande.statut = "acceptee"
            departement.apprenants_autorises.add(demande.apprenant)
        else:
            demande.statut = "refusee"

        demande.reponse_cadre = reponse
        demande.traite_le = timezone.now()
        demande.save()

        # Optionnel: envoyer une notification à l'apprenant
        # Notification.objects.create(...)

        return Response(
            {"detail": f"Demande {action}e avec succès.", "statut": demande.statut}, status=200
        )


@extend_schema_view(
    get=extend_schema(
        summary="Lister les demandes d'accès à un département",
        description=(
            "Retourne, paginées, les demandes d'accès à un département filtrées "
            "par statut (`en_attente` par défaut, `acceptee`, `refusee`). "
            "Réservé à l'enseignant cadre du département."
        ),
        tags=["formation"],
        parameters=[
            *PARAMS_PAGINATION,
            OpenApiParameter(
                "statut",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre par statut : en_attente (défaut), acceptee, refusee.",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class DemandesAccesDepartementView(PaginatedListMixin, APIView):
    """
    GET /api/departements/<departement_id>/demandes/
    Retourne les demandes d'accès pour un département.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, departement_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_cadre":
            return Response({"detail": "Accès réservé aux enseignants cadres."}, status=403)

        departement = get_object_or_404(Departement, pk=departement_id, cadre=profile)

        statut = request.query_params.get("statut", "en_attente")
        if statut not in ["en_attente", "acceptee", "refusee"]:
            statut = "en_attente"

        demandes = (
            DemandeAccesFormation.objects.filter(departement=departement, statut=statut)
            .select_related("apprenant")
            .order_by("-cree_le")
        )

        page = self.paginate_queryset(demandes)
        data = [
            {
                "id": d.id,
                "apprenant_id": d.apprenant.id,
                "apprenant_nom": f"{d.apprenant.first_name} {d.apprenant.last_name}".strip()
                or d.apprenant.username,
                "apprenant_username": d.apprenant.username,
                "apprenant_email": d.apprenant.email,
                "message": d.message,
                "reponse_cadre": d.reponse_cadre,
                "cree_le": d.cree_le.isoformat(),
                "traite_le": d.traite_le.isoformat() if d.traite_le else None,
            }
            for d in page
        ]

        return self.get_paginated_response(data)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les apprenants d'un département",
        description=(
            "Retourne, paginés, les apprenants inscrits au parcours d'un "
            "département. Réservé à l'enseignant cadre de ce département."
        ),
        tags=["formation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class ApprenantsParDepartementView(PaginatedListMixin, APIView):
    """GET /api/departements/<departement_id>/apprenants/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, departement_id):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != "enseignant_cadre":
            return Response({"detail": "Accès réservé aux enseignants cadres."}, status=403)

        departement = get_object_or_404(Departement, pk=departement_id)

        # Vérifier que le cadre gère ce département
        if departement.cadre != profile:
            return Response({"detail": "Vous n'êtes pas le cadre de ce département."}, status=403)

        # Récupérer les apprenants du parcours
        apprenants = Profile.objects.filter(
            user_type="apprenant", cursus=departement.parcours.nom, is_active=True
        ).select_related("user")

        page = self.paginate_queryset(apprenants)
        data = [
            {
                "id": a.id,
                "nom": _nom_profil(a),
                "username": a.user.username,
                "email": a.user.email,
            }
            for a in page
        ]

        return self.get_paginated_response(data)


@extend_schema_view(
    get=extend_schema(
        summary="Détail d'un département pour l'apprenant",
        description="Retourne le détail complet d'un département (cours inclus) avec la progression de l'apprenant connecté.",
        tags=["formation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_NOT_FOUND, *ERREURS_COURANTES],
    ),
)
class ApprenantDepartementDetailView(APIView):
    """GET /api/apprenant/departement/<pk>/ — detail complet"""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        dept = get_object_or_404(Departement, pk=pk)
        cours_qs = Cours.objects.filter(departement=dept).select_related(
            "enseignant_principal__user"
        )
        prog_map = _progression_cours(request.user, cours_qs)
        return Response(
            _serialise_departement_detail(
                dept, prog_map=prog_map, include_cours=True, user=request.user
            )
        )
