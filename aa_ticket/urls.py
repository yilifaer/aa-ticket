from django.urls import path

from .views import files, requester, ticket

app_name = "aa_ticket"

urlpatterns = [
    path("", requester.index, name="index"),
    path("mine/", requester.my_tickets, name="my_tickets"),
    path("new/", requester.submit_choose_department, name="submit"),
    path("new/<int:department_id>/", requester.submit, name="submit_form"),
    path("<int:pk>/", ticket.detail, name="detail"),
    path("<int:pk>/reply/", ticket.reply, name="reply"),
    path("<int:pk>/action/<str:action>/", ticket.action, name="action"),
    path("files/<int:pk>/", files.attachment, name="attachment"),
]
