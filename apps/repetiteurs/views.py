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
from apps.core.schema_examples import ERREURS_COURANTES
from apps.formation.models import Cours


# TODO(audit): cette vue n'utilise PAS le modèle Repetiteur — elle interroge
# directement Profile/Cours et hardcode `tarif: 5000` (valeur métier en dur,
# voir docs/AUDIT_BACKEND.md §6). Déplacée telle quelle par convention de
# route ("déplacer, ne pas réécrire") ; correction (ParametreSysteme) à
# traiter séparément.
@extend_schema_view(
    get=extend_schema(
        summary="Rechercher des répétiteurs par matière",
        description=(
            "Recherche des enseignants (principaux et secondaires) validés "
            "répétiteurs par le Service Client (`is_repetiteur=True`) et "
            "disponibles à domicile pour une matière donnée, avec filtres "
            "optionnels par ville et niveau. Retourne pour chaque répétiteur son "
            "nom, les matières enseignées, un tarif fixe de 5000 FCFA/mois, son "
            "contact WhatsApp et un modèle de message pré-rempli. Note : le "
            "champ `tarif` est actuellement une valeur fixe codée en dur (voir "
            "docs/AUDIT_BACKEND.md §6), pas une donnée métier configurable."
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
                            "tarif": 5000,
                            "whatsapp": "+237690000000",
                            "avatar": "https://api.yeki.cm/media/avatars/jmbarga.jpg",
                            "ville": "Yaounde",
                            "disponible": True,
                            "niveau": "Terminale",
                        }
                    ],
                    "tarif_mensuel": 5000,
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
    - nom, matière, tarif (5000 FCFA/mois), numéro WhatsApp, ville
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
                # Numéro WhatsApp (à stocker dans le profil)
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
                        "tarif": 5000,  # 5000 FCFA par mois
                        "whatsapp": whatsapp,
                        "avatar": (
                            request.build_absolute_uri(profil.avatar.url) if profil.avatar else None
                        ),
                        "ville": profil.ville or "",
                        "disponible": True,
                        "niveau": profil.niveau or "",
                    }
                )

        return Response(
            {
                "matiere": matiere,
                "total": len(resultats),
                "repetiteurs": resultats,
                "tarif_mensuel": 5000,
                "message_whatsapp_template": f"Bonjour, je souhaite prendre des cours de {matiere} avec vous à domicile.",
            },
            status=200,
        )
