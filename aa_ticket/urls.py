from django.urls import path

from .views import files, manage, prefs, requester, staff, ticket

app_name = "aa_ticket"

urlpatterns = [
    path("", requester.index, name="index"),
    path("mine/", requester.my_tickets, name="my_tickets"),
    path("new/", requester.submit_choose_department, name="submit"),
    path("new/<int:department_id>/", requester.submit, name="submit_form"),
    path("<int:pk>/", ticket.detail, name="detail"),
    path("<int:pk>/reply/", ticket.reply, name="reply"),
    path("<int:pk>/action/<str:action>/", ticket.action, name="action"),
    path("staff/", staff.workbench, name="workbench"),
    path("stats/", staff.stats, name="stats"),
    path("prefs/", prefs.prefs, name="prefs"),
    path("manage/departments/", manage.departments, name="manage_departments"),
    path("manage/departments/<int:pk>/", manage.department_edit, name="manage_department_edit"),
    path("manage/departments/<int:pk>/delete/", manage.department_delete, name="manage_department_delete"),
    path("manage/departments/<int:pk>/test/", manage.department_test, name="manage_department_test"),
    path("manage/priorities/", manage.priorities, name="manage_priorities"),
    path("manage/priorities/<int:pk>/", manage.priority_edit, name="manage_priority_edit"),
    path("manage/priorities/<int:pk>/delete/", manage.priority_delete, name="manage_priority_delete"),
    path("manage/categories/", manage.categories, name="manage_categories"),
    path("manage/categories/<int:pk>/", manage.category_edit, name="manage_category_edit"),
    path("manage/categories/<int:pk>/delete/", manage.category_delete, name="manage_category_delete"),
    path("manage/canned/", manage.canned, name="manage_canned"),
    path("manage/canned/<int:pk>/", manage.canned_edit, name="manage_canned_edit"),
    path("manage/canned/<int:pk>/delete/", manage.canned_delete, name="manage_canned_delete"),
    path("manage/settings/", manage.settings_view, name="manage_settings"),
    path("files/<int:pk>/", files.attachment, name="attachment"),
]
