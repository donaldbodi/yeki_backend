from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework import status, generics
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated

from drf_spectacular.utils import extend_schema, extend_schema_view
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.accounts.services import _get_profile
from apps.core.models import enregistrer_activite
from apps.core.pagination import PaginatedListMixin, YekiPageNumberPagination
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_NOT_FOUND,
    EXEMPLE_PAGINATION,
    PARAMS_PAGINATION,
)
from apps.formation.models import (
    Parcours,
    Departement,
    Cours,
    Module,
    Lecon,
    LeconLike,
    ProgressionLecon,
    COURSE_COLOR_PALETTE,
)
from apps.formation.serializers import (
    CoursSerializer,
    CoursCreateSerializer,
    ModuleAvecLeconsSerializer,
    LeconCreateSerializer,
    ModuleCreateSerializer,
    ModuleUpdateSerializer,
    LeconUpdateSerializer,
    LeconSerializer,
)
from apps.formation.services import _progression_cours


@extend_schema_view(
    get=extend_schema(
        summary="Lister les niveaux scolaires existants",
        description=(
            "Retourne la liste triée des valeurs de niveau (ex : '6e', 'Tle C') "
            "déjà utilisées par au moins un cours en base, sans doublon. "
            "Réponse : liste JSON de chaînes de caractères."
        ),
        tags=["formation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class ListeNiveauxView(APIView):
    """
    GET /api/niveaux/
    Retourne la liste des niveaux uniques déjà enregistrés en base.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Récupérer tous les niveaux distincts depuis les cours existants
        niveaux = Cours.objects.values_list("niveau", flat=True).distinct().order_by("niveau")

        resultats = list(niveaux)

        return Response(sorted(resultats))


@extend_schema_view(
    get=extend_schema(
        summary="Récupérer la palette officielle des couleurs de cours",
        description=(
            "Retourne la liste des 12 couleurs (codes hexadécimaux) proposées à "
            "l'enseignant lors de la création ou modification d'un cours. Le "
            "frontend ne doit jamais générer de couleur lui-même : il doit "
            "utiliser strictement cette liste."
        ),
        tags=["formation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class PaletteCouleursCoursView(APIView):
    """
    GET /api/cours/palette-couleurs/
    Retourne la palette officielle des 12 couleurs de cours, proposée à
    l'enseignant lors de la création ou modification d'un cours.
    Le frontend ne doit JAMAIS générer de couleur lui-même : il consomme
    strictement cette liste (voir COURSE_COLOR_PALETTE dans apps/formation/models.py).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(COURSE_COLOR_PALETTE)


@extend_schema_view(
    post=extend_schema(
        summary="Ajouter un enseignant secondaire à un cours",
        description=(
            "Ajoute un enseignant secondaire à un cours. Réservé à l'enseignant "
            'principal du cours. Corps attendu : `{"enseignant_id": <int>}`.'
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: CoursSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AddEnseignantSecondaireView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, cours_id):
        # 1️⃣ Récupération du cours
        cours = get_object_or_404(Cours, pk=cours_id)

        # 2️⃣ Profil du demandeur
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            raise PermissionDenied("Profil utilisateur introuvable.")

        # 3️⃣ Vérification : enseignant principal du cours
        if cours.enseignant_principal != profile:
            raise PermissionDenied("Action réservée à l’enseignant principal de ce cours.")

        # 4️⃣ Récupération de l'enseignant secondaire
        enseignant_id = request.data.get("enseignant_id")
        if not enseignant_id:
            return Response(
                {"detail": "L'id de l'enseignant est requis."}, status=status.HTTP_400_BAD_REQUEST
            )

        enseignant = get_object_or_404(Profile, pk=enseignant_id)

        # 5️⃣ Vérification du rôle
        if enseignant.user_type != "enseignant":
            return Response(
                {"detail": "L'utilisateur choisi n'est pas un enseignant secondaire."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 6️⃣ Vérification doublon
        if cours.enseignants.filter(pk=enseignant.pk).exists():
            return Response(
                {"detail": "Enseignant déjà présent dans ce cours."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 7️⃣ Ajout via la logique métier
        cours.enseignants.add(enseignant)

        enregistrer_activite(
            user=request.user,
            action="secondary_added",
            description=f"{enseignant.user.get_full_name() or enseignant.user.username} ajouté comme enseignant secondaire dans « {cours.titre} »",
            data={
                "enseignant": enseignant.user.get_full_name() or enseignant.user.username,
                "cours": cours.titre,
            },
            objet_id=cours.id,
            objet_type="Cours",
        )

        return Response(CoursSerializer(cours).data, status=status.HTTP_200_OK)


@extend_schema_view(
    post=extend_schema(
        summary="Retirer un enseignant secondaire d'un cours",
        description=(
            "Retire un enseignant secondaire d'un cours. Réservé à l'enseignant "
            'principal du cours. Corps attendu : `{"enseignant_id": <int>}`.'
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: CoursSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class RemoveEnseignantSecondaireView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)
        profile = request.user.profile
        if cours.enseignant_principal != profile:
            raise PermissionDenied("Action réservée à l’enseignant principal du cours.")

        enseignant_id = request.data.get("enseignant_id")
        if not enseignant_id:
            return Response(
                {"detail": "L'id de l'enseignant est requis."}, status=status.HTTP_400_BAD_REQUEST
            )

        enseignant = get_object_or_404(Profile, pk=enseignant_id, user_type="enseignant")
        if enseignant not in cours.enseignants.all():
            return Response(
                {"detail": "Enseignant non présent dans le cours."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cours.enseignants.remove(enseignant)
        cours.save()
        return Response(CoursSerializer(cours).data, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les cours du cursus de l'apprenant connecté",
        description=(
            "Retourne, paginés, les cours du niveau exact de l'apprenant connecté "
            "dans son cursus (profil.cursus), avec la progression de l'apprenant "
            "pour chacun. Réservé aux profils de type 'apprenant'. Chaque élément "
            "contient : id, title, description, enseignant_principal, lessons, "
            "assignments, icon, color, progression, niveau."
        ),
        tags=["formation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class ApprenantCursusAPIView(PaginatedListMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_profile(request.user)
        if profile.user_type != "apprenant":
            return Response({"detail": "Accès réservé aux apprenants"}, status=403)

        if not profile.cursus:
            return self.get_paginated_response(self.paginate_queryset([]))

        # Récupérer le parcours du cursus
        try:
            parcours = Parcours.objects.get(nom=profile.cursus, type_parcours="cursus")
        except Parcours.DoesNotExist:
            return self.get_paginated_response(self.paginate_queryset([]))

        # Utiliser le niveau enregistré dans le profil
        niveau_apprenant = profile.niveau or ""

        # Récupérer les départements du cursus
        depts = Departement.objects.filter(parcours=parcours, est_actif=True)

        # Récupérer les cours du niveau EXACT de l'apprenant (pas inférieur, pas supérieur)
        cours_qs = Cours.objects.filter(
            departement__in=depts, niveau=niveau_apprenant  # ← Filtre exact sur le niveau
        ).select_related("enseignant_principal__user")

        page = self.paginate_queryset(cours_qs)

        # Calculer les progressions (uniquement pour la page retournée)
        prog_map = _progression_cours(request.user, page)

        result = []
        for c in page:
            ep_nom = "—"
            if c.enseignant_principal:
                ep = c.enseignant_principal
                ep_nom = f"{ep.user.first_name} {ep.user.last_name}".strip() or ep.user.username

            result.append(
                {
                    "id": c.id,
                    "title": c.titre,
                    "description": c.description_brief or "",
                    "enseignant_principal": ep_nom,
                    "lessons": c.nb_lecons,
                    "assignments": c.nb_devoirs,
                    "icon": c.icon_name or "school",
                    "color": c.color_code or "#2884A0",
                    "progression": prog_map.get(c.id, 0.0),
                    "niveau": c.niveau,
                }
            )

        return self.get_paginated_response(result)


@extend_schema_view(
    post=extend_schema(
        summary="Créer un cours",
        description=(
            "Crée un nouveau cours dans un département. La logique de validation "
            "et de création est déléguée à `CoursCreateSerializer`."
        ),
        tags=["formation"],
        request=CoursCreateSerializer,
        responses={201: CoursSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class CoursCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        # Ici, la logique de création est déléguée au serializer ou au manager métier
        serializer = CoursCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        cours = serializer.save()
        enregistrer_activite(
            user=request.user,
            action="course_created",
            description=f"Cours « {cours.titre} » créé dans le département {cours.departement.nom}",
            data={
                "titre": cours.titre,
                "niveau": cours.niveau,
                "departement": cours.departement.nom,
            },
            objet_id=cours.id,
            objet_type="Cours",
        )
        return Response(CoursSerializer(cours).data, status=status.HTTP_201_CREATED)


# TODO(audit): vue orpheline, non routée (docs/AUDIT_BACKEND.md §2.2) —
# remplacée en pratique par ModifierCoursParCadreView. Conservée telle
# quelle (déplacement sans réécriture), à archiver/supprimer dans une
# tâche de nettoyage ultérieure si confirmé inutile.
@extend_schema_view(
    get=extend_schema(
        summary="Consulter un cours (détail)",
        description="Retourne le détail d'un cours identifié par son id.",
        tags=["formation"],
        responses={200: CoursSerializer},
        examples=[*ERREURS_COURANTES],
    ),
    patch=extend_schema(
        summary="Modifier un cours",
        description=(
            "Modifie un cours. Un enseignant principal peut modifier titre, "
            "niveau, description_brief, color_code, icon_name. Un enseignant "
            "cadre peut en plus modifier enseignant_principal et departement."
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: CoursSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class CoursUpdateView(generics.RetrieveAPIView, generics.UpdateAPIView):
    queryset = Cours.objects.select_related("departement", "enseignant_principal")
    serializer_class = CoursSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        cours = self.get_object()
        profile = request.user.profile
        payload = request.data

        # 🔐 Permissions
        # TODO(bug pré-existant, non corrigé — "déplacer, ne pas réécrire") :
        # `allowed_fields` (les deux branches, repéré en P1.6 via ruff F841)
        # n'est jamais consulté plus bas — chaque champ est appliqué via un
        # `if 'x' in payload:` indépendant, sans vérifier `allowed_fields`.
        # La restriction de champs pour `enseignant_principal` est donc
        # entièrement non appliquée (un enseignant_principal peut en
        # pratique modifier n'importe quel champ du payload, pas seulement
        # ceux listés ici).
        if profile.user_type == "enseignant_principal":
            allowed_fields = {
                "titre",
                "niveau",
                "description_brief",
                "color_code",
                "icon_name",
            }
        elif profile.user_type == "enseignant_cadre":
            allowed_fields = "__all__"  # noqa: F841
        else:
            raise PermissionDenied("Accès interdit.")

        # 📝 Titre
        if "titre" in payload:
            cours.titre = payload["titre"].strip()

        # 🎓 Niveau
        if "niveau" in payload:
            cours.niveau = payload["niveau"].strip()

        # 🧾 Description courte
        if "description_brief" in payload:
            cours.description_brief = payload["description_brief"]

        # 🎨 Couleur
        if "color_code" in payload:
            cours.color_code = payload["color_code"]

        # 🧩 Icône
        if "icon_name" in payload:
            cours.icon_name = payload["icon_name"]

        # 👨‍🏫 Enseignant principal (cadre seulement)
        if profile.user_type == "enseignant_cadre" and "enseignant_principal" in payload:
            principal_id = payload["enseignant_principal"]
            if principal_id:
                principal = get_object_or_404(
                    Profile, pk=principal_id, user_type="enseignant_principal"
                )
                cours.enseignant_principal = principal
            else:
                cours.enseignant_principal = None

        # 🏫 Département (cadre seulement)
        if profile.user_type == "enseignant_cadre" and "departement" in payload:
            dep = get_object_or_404(Departement, pk=payload["departement"])
            cours.departement = dep

        cours.save()
        return Response(CoursSerializer(cours).data, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les modules d'un cours (avec leçons)",
        description=(
            "Retourne, paginés et triés par ordre, les modules d'un cours "
            "avec leurs leçons imbriquées."
        ),
        tags=["formation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: ModuleAvecLeconsSerializer(many=True)},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class ModuleListByCoursView(PaginatedListMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cours_id):
        cours = get_object_or_404(Cours, id=cours_id)

        modules = Module.objects.filter(cours=cours).prefetch_related("lecons").order_by("ordre")

        page = self.paginate_queryset(modules)
        serializer = ModuleAvecLeconsSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les niveaux d'un département (public)",
        description=(
            "Retourne la liste des niveaux distincts des cours d'un département. "
            "Vue publique consultée depuis le formulaire d'inscription, avant "
            "connexion."
        ),
        tags=["formation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_NOT_FOUND],
    ),
)
class DepartementNiveauxAPIView(APIView):
    # Public : consulté depuis le formulaire d'inscription, avant connexion
    # (lib/views/auth/register_page.dart → _fetchNiveaux).
    permission_classes = [AllowAny]

    def get(self, request, departement_id):
        niveaux = (
            Cours.objects.filter(departement_id=departement_id)
            .values_list("niveau", flat=True)
            .distinct()
        )
        return Response(niveaux)


# TODO(audit): vue orpheline, non routée (docs/AUDIT_BACKEND.md §4).
@extend_schema(
    summary="Lister les cours visibles selon le rôle de l'utilisateur",
    description=(
        "Retourne, paginés, les cours visibles par l'utilisateur connecté selon "
        "son rôle : tous les cours pour admin/enseignant_admin, les cours du "
        "département pour un enseignant_cadre, les cours dont il est enseignant "
        "principal pour un enseignant_principal, ses cours secondaires pour un "
        "enseignant. Non câblée à ce jour dans les urls (lacune de routage "
        "documentée, hors périmètre)."
    ),
    tags=["formation"],
    parameters=[*PARAMS_PAGINATION],
    responses={200: CoursSerializer(many=True)},
    examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def liste_cours(request):
    user = request.user

    if getattr(user, "user_type", None) in ["admin", "enseignant_admin"]:
        qs = Cours.objects.all()
    elif getattr(user, "user_type", None) == "enseignant_cadre":
        qs = Cours.objects.filter(departement__cadre=user)
    elif getattr(user, "user_type", None) == "enseignant_principal":
        qs = Cours.objects.filter(enseignant_principal=user)
    elif getattr(user, "user_type", None) == "enseignant":
        # relation ManyToMany 'cours_secondaires' supposée exister sur le modèle
        qs = user.cours_secondaires.all()
    else:
        return Response({"error": "Rôle non géré"}, status=status.HTTP_403_FORBIDDEN)

    paginator = YekiPageNumberPagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = CoursSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


@extend_schema_view(
    post=extend_schema(
        summary="Ajouter une leçon à un cours",
        description=("Crée une leçon dans un cours. Réservé à l'enseignant principal du " "cours."),
        tags=["formation"],
        request=LeconCreateSerializer,
        responses={201: LeconCreateSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class AjouterLeconView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, pk=cours_id)

        if cours.enseignant_principal != request.user.profile:
            raise PermissionDenied("Seul l’enseignant principal peut ajouter une leçon.")

        serializer = LeconCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(cours=cours, created_by=request.user.profile)
        lecon = serializer.instance
        enregistrer_activite(
            user=request.user,
            action="lesson_created",
            description=f"Leçon « {lecon.titre} » ajoutée au cours « {cours.titre} »",
            data={"lecon": lecon.titre, "cours": cours.titre},
            objet_id=lecon.id,
            objet_type="Lecon",
        )

        cours.nb_lecons += 1
        cours.save(update_fields=["nb_lecons"])

        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(
        summary="Lister les lectures récentes et non terminées de l'apprenant",
        description=(
            "Retourne, paginées et triées par dernière consultation, les leçons "
            "en cours de progression (non terminées) de l'apprenant connecté, "
            "avec le temps estimé restant. Chaque élément contient : lecon_id, "
            "lecon_titre, cours_id, cours_titre, cours_color, cours_icon, "
            "module_titre, pourcentage, derniere_vue, mins_restants."
        ),
        tags=["formation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class LecturesRecentesView(PaginatedListMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # ── Avec le modèle ProgressionLecon ──────────────────────
        progressions = (
            ProgressionLecon.objects.filter(
                apprenant=request.user,
                terminee=False,  # Seulement les leçons non terminées
            )
            .select_related(
                "lecon__cours__enseignant_principal__user",
                "lecon__module",
            )
            .order_by("-derniere_vue")
        )

        page = self.paginate_queryset(progressions)

        result = []
        for p in page:
            lecon = p.lecon
            cours = lecon.cours
            module_titre = lecon.module.titre if lecon.module else ""

            # Estimer le temps restant (supposons ~5 min par leçon)
            mins_total = 5
            mins_restants = max(1, round(mins_total * (1 - p.pourcentage / 100)))

            result.append(
                {
                    "lecon_id": lecon.id,
                    "lecon_titre": lecon.titre,
                    "cours_id": cours.id,
                    "cours_titre": cours.titre,
                    "cours_color": cours.color_code or "#2884A0",
                    "cours_icon": cours.icon_name or "school",
                    "module_titre": module_titre,
                    "pourcentage": p.pourcentage,
                    "derniere_vue": p.derniere_vue.isoformat(),
                    "mins_restants": mins_restants,
                }
            )

        return self.get_paginated_response(result)


@extend_schema_view(
    post=extend_schema(
        summary="Enregistrer la progression de visionnage d'une leçon",
        description=(
            "Met à jour (ou crée) la progression de l'apprenant connecté sur une "
            'leçon. Corps attendu : `{"lecon_id": <int>, "pourcentage": <0-100>}`. '
            "La leçon est marquée terminée à partir de 90%."
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class MarquerLeconVueView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        lecon_id = request.data.get("lecon_id")
        pourcentage = request.data.get("pourcentage", 0)

        if not lecon_id:
            return Response(
                {"detail": "lecon_id est requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            pourcentage = max(0, min(100, int(pourcentage)))
        except (TypeError, ValueError):
            pourcentage = 0

        lecon = get_object_or_404(Lecon, pk=lecon_id)

        # Toute erreur inattendue ici doit remonter à EXCEPTION_HANDLER
        # (SERVER_ERROR journalisé avec traceback), pas être reformatée à la
        # main avec le message technique `str(e)` fuité au client.
        prog, created = ProgressionLecon.objects.update_or_create(
            apprenant=request.user,
            lecon=lecon,
            defaults={
                "cours": lecon.cours,
                "pourcentage": pourcentage,
                "terminee": pourcentage >= 90,
            },
        )

        return Response(
            {
                "lecon_id": lecon.id,
                "pourcentage": prog.pourcentage,
                "terminee": prog.terminee,
                "created": created,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Créer un module dans un cours",
        description=("Crée un module dans un cours. Réservé à l'enseignant principal du " "cours."),
        tags=["formation"],
        request=ModuleCreateSerializer,
        responses={201: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class ModuleCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cours_id):
        cours = get_object_or_404(Cours, id=cours_id)

        # 🔐 Sécurité : seul l’enseignant principal
        if cours.enseignant_principal != request.user.profile:
            raise PermissionDenied("Seul l'enseignant principal peut créer un module.")

        serializer = ModuleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        module = serializer.save(cours=cours)
        enregistrer_activite(
            user=request.user,
            action="module_created",
            description=f"Module « {module.titre} » créé dans le cours « {cours.titre} »",
            data={"module": module.titre, "cours": cours.titre, "ordre": module.ordre},
            objet_id=module.id,
            objet_type="Module",
        )

        return Response(
            {"id": module.id, "titre": module.titre, "ordre": module.ordre, "cours": cours.id},
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    patch=extend_schema(
        summary="Modifier un module",
        description=(
            "Modifie le titre, la description et/ou l'ordre d'un module. "
            "Réservé à l'enseignant principal du cours lié."
        ),
        tags=["formation"],
        request=ModuleUpdateSerializer,
        responses={200: ModuleAvecLeconsSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class ModuleUpdateView(APIView):
    """
    PATCH /api/modules/<module_id>/modifier/
    Modifie le titre, la description et/ou l'ordre d'un module.
    Réservé à l'enseignant principal du cours lié.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, module_id):
        module = get_object_or_404(Module, pk=module_id)
        cours = module.cours

        # 🔐 Seul l'enseignant principal peut modifier
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut modifier un module."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ModuleUpdateSerializer(module, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        enregistrer_activite(
            user=request.user,
            action="module_modified",
            description=f"Module « {updated.titre} » modifié",
            data={"module": updated.titre, "cours": updated.cours.titre},
            objet_id=updated.id,
            objet_type="Module",
        )
        return Response(
            ModuleAvecLeconsSerializer(updated, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    delete=extend_schema(
        summary="Supprimer un module",
        description=(
            "Supprime un module et toutes ses leçons (cascade Django). Réservé "
            "à l'enseignant principal du cours lié."
        ),
        tags=["formation"],
        responses={204: None},
        examples=[*ERREURS_COURANTES],
    ),
)
class ModuleDeleteView(APIView):
    """
    DELETE /api/modules/<module_id>/supprimer/
    Supprime un module et toutes ses leçons (cascade Django).
    Réservé à l'enseignant principal du cours lié.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def delete(self, request, module_id):
        module = get_object_or_404(Module, pk=module_id)
        cours = module.cours

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile:
            return Response(
                {"detail": "Seul l'enseignant principal peut supprimer un module."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Décrémenter nb_lecons du cours
        nb_lecons_module = module.lecons.count()
        enregistrer_activite(
            user=request.user,
            action="module_deleted",
            description=f"Module « {module.titre} » supprimé du cours « {cours.titre} »",
            data={"module": module.titre, "cours": cours.titre},
            objet_type="Module",
        )
        module.delete()

        if nb_lecons_module > 0:
            cours.nb_lecons = max(0, cours.nb_lecons - nb_lecons_module)
            cours.save(update_fields=["nb_lecons"])

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    patch=extend_schema(
        summary="Modifier une leçon",
        description=(
            "Modifie une leçon (titre, description, module, fichier_pdf, "
            "video). Réservé à l'enseignant principal du cours OU au créateur "
            "de la leçon. Accepte multipart/form-data pour les fichiers."
        ),
        tags=["formation"],
        request=LeconUpdateSerializer,
        responses={200: LeconSerializer},
        examples=[*ERREURS_ECRITURE],
    ),
)
class LeconUpdateView(APIView):
    """
    PATCH /api/lecons/<lecon_id>/modifier/
    Modifie une leçon (titre, description, module, fichier_pdf, video).
    Réservé à l'enseignant principal du cours OU au créateur de la leçon.
    Accepte multipart/form-data pour les fichiers.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @transaction.atomic
    def patch(self, request, lecon_id):
        lecon = get_object_or_404(Lecon, pk=lecon_id)
        cours = lecon.cours

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        # 🔐 Enseignant principal OU créateur de la leçon
        if cours.enseignant_principal != profile and lecon.created_by != profile:
            return Response(
                {"detail": "Vous n'avez pas la permission de modifier cette leçon."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = LeconUpdateSerializer(lecon, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(
            LeconSerializer(updated, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    delete=extend_schema(
        summary="Supprimer une leçon",
        description=(
            "Supprime une leçon. Réservé à l'enseignant principal du cours OU "
            "au créateur de la leçon."
        ),
        tags=["formation"],
        responses={204: None},
        examples=[*ERREURS_COURANTES],
    ),
)
class LeconDeleteView(APIView):
    """
    DELETE /api/lecons/<lecon_id>/supprimer/
    Supprime une leçon.
    Réservé à l'enseignant principal du cours OU au créateur.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def delete(self, request, lecon_id):
        lecon = get_object_or_404(Lecon, pk=lecon_id)
        cours = lecon.cours

        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if cours.enseignant_principal != profile and lecon.created_by != profile:
            return Response(
                {"detail": "Vous n'avez pas la permission de supprimer cette leçon."},
                status=status.HTTP_403_FORBIDDEN,
            )
        enregistrer_activite(
            user=request.user,
            action="lesson_deleted",
            description=f"Leçon « {lecon.titre} » supprimée du cours « {cours.titre} »",
            data={"lecon": lecon.titre, "cours": cours.titre},
            objet_type="Lecon",
        )
        lecon.delete()

        cours.nb_lecons = max(0, cours.nb_lecons - 1)
        cours.save(update_fields=["nb_lecons"])

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    post=extend_schema(
        summary="Aimer / retirer son like sur une leçon",
        description=(
            "Bascule (toggle) le like de l'apprenant connecté sur une leçon : "
            "ajoute le like s'il n'existe pas, le retire sinon. Réservé aux "
            "profils de type 'apprenant'."
        ),
        tags=["formation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
    get=extend_schema(
        summary="Vérifier si l'apprenant a aimé une leçon",
        description=(
            "Retourne si l'utilisateur connecté a liké la leçon, ainsi que le "
            "nombre total de likes de la leçon."
        ),
        tags=["formation"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class LeconLikeView(APIView):
    """
    POST /api/apprenant/lecon/<lecon_id>/like/
    Gère les likes d'une leçon par un apprenant.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, lecon_id):
        lecon = get_object_or_404(Lecon, pk=lecon_id)
        user = request.user

        # Vérifier que l'utilisateur est un apprenant
        try:
            profile = user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "apprenant":
            return Response(
                {"detail": "Seuls les apprenants peuvent liker des leçons."}, status=403
            )

        try:
            like = LeconLike.objects.get(user=user, lecon=lecon)
            like.delete()
            liked = False
            message = "Like retiré"
        except LeconLike.DoesNotExist:
            LeconLike.objects.create(user=user, lecon=lecon)
            liked = True
            message = "Like ajouté"

        # Récupérer le nombre total de likes
        total_likes = LeconLike.objects.filter(lecon=lecon).count()

        return Response(
            {"liked": liked, "total_likes": total_likes, "message": message},
            status=status.HTTP_200_OK,
        )

    def get(self, request, lecon_id):
        """Vérifie si l'utilisateur a liké la leçon"""
        lecon = get_object_or_404(Lecon, pk=lecon_id)
        user = request.user

        liked = LeconLike.objects.filter(user=user, lecon=lecon).exists()
        total_likes = LeconLike.objects.filter(lecon=lecon).count()

        return Response({"liked": liked, "total_likes": total_likes}, status=status.HTTP_200_OK)


@extend_schema_view(
    patch=extend_schema(
        summary="Changer l'enseignant principal d'un cours",
        description=(
            "Change l'enseignant principal d'un cours. Réservé à l'enseignant "
            "cadre du département auquel appartient le cours. Corps attendu : "
            '`{"enseignant_principal_id": <int>}`.'
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class ChangerEnseignantPrincipalView(APIView):
    """
    PATCH /api/cours/<cours_id>/changer-enseignant-principal/
    Body  : { "enseignant_principal_id": <int> }
    Accès : enseignant_cadre du département auquel appartient le cours
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, cours_id):
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        if profile.user_type != "enseignant_cadre":
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=status.HTTP_403_FORBIDDEN,
            )

        cours = get_object_or_404(Cours, pk=cours_id)

        # Sécurité : le cadre ne peut modifier que les cours de son département
        if cours.departement.cadre != profile:
            return Response(
                {"detail": "Ce cours n'appartient pas à votre département."},
                status=status.HTTP_403_FORBIDDEN,
            )

        ep_id = request.data.get("enseignant_principal_id")
        if not ep_id:
            return Response(
                {"detail": "enseignant_principal_id est requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ep = get_object_or_404(Profile, pk=ep_id)
        if ep.user_type != "enseignant_principal":
            return Response(
                {"detail": "Cet utilisateur n'est pas un enseignant principal."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cours.enseignant_principal = ep
        cours.save(update_fields=["enseignant_principal"])
        enregistrer_activite(
            user=request.user,
            action="teacher_changed",
            description=f"Enseignant principal de « {cours.titre} » changé pour {ep.user.get_full_name() or ep.user.username}",
            data={
                "cours": cours.titre,
                "enseignant": ep.user.get_full_name() or ep.user.username,
                "departement": cours.departement.nom,
            },
            objet_id=cours.id,
            objet_type="Cours",
        )

        return Response(
            {"detail": "Enseignant principal mis à jour avec succès."}, status=status.HTTP_200_OK
        )


@extend_schema_view(
    patch=extend_schema(
        summary="Modifier un cours (enseignant cadre)",
        description=(
            "Modifie titre, niveau, description_brief, color_code et/ou "
            "icon_name d'un cours. Réservé à l'enseignant cadre du département "
            "auquel appartient le cours."
        ),
        tags=["formation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class ModifierCoursParCadreView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, cours_id):
        # ── Récupérer le profil ──────────────────────────────────
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profil introuvable."}, status=404)

        # ── Vérifier le rôle ─────────────────────────────────────
        if profile.user_type != "enseignant_cadre":
            return Response(
                {"detail": "Accès réservé aux enseignants cadres."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Récupérer le cours ───────────────────────────────────
        cours = get_object_or_404(Cours, pk=cours_id)

        # ── Sécurité : le cours doit appartenir au département du cadre ──
        if cours.departement.cadre != profile:
            return Response(
                {"detail": "Ce cours n'appartient pas à votre département."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data

        # ── Titre ────────────────────────────────────────────────
        if "titre" in data:
            titre = data["titre"].strip()
            if not titre:
                return Response(
                    {"detail": "Le titre ne peut pas être vide."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            cours.titre = titre

        # ── Niveau ───────────────────────────────────────────────
        if "niveau" in data:
            niveau = data["niveau"].strip()
            if not niveau:
                return Response(
                    {"detail": "Le niveau ne peut pas être vide."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            cours.niveau = niveau

        # ── Description courte ───────────────────────────────────
        if "description_brief" in data:
            cours.description_brief = (data["description_brief"] or "").strip()

        # ── Couleur ──────────────────────────────────────────────
        if "color_code" in data:
            color = data["color_code"].strip()
            if color and not color.startswith("#"):
                color = f"#{color}"
            if len(color) not in [4, 7]:  # #RGB ou #RRGGBB
                return Response(
                    {"detail": "Format de couleur invalide. Utilisez #RRGGBB."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            cours.color_code = color

        # ── Icône ─────────────────────────────────────────────────
        if "icon_name" in data:
            cours.icon_name = (data["icon_name"] or "school").strip()

        cours.save()

        enregistrer_activite(
            user=request.user,
            action="course_modified",
            description=f"Cours « {cours.titre} » modifié",
            data={"titre": cours.titre, "niveau": cours.niveau, "color_code": cours.color_code},
            objet_id=cours.id,
            objet_type="Cours",
        )

        # ── Réponse ───────────────────────────────────────────────
        ep_data = None
        if cours.enseignant_principal:
            ep = cours.enseignant_principal
            ep_data = {
                "id": ep.id,
                "nom": f"{ep.user.first_name} {ep.user.last_name}".strip() or ep.user.username,
                "username": ep.user.username,
            }

        return Response(
            {
                "id": cours.id,
                "titre": cours.titre,
                "niveau": cours.niveau,
                "description_brief": cours.description_brief,
                "color_code": cours.color_code,
                "icon_name": cours.icon_name,
                "nb_apprenants": cours.nb_apprenants,
                "nb_lecons": cours.nb_lecons,
                "nb_devoirs": cours.nb_devoirs,
                "enseignant_principal": ep_data,
                "detail": "Cours modifié avec succès.",
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    get=extend_schema(
        summary="Lister les cours d'un département",
        description=(
            "Retourne, paginés, les cours d'un département donné. Chaque "
            "élément contient : id, titre, niveau, nb_apprenants, "
            "taux_completion, color_code, icon_name."
        ),
        tags=["formation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    ),
)
class CoursParDepartementView(PaginatedListMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, departement_id):
        departement = get_object_or_404(Departement, pk=departement_id)
        cours_qs = Cours.objects.filter(departement=departement).select_related(
            "enseignant_principal__user"
        )
        page = self.paginate_queryset(cours_qs)
        data = [
            {
                "id": c.id,
                "titre": c.titre,
                "niveau": c.niveau,
                "nb_apprenants": c.nb_apprenants,
                "taux_completion": 0,
                "color_code": c.color_code,
                "icon_name": c.icon_name,
            }
            for c in page
        ]
        return self.get_paginated_response(data)
