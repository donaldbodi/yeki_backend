from django.urls import path

from apps.ia.views import YekiIAChatHistoriqueView, YekiIAChatAvecHistoriqueView

urlpatterns = [
    # ── YEKI IA ───────────────────────────────────────────────────
    path(
        "ia/cours/<int:cours_id>/historique/",
        YekiIAChatHistoriqueView.as_view(),
        name="ia-chat-historique",
    ),
    path("ia/cours/<int:cours_id>/chat/", YekiIAChatAvecHistoriqueView.as_view(), name="ia-chat"),
]
