from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiExample,
)
from drf_spectacular.types import OpenApiTypes

from apps.accounts.models import Profile
from apps.accounts.services import _nom_profil
from apps.core.models import ParametreSysteme
from apps.core.schema_examples import ERREURS_COURANTES
from apps.formation.models import Cours
from apps.repetiteurs.models import Repetiteur
from apps.repetiteurs.serializers import RepetiteurSerializer
from yeki.permissions import IsServiceClient


# P9.5 : le tarif en dur (`5000`) est corrigé — lu depuis `ParametreSysteme
# ['tarif_repetiteur_mensuel']` (même clé que `Repetiteur._tarif_repetiteur_
# defaut()`, déjà utilisée comme valeur par défaut du modèle), avec un
# repli sur la fiche `Repetiteur` du profil quand une existe (ville/tarif
# individualisés, éditables par le Service Client — voir
# RepetiteurFicheDetailView plus bas). La logique de correspondance
# matière reste basée sur `Cours.enseignant_principal`/`cours_secondaires`
# (contrat déjà testé, apps/repetiteurs/tests/test_views.py) — PAS
# réécrite pour interroger `Repetiteur.cours` directement, ce qui casserait
# ce contrat (les fiches Repetiteur restent une donnée complémentaire,
# optionnelle, pas la source de vérité de "qui enseigne quoi").
@extend_schema_view(
    get=extend_schema(
        summary="Rechercher des répétiteurs par matière",
        description=(
            "Recherche des enseignants (principaux et secondaires) validés "
            "répétiteurs par le Service Client (`is_repetiteur=True`) et "
            "disponibles à domicile pour une matière donnée, avec filtres "
            "optionnels par ville et niveau. Retourne pour chaque répétiteur son "
            "nom, les matières enseignées, un tarif (FCFA/mois — celui de sa "
            "fiche `Repetiteur` si le Service Client en a créé une pour ce "
            "cours, sinon `ParametreSysteme['tarif_repetiteur_mensuel']`), son "
            "contact WhatsApp et un modèle de message pré-rempli."
        ),
        tags=["repetiteurs"],
        parameters=[
            OpenApiParameter(
                "matiere",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=True,
                description="Matière recherchée (obligatoire).",
            ),
            OpenApiParameter(
                "ville",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filtre optionnel par ville.",
            ),
            OpenApiParameter(
                "niveau",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Niveau recherché (transmis tel quel dans la réponse, non utilisé pour filtrer les résultats).",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                name="Résultats de recherche",
                summary="Réponse 200",
                value={
                    "matiere": "Maths",
                    "total": 1,
                    "repetiteurs": [
                        {
                            "id": 7,
                            "nom": "Jean Mbarga",
                            "username": "jmbarga",
                            "matiere": "Maths",
                            "matieres": ["Maths", "Physique"],
                            "tarif": 7500,
                            "whatsapp": "+237690000000",
                            "avatar": "https://api.yeki.cm/media/avatars/jmbarga.jpg",
                            "ville": "Yaounde",
                            "disponible": True,
                            "niveau": "Terminale",
                        }
                    ],
                    "tarif_mensuel": 7500,
                    "message_whatsapp_template": "Bonjour, je souhaite prendre des cours de maths avec vous à domicile.",
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                name="Paramètre manquant",
                summary="Réponse 400 — matière absente",
                value={"detail": "Le paramètre 'matiere' est requis."},
                response_only=True,
                status_codes=["400"],
            ),
            *ERREURS_COURANTES,
        ],
    ),
)
class RepetiteursSearchView(APIView):
    """
    GET /api/repetiteurs/search/?matiere=maths&ville=Yaounde&niveau=Terminale
    Recherche des enseignants (principaux et secondaires) par matière.

    Retourne :
    - nom, matière, tarif (FCFA/mois, ParametreSysteme ou fiche Repetiteur), numéro WhatsApp, ville
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        matiere = request.query_params.get("matiere", "").strip().lower()
        ville = request.query_params.get("ville", "").strip().lower()
        # TODO(bug pré-existant, non corrigé — "déplacer, ne pas réécrire") :
        # `niveau` est documenté comme paramètre de filtre (voir docstring et
        # @extend_schema ci-dessus) mais n'est jamais utilisé pour filtrer
        # les résultats plus bas (repéré en P1.6 via ruff F841) — seul
        # `matiere`/`ville` filtrent réellement. Le paramètre `niveau` est
        # donc actuellement sans effet.
        niveau = request.query_params.get("niveau", "").strip().lower()  # noqa: F841

        if not matiere:
            return Response({"detail": "Le paramètre 'matiere' est requis."}, status=400)

        tarif_defaut = int(ParametreSysteme.get("tarif_repetiteur_mensuel", default=7500))

        # Rechercher les enseignants (principaux et secondaires)
        # qui enseignent dans des cours correspondant à la matière.
        # is_repetiteur=True (P2.1) : validé par le Service Client — arbitrage
        # tranché par l'utilisateur, appliqué aux deux grades (principal et
        # secondaire) plutôt que d'exclure l'enseignant principal.
        profils = Profile.objects.filter(
            user_type__in=["enseignant_principal", "enseignant"],
            is_active=True,
            is_repetiteur=True,
        ).select_related("user")

        resultats = []
        for profil in profils:
            # Vérifier si l'enseignant enseigne la matière recherchée
            enseigne_matiere = False

            # Cours en tant que principal
            cours_principaux = Cours.objects.filter(
                enseignant_principal=profil, matiere__iexact=matiere
            )

            # Cours en tant que secondaire
            cours_secondaires = profil.cours_secondaires.filter(matiere__iexact=matiere)

            if cours_principaux.exists() or cours_secondaires.exists():
                enseigne_matiere = True

            # Filtrer par ville si spécifiée
            if ville and enseigne_matiere:
                profil_ville = (profil.ville or "").strip().lower()
                if profil_ville and ville not in profil_ville:
                    # Si la ville ne correspond pas, on vérifie si l'enseignant a des cours dans cette ville
                    cours_ville = Cours.objects.filter(
                        departement__ville__iexact=ville, enseignant_principal=profil
                    )
                    if not cours_ville.exists():
                        enseigne_matiere = False

            if enseigne_matiere:
                # P9.5 : si le Service Client a créé/édité une fiche
                # Repetiteur pour ce profil sur un cours de cette matière,
                # elle prime (ville/tarif individualisés) — sinon repli sur
                # le profil + le tarif par défaut. Une fiche explicitement
                # marquée indisponible exclut le profil des résultats.
                fiche = (
                    Repetiteur.objects.filter(enseignant=profil, cours__matiere__iexact=matiere)
                    .order_by("-disponible")
                    .first()
                )
                if fiche is not None and not fiche.disponible:
                    continue

                if fiche is not None:
                    whatsapp = fiche.telephone or ""
                else:
                    whatsapp = getattr(profil, "whatsapp", None) or profil.phone or ""
                if not whatsapp.startswith("+237") and whatsapp:
                    whatsapp = f"+237{whatsapp}"

                # Récupérer les matières enseignées
                matieres_enseignees = []
                for c in cours_principaux:
                    if c.matiere and c.matiere not in matieres_enseignees:
                        matieres_enseignees.append(c.matiere)
                for c in cours_secondaires:
                    if c.matiere and c.matiere not in matieres_enseignees:
                        matieres_enseignees.append(c.matiere)

                resultats.append(
                    {
                        "id": profil.id,
                        "nom": _nom_profil(profil),
                        "username": profil.user.username,
                        "matiere": matiere.capitalize(),
                        "matieres": matieres_enseignees,
                        "tarif": fiche.tarif_mensuel if fiche is not None else tarif_defaut,
                        "whatsapp": whatsapp,
                        "avatar": (
                            request.build_absolute_uri(profil.avatar.url) if profil.avatar else None
                        ),
                        "ville": fiche.ville if fiche is not None else (profil.ville or ""),
                        "disponible": True,
                        "niveau": profil.niveau or "",
                    }
                )

        return Response(
            {
                "matiere": matiere,
                "total": len(resultats),
                "repetiteurs": resultats,
                "tarif_mensuel": tarif_defaut,
                "message_whatsapp_template": f"Bonjour, je souhaite prendre des cours de {matiere} avec vous à domicile.",
            },
            status=200,
        )


# ═══════════════════════════════════════════════════════════════════════
# ADMINISTRATION (Service Client) — P9.5, n'existait pas avant ce ticket.
# ═══════════════════════════════════════════════════════════════════════


@extend_schema_view(
    patch=extend_schema(
        summary="Basculer is_repetiteur (Service Client)",
        description=(
            "Bascule la validation « répétiteur » d'un profil enseignant. Un "
            "passage à `False` désactive en cascade ses fiches `Repetiteur` "
            "(signal existant, apps/accounts/signals.py) SANS les supprimer."
        ),
        tags=["repetiteurs"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class RepetiteurToggleView(APIView):
    """
    PATCH /api/repetiteurs/admin/<profile_id>/toggle/
    Body: { "is_repetiteur": true|false }

    Bascule la validation "répétiteur" d'un profil enseignant. Un passage
    à `False` désactive en cascade ses fiches `Repetiteur` (signal déjà
    existant, apps/accounts/signals.py) SANS les supprimer (règle 5).
    """

    permission_classes = [IsServiceClient]

    def patch(self, request, profile_id):
        profil = get_object_or_404(
            Profile.objects.select_related("user"),
            pk=profile_id,
            user_type__in=["enseignant", "enseignant_principal"],
        )
        valeur = request.data.get("is_repetiteur")
        if not isinstance(valeur, bool):
            return Response({"detail": "is_repetiteur (bool) est obligatoire."}, status=400)

        profil.is_repetiteur = valeur
        profil.save(update_fields=["is_repetiteur"])
        return Response({"id": profil.id, "is_repetiteur": profil.is_repetiteur})


@extend_schema_view(
    get=extend_schema(
        summary="Candidats répétiteurs (Service Client)",
        description=(
            "Liste les enseignants (principaux et secondaires) avec leur "
            "statut `is_repetiteur` et leurs fiches `Repetiteur` existantes — "
            "vue d'ensemble avant bascule/édition. Filtrable par `is_repetiteur`."
        ),
        tags=["repetiteurs"],
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class RepetiteurCandidatsListView(APIView):
    """
    GET /api/repetiteurs/admin/candidats/?is_repetiteur=true|false
    Liste les enseignants (principaux et secondaires) avec leur statut
    `is_repetiteur` et leurs fiches `Repetiteur` existantes — vue
    d'ensemble pour le Service Client avant bascule/édition.
    """

    permission_classes = [IsServiceClient]

    def get(self, request):
        qs = (
            Profile.objects.filter(user_type__in=["enseignant", "enseignant_principal"], is_active=True)
            .select_related("user")
            .order_by("user__username")
        )
        filtre = request.query_params.get("is_repetiteur")
        if filtre is not None:
            qs = qs.filter(is_repetiteur=filtre.lower() == "true")

        candidats = []
        for profil in qs:
            fiches = Repetiteur.objects.filter(enseignant=profil).select_related("cours")
            candidats.append(
                {
                    "id": profil.id,
                    "nom": _nom_profil(profil),
                    "username": profil.user.username,
                    "is_repetiteur": profil.is_repetiteur,
                    "fiches": RepetiteurSerializer(fiches, many=True).data,
                }
            )
        return Response({"candidats": candidats})


@extend_schema_view(
    get=extend_schema(
        summary="Lister les fiches répétiteur (Service Client)",
        tags=["repetiteurs"],
        responses={200: RepetiteurSerializer(many=True)},
    ),
    post=extend_schema(
        summary="Ajouter une fiche répétiteur (Service Client)",
        description=(
            "« Ajouter à un cours » : crée une fiche `Repetiteur` pour un "
            "enseignant DÉJÀ validé (`is_repetiteur=True` — basculer avant, "
            "sinon 400)."
        ),
        tags=["repetiteurs"],
        request=RepetiteurSerializer,
        responses={201: RepetiteurSerializer},
        examples=[*ERREURS_COURANTES],
    ),
)
class RepetiteurFicheListCreateView(APIView):
    """
    GET  /api/repetiteurs/admin/fiches/  — toutes les fiches.
    POST /api/repetiteurs/admin/fiches/  — « ajouter à un cours ».
    Body POST: { "enseignant": <profile_id>, "cours": <cours_id>,
                 "ville": "...", "telephone": "...", "tarif_mensuel": 7500 }
    """

    permission_classes = [IsServiceClient]

    def get(self, request):
        qs = Repetiteur.objects.select_related("enseignant__user", "cours").order_by("-created_at")
        return Response(RepetiteurSerializer(qs, many=True).data)

    def post(self, request):
        serializer = RepetiteurSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enseignant = serializer.validated_data["enseignant"]
        if not enseignant.is_repetiteur:
            return Response(
                {
                    "detail": (
                        "Cet enseignant n'est pas encore validé répétiteur "
                        "(basculer is_repetiteur avant de lui ajouter une fiche)."
                    )
                },
                status=400,
            )
        serializer.save()
        return Response(serializer.data, status=201)


@extend_schema_view(
    patch=extend_schema(
        summary="Éditer une fiche répétiteur (Service Client)",
        description="Édite ville/tarif_mensuel/disponible/telephone d'une fiche existante.",
        tags=["repetiteurs"],
        request=RepetiteurSerializer,
        responses={200: RepetiteurSerializer},
        examples=[*ERREURS_COURANTES],
    ),
    delete=extend_schema(
        summary="Retirer une fiche répétiteur d'un cours (Service Client)",
        tags=["repetiteurs"],
        responses={204: None},
        examples=[*ERREURS_COURANTES],
    ),
)
class RepetiteurFicheDetailView(APIView):
    """
    PATCH  /api/repetiteurs/admin/fiches/<pk>/  — éditer ville/tarif/disponible.
    DELETE /api/repetiteurs/admin/fiches/<pk>/  — « retirer d'un cours ».
    """

    permission_classes = [IsServiceClient]

    def patch(self, request, pk):
        fiche = get_object_or_404(Repetiteur, pk=pk)
        serializer = RepetiteurSerializer(fiche, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        fiche = get_object_or_404(Repetiteur, pk=pk)
        fiche.delete()
        return Response(status=204)
