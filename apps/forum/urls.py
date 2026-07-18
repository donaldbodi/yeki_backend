from django.urls import path

from apps.forum.views import (
    ListeQuestionsView,
    DetailQuestionView,
    ResoudreQuestionView,
    RepondreQuestionView,
    LikerReponseView,
    MarquerSolutionView,
    StatsForumView,
    ForumMessagesPollingView,
)

urlpatterns = [
    path("forum/questions/", ListeQuestionsView.as_view()),
    path("forum/questions/<int:pk>/", DetailQuestionView.as_view()),
    path("forum/questions/<int:pk>/resoudre/", ResoudreQuestionView.as_view()),
    path("forum/questions/<int:pk>/repondre/", RepondreQuestionView.as_view()),
    path("forum/reponses/<int:pk>/liker/", LikerReponseView.as_view()),
    path("forum/reponses/<int:pk>/solution/", MarquerSolutionView.as_view()),
    path("forum/stats/", StatsForumView.as_view()),
    # Sondage incrémental (repli WebSocket) — voir docs/FORUM_TEMPS_REEL.md
    path(
        "forum/<str:room>/messages/",
        ForumMessagesPollingView.as_view(),
        name="forum-messages-polling",
    ),
]
