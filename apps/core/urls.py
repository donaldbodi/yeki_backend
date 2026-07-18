from django.urls import path

from apps.core.views import (
    landing,
    HistoriqueActiviteView,
    HistoriqueStatsView,
    LatestVersionView,
    CheckUpdateView,
    AdminVersionCreateView,
    AdminVersionListView,
)

urlpatterns = [
    path("landing/", landing, name="landing"),
    path("historique/", HistoriqueActiviteView.as_view(), name="historique"),
    path("historique/stats/", HistoriqueStatsView.as_view(), name="historique-stats"),
    path("latest-version/", LatestVersionView.as_view(), name="latest-version"),
    path("check-update/", CheckUpdateView.as_view(), name="check-update"),
    path("admin/versions/", AdminVersionCreateView.as_view(), name="admin-version-create"),
    path("admin/versions/list/", AdminVersionListView.as_view(), name="admin-version-list"),
]
