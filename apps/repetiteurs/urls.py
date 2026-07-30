from django.urls import path

from apps.repetiteurs.views import (
    RepetiteursSearchView,
    RepetiteurCandidatsListView,
    RepetiteurFicheDetailView,
    RepetiteurFicheListCreateView,
    RepetiteurToggleView,
)

urlpatterns = [
    path("repetiteurs/search/", RepetiteursSearchView.as_view(), name="repetiteurs-search"),
    # ── Administration (Service Client, P9.5) ─────────────────────
    path(
        "repetiteurs/admin/candidats/",
        RepetiteurCandidatsListView.as_view(),
        name="repetiteurs-admin-candidats",
    ),
    path(
        "repetiteurs/admin/<int:profile_id>/toggle/",
        RepetiteurToggleView.as_view(),
        name="repetiteurs-admin-toggle",
    ),
    path(
        "repetiteurs/admin/fiches/",
        RepetiteurFicheListCreateView.as_view(),
        name="repetiteurs-admin-fiches",
    ),
    path(
        "repetiteurs/admin/fiches/<int:pk>/",
        RepetiteurFicheDetailView.as_view(),
        name="repetiteurs-admin-fiche-detail",
    ),
]
