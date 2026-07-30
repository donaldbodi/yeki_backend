from django.urls import path

from apps.notifications.views import (
    NotificationsView,
    MarquerNotificationLueView,
    MarquerToutesNotificationsLuesView,
    NotificationsNonLuesView,
    DeviceTokenView,
    DeviceTokenDeleteView,
)

urlpatterns = [
    path("notifications/", NotificationsView.as_view(), name="notifications"),
    path(
        "notifications/<int:id>/lire/",
        MarquerNotificationLueView.as_view(),
        name="notifications-lire",
    ),
    path(
        "notifications/tout-lire/",
        MarquerToutesNotificationsLuesView.as_view(),
        name="notifications-tout-lire",
    ),
    path(
        "notifications/non-lues/", NotificationsNonLuesView.as_view(), name="notifications-non-lues"
    ),
    path(
        "notifications/device-token/", DeviceTokenView.as_view(), name="notifications-device-token"
    ),
    path(
        "notifications/device-token/<str:token>/",
        DeviceTokenDeleteView.as_view(),
        name="notifications-device-token-delete",
    ),
]
