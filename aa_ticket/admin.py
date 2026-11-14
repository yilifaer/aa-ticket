"""Django admin: read-only backup view.

Everything is configured on the app's own management pages. The admin only lets
superusers delete single messages or images in emergencies (for example an image
that contains private data).
"""

from django.contrib import admin

from .attachments import delete_attachment
from .models import Attachment, CannedReply, Category, Department, Priority, Ticket, TicketMessage


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Department)
class DepartmentAdmin(ReadOnlyAdmin):
    list_display = ("name", "parent", "is_active", "accepts_submissions", "order")
    exclude = ("webhook_url",)


@admin.register(Priority)
class PriorityAdmin(ReadOnlyAdmin):
    list_display = ("name", "order", "mention_on_new", "remind_after_minutes", "escalate_after_minutes", "is_active")


@admin.register(Category)
class CategoryAdmin(ReadOnlyAdmin):
    list_display = ("name", "department", "is_active")


@admin.register(CannedReply)
class CannedReplyAdmin(ReadOnlyAdmin):
    list_display = ("title", "department")


@admin.register(Ticket)
class TicketAdmin(ReadOnlyAdmin):
    list_display = ("id", "title", "department", "priority", "status", "requester", "assignee", "created_at")
    list_filter = ("status", "department", "priority")
    search_fields = ("title",)


class SuperuserDeleteAdmin(ReadOnlyAdmin):
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(TicketMessage)
class TicketMessageAdmin(SuperuserDeleteAdmin):
    list_display = ("id", "ticket", "kind", "author", "created_at")
    list_filter = ("kind",)

    def delete_model(self, request, obj):
        for attachment in obj.attachments.all():
            delete_attachment(attachment)
        obj.delete()

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self.delete_model(request, obj)


@admin.register(Attachment)
class AttachmentAdmin(SuperuserDeleteAdmin):
    list_display = ("id", "original_name", "content_type", "size", "message", "created_at")

    def delete_model(self, request, obj):
        delete_attachment(obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            delete_attachment(obj)
