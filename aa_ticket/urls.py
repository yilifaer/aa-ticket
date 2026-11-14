from django.urls import path

from .views import ticket

app_name = "aa_ticket"

urlpatterns = [
    path("<int:pk>/", ticket.detail, name="detail"),
]
