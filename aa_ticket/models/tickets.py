from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import pgettext_lazy

from allianceauth.eveonline.models import EveCharacter

from ..constants import ClosedReason, MessageKind, Status
from .config import Category, Department, Priority


class Ticket(models.Model):
    title = models.CharField(pgettext_lazy("aa_ticket", "title"), max_length=200)
    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name="aa_tickets")
    requester_character = models.ForeignKey(
        EveCharacter, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="tickets")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    priority = models.ForeignKey(Priority, on_delete=models.PROTECT, related_name="tickets")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    assignee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    collaborating_departments = models.ManyToManyField(
        Department, blank=True, related_name="collab_tickets"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    open_since = models.DateTimeField()
    claimed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    closed_reason = models.CharField(max_length=20, choices=ClosedReason.choices, blank=True)

    last_reply_at = models.DateTimeField()
    last_reply_by_staff = models.BooleanField(default=False)

    reminded_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    autoclose_warned_at = models.DateTimeField(null=True, blank=True)
    staff_reminded_at = models.DateTimeField(null=True, blank=True)
    escalation_cycle = models.PositiveIntegerField(default=0)

    class Meta:
        default_permissions = ()
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "department"]),
            models.Index(fields=["requester", "status"]),
        ]

    def __str__(self):
        return f"{self.display_number} {self.title}"

    @property
    def display_number(self):
        return f"#{self.pk}"


class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    author_department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    kind = models.CharField(max_length=20, choices=MessageKind.choices)
    body = models.TextField(blank=True)
    event_type = models.CharField(max_length=40, blank=True)
    event_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        ordering = ("created_at", "pk")

    def __str__(self):
        return f"{self.ticket.display_number} {self.kind} {self.pk}"


class Attachment(models.Model):
    message = models.ForeignKey(TicketMessage, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="aa_ticket/%Y/%m/")
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        ordering = ("pk",)

    def __str__(self):
        return self.original_name


class EscalationRequest(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="escalations")
    to_department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="+")
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reason = models.TextField(blank=True)
    cycle = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        ordering = ("created_at",)
