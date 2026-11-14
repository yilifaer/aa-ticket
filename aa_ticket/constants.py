from django.db import models
from django.utils.translation import gettext_lazy as _


class Status(models.TextChoices):
    OPEN = "open", _("Unclaimed")
    IN_PROGRESS = "in_progress", _("In progress")
    CLOSED = "closed", _("Closed")


class ClosedReason(models.TextChoices):
    REQUESTER = "requester", _("Closed by requester")
    STAFF = "staff", _("Closed by staff")
    AUTO = "auto", _("Closed automatically")


class MessageKind(models.TextChoices):
    REPLY = "reply", _("Reply")
    INTERNAL = "internal", _("Internal note")
    EVENT = "event", _("Event")


class Event(models.TextChoices):
    SUBMITTED = "submitted", _("submitted the ticket")
    CLAIMED = "claimed", _("claimed the ticket")
    ASSIGNED = "assigned", _("assigned the ticket")
    REPLIED = "replied", _("replied")
    NOTED = "noted", _("added an internal note")
    INVITED = "invited", _("invited a department")
    UNINVITED = "uninvited", _("removed a department")
    TRANSFERRED = "transferred", _("transferred the ticket")
    ESCALATION_REQUESTED = "escalation_requested", _("requested escalation")
    PRIORITY_CHANGED = "priority_changed", _("changed the priority")
    CATEGORY_CHANGED = "category_changed", _("changed the category")
    CLOSED = "closed", _("closed the ticket")
    REOPENED = "reopened", _("reopened the ticket")
    UNCLAIMED_REMINDER = "unclaimed_reminder", _("unclaimed reminder sent")
    ESCALATION_REMINDER = "escalation_reminder", _("escalation reminder sent")
    AUTOCLOSE_WARNING = "autoclose_warning", _("auto-close warning sent")
    AWAITING_STAFF_REMINDER = "awaiting_staff_reminder", _("waiting-for-staff reminder sent")


PRIORITY_COLORS = (
    ("secondary", _("Grey")),
    ("primary", _("Blue")),
    ("info", _("Cyan")),
    ("success", _("Green")),
    ("warning", _("Yellow")),
    ("danger", _("Red")),
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
