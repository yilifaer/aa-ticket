from django.db import models
from django.utils.translation import pgettext_lazy


class Status(models.TextChoices):
    OPEN = "open", pgettext_lazy("aa_ticket", "Unclaimed")
    IN_PROGRESS = "in_progress", pgettext_lazy("aa_ticket", "In progress")
    CLOSED = "closed", pgettext_lazy("aa_ticket", "Closed")


class ClosedReason(models.TextChoices):
    REQUESTER = "requester", pgettext_lazy("aa_ticket", "Closed by requester")
    STAFF = "staff", pgettext_lazy("aa_ticket", "Closed by staff")
    AUTO = "auto", pgettext_lazy("aa_ticket", "Closed automatically")


class MessageKind(models.TextChoices):
    REPLY = "reply", pgettext_lazy("aa_ticket", "Reply")
    INTERNAL = "internal", pgettext_lazy("aa_ticket", "Internal note")
    EVENT = "event", pgettext_lazy("aa_ticket", "Event")


class Event(models.TextChoices):
    SUBMITTED = "submitted", pgettext_lazy("aa_ticket", "submitted the ticket")
    CLAIMED = "claimed", pgettext_lazy("aa_ticket", "claimed the ticket")
    ASSIGNED = "assigned", pgettext_lazy("aa_ticket", "assigned the ticket")
    REPLIED = "replied", pgettext_lazy("aa_ticket", "replied")
    NOTED = "noted", pgettext_lazy("aa_ticket", "added an internal note")
    INVITED = "invited", pgettext_lazy("aa_ticket", "invited a department")
    UNINVITED = "uninvited", pgettext_lazy("aa_ticket", "removed a department")
    TRANSFERRED = "transferred", pgettext_lazy("aa_ticket", "transferred the ticket")
    ESCALATION_REQUESTED = "escalation_requested", pgettext_lazy("aa_ticket", "requested escalation")
    PRIORITY_CHANGED = "priority_changed", pgettext_lazy("aa_ticket", "changed the priority")
    CATEGORY_CHANGED = "category_changed", pgettext_lazy("aa_ticket", "changed the category")
    CLOSED = "closed", pgettext_lazy("aa_ticket", "closed the ticket")
    REOPENED = "reopened", pgettext_lazy("aa_ticket", "reopened the ticket")
    UNCLAIMED_REMINDER = "unclaimed_reminder", pgettext_lazy("aa_ticket", "unclaimed reminder sent")
    ESCALATION_REMINDER = "escalation_reminder", pgettext_lazy("aa_ticket", "escalation reminder sent")
    AUTOCLOSE_WARNING = "autoclose_warning", pgettext_lazy("aa_ticket", "auto-close warning sent")
    AWAITING_STAFF_REMINDER = "awaiting_staff_reminder", pgettext_lazy("aa_ticket", "waiting-for-staff reminder sent")
    ASSIGNEE_LEFT = "assignee_left", pgettext_lazy("aa_ticket", "assignee left the department, ticket is unclaimed again")


PRIORITY_COLORS = (
    ("secondary", pgettext_lazy("aa_ticket", "Grey")),
    ("primary", pgettext_lazy("aa_ticket", "Blue")),
    ("info", pgettext_lazy("aa_ticket", "Cyan")),
    ("success", pgettext_lazy("aa_ticket", "Green")),
    ("warning", pgettext_lazy("aa_ticket", "Yellow")),
    ("danger", pgettext_lazy("aa_ticket", "Red")),
)

# Discord embed colours matching the Bootstrap colour names above.
PRIORITY_HEX = {
    "secondary": 0x6C757D,
    "primary": 0x0D6EFD,
    "info": 0x0DCAF0,
    "success": 0x198754,
    "warning": 0xFFC107,
    "danger": 0xDC3545,
}
