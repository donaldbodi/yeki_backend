# routing.py - Version complète

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Forum global (sans cours spécifique)
    re_path(r'ws/forum/$', consumers.ForumConsumer.as_asgi()),
    
    # Forum par cours (recommandé)
    re_path(r'ws/forum/cours/(?P<cours_id>\d+)/$', consumers.ForumConsumer.as_asgi()),
]