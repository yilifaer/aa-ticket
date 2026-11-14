from django.urls import path

from .views import files, ticket

app_name = "aa_ticket"

urlpatterns = [
    path("<int:pk>/", ticket.detail, name="detail"),
    path("files/<int:pk>/", files.attachment, name="attachment"),
]
