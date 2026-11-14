import re

from solo.models import SingletonModel

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from allianceauth.authentication.models import State

from ..constants import PRIORITY_COLORS

_ROLE_IDS_RE = re.compile(r"^\s*\d+(\s*[,\s]\s*\d+)*\s*$")


def validate_role_ids(value):
    if value and not _ROLE_IDS_RE.match(value):
        raise ValidationError(
            _("Enter Discord role IDs as numbers, separated by commas or spaces.")
        )


class General(models.Model):
    """Holds the app's permissions. Has no table."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("basic_access", "Can submit and view own tickets"),
            ("view_all", "Can view all tickets"),
            ("manage", "Can manage ticket settings"),
        )


class Department(models.Model):
    name = models.CharField(_("name"), max_length=100)
    description = models.TextField(
        _("description"), blank=True, help_text=_("Shown to players when they pick a department.")
    )
    parent = models.ForeignKey(
        "self",
        verbose_name=_("parent department"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        help_text=_("Staff of the parent department can see all tickets of this department."),
    )
    groups = models.ManyToManyField(
        Group,
        verbose_name=_("staff groups"),
        blank=True,
        related_name="aa_ticket_departments",
        help_text=_("Members of these groups are staff of this department."),
    )
    submit_states = models.ManyToManyField(
        State,
        verbose_name=_("states allowed to submit"),
        blank=True,
        related_name="+",
        help_text=_("Leave both lists empty to allow everyone who can use tickets."),
    )
    submit_groups = models.ManyToManyField(
        Group,
        verbose_name=_("groups allowed to submit"),
        blank=True,
        related_name="+",
    )
    accepts_submissions = models.BooleanField(
        _("accepts tickets from players"),
        default=True,
        help_text=_("When off, tickets can only reach this department by transfer or invitation."),
    )
    is_active = models.BooleanField(_("active"), default=True)
    order = models.IntegerField(_("order"), default=0)
    webhook_url = models.CharField(_("Discord webhook"), max_length=255, blank=True)
    mention_role_ids = models.CharField(
        _("Discord role IDs to mention"),
        max_length=255,
        blank=True,
        validators=[validate_role_ids],
    )
    last_webhook_error = models.CharField(max_length=255, blank=True)
    last_webhook_error_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()
        ordering = ("order", "name")
        verbose_name = _("department")
        verbose_name_plural = _("departments")

    def __str__(self):
        return self.name

    def ancestors(self):
        """Parent, grandparent, ... nearest first. Stops on a cycle."""
        result = []
        seen = {self.pk}
        current = self.parent
        while current is not None and current.pk not in seen:
            result.append(current)
            seen.add(current.pk)
            current = current.parent
        return result

    def descendant_ids(self):
        children_of = {}
        for pk, parent_id in Department.objects.values_list("pk", "parent_id"):
            children_of.setdefault(parent_id, []).append(pk)
        result = set()
        stack = list(children_of.get(self.pk, []))
        while stack:
            pk = stack.pop()
            if pk in result or pk == self.pk:
                continue
            result.add(pk)
            stack.extend(children_of.get(pk, []))
        return result

    def clean(self):
        super().clean()
        if self.parent_id is None:
            return
        if self.pk and self.parent_id == self.pk:
            raise ValidationError({"parent": _("A department cannot be its own parent.")})
        if self.pk and self.parent_id in self.descendant_ids():
            raise ValidationError(
                {"parent": _("This parent would create a loop. Pick a department above this one.")}
            )

    def mention_role_id_list(self):
        return [int(x) for x in re.findall(r"\d+", self.mention_role_ids or "")]

    def masked_webhook(self):
        if not self.webhook_url:
            return ""
        return "…" + self.webhook_url[-4:]


class Priority(models.Model):
    name = models.CharField(_("name"), max_length=50)
    color = models.CharField(_("colour"), max_length=20, choices=PRIORITY_COLORS, default="primary")
    order = models.IntegerField(_("order"), default=0, help_text=_("Higher means more urgent."))
    mention_on_new = models.BooleanField(
        _("mention roles for new tickets"),
        default=True,
        help_text=_("When on, new tickets with this priority mention the department's Discord roles."),
    )
    remind_after_minutes = models.PositiveIntegerField(
        _("remind after (minutes)"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=_("Mention the department again if nobody claims the ticket in time. Leave empty to turn off."),
    )
    escalate_after_minutes = models.PositiveIntegerField(
        _("escalate after (minutes)"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=_("Mention the parent department if nobody claims the ticket in time. Leave empty to turn off."),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        default_permissions = ()
        ordering = ("order", "name")
        verbose_name = _("priority")
        verbose_name_plural = _("priorities")

    def __str__(self):
        return self.name


class Category(models.Model):
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="categories", verbose_name=_("department")
    )
    name = models.CharField(_("name"), max_length=100)
    template = models.TextField(
        _("template"), blank=True, help_text=_("Pre-filled into the ticket text when a player picks this category.")
    )
    order = models.IntegerField(_("order"), default=0)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        default_permissions = ()
        ordering = ("order", "name")
        verbose_name = _("category")
        verbose_name_plural = _("categories")

    def __str__(self):
        return self.name


class CannedReply(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="canned_replies",
        verbose_name=_("department"),
        help_text=_("Leave empty to share with all departments."),
    )
    title = models.CharField(_("title"), max_length=100)
    body = models.TextField(_("text"))

    class Meta:
        default_permissions = ()
        ordering = ("title",)
        verbose_name = _("canned reply")
        verbose_name_plural = _("canned replies")

    def __str__(self):
        return self.title


class TicketSettings(SingletonModel):
    autoclose_days = models.PositiveIntegerField(
        _("auto-close after (days)"),
        default=7,
        validators=[MinValueValidator(1)],
        help_text=_("Tickets waiting for the requester are closed automatically after this many days without a reply."),
    )
    autoclose_warning_hours = models.PositiveIntegerField(
        _("warn before auto-close (hours)"),
        default=24,
        help_text=_("The requester and the assignee are warned this many hours before a ticket closes automatically."),
    )
    reopen_days = models.PositiveIntegerField(
        _("requester can reopen for (days)"),
        default=7,
        help_text=_("For this many days after closing, the requester can reopen the ticket. Staff can always reopen."),
    )
    max_open_tickets = models.PositiveIntegerField(
        _("open tickets per person"),
        default=5,
        validators=[MinValueValidator(1)],
        help_text=_("A person cannot submit a new ticket while this many of their tickets are still open."),
    )
    max_image_mb = models.PositiveIntegerField(
        _("maximum image size (MB)"), default=5, validators=[MinValueValidator(1)]
    )
    attachment_retention_days = models.PositiveIntegerField(
        _("delete images after (days)"),
        null=True,
        blank=True,
        help_text=_("Images of tickets closed longer than this are deleted. Leave empty to keep them forever."),
    )
    discord_dm_enabled = models.BooleanField(
        _("Discord direct messages"),
        default=True,
        help_text=_("When on and aa-discordbot is installed, people also get notifications as Discord direct messages."),
    )

    class Meta:
        default_permissions = ()
        verbose_name = _("ticket settings")

    def __str__(self):
        return str(_("Ticket settings"))


class UserPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="aa_ticket_pref")
    discord_dm_enabled = models.BooleanField(_("Discord direct messages"), default=True)

    class Meta:
        default_permissions = ()

    @classmethod
    def for_user(cls, user):
        obj, _created = cls.objects.get_or_create(user=user)
        return obj
