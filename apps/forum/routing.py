from django.urls import re_path

from apps.forum.consumers import ForumConsumer

websocket_urlpatterns = [
    re_path(r"^ws/forum/$", ForumConsumer.as_asgi()),
    re_path(r"^ws/forum/cours/(?P<cours_id>\d+)/$", ForumConsumer.as_asgi()),
]
