import re

from solo.models import SingletonModel

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import pgettext_lazy

from allianceauth.authentication.models import State

from ..constants import CHANNEL_LANGUAGES, DM_LANGUAGE_MODES, PRIORITY_COLORS

_ROLE_IDS_RE = re.compile(r"^\s*[0-9]+(\s*[,\s]\s*[0-9]+)*\s*$")


def validate_role_ids(value):
    if value and not _ROLE_IDS_RE.match(value):
        raise ValidationError(
            pgettext_lazy("aa_ticket", "Enter Discord role IDs as numbers, separated by commas or spaces.")
        )


class General(models.Model):
    """Holds the app's permissions. Has no table."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("basic_access", "Can submit and view own tickets"),
            ("view_all", "Can view and handle all tickets"),
            ("manage", "Can manage ticket settings"),
        )


class Department(models.Model):
    name = models.CharField(pgettext_lazy("aa_ticket", "name"), max_length=100)
    description = models.TextField(
        pgettext_lazy("aa_ticket", "description"), blank=True, help_text=pgettext_lazy("aa_ticket", "Shown to players when they pick a department.")
    )
    parent = models.ForeignKey(
        "self",
        verbose_name=pgettext_lazy("aa_ticket", "parent department"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        help_text=pgettext_lazy("aa_ticket", "Staff of the parent department can see all tickets of this department."),
    )
    groups = models.ManyToManyField(
        Group,
        verbose_name=pgettext_lazy("aa_ticket", "staff groups"),
        blank=True,
        related_name="aa_ticket_departments",
        help_text=pgettext_lazy("aa_ticket", "Members of these groups are staff of this department."),
    )
    submit_states = models.ManyToManyField(
        State,
        verbose_name=pgettext_lazy("aa_ticket", "states allowed to submit"),
        blank=True,
        related_name="+",
        help_text=pgettext_lazy("aa_ticket", "Leave both lists empty to allow everyone who can use tickets."),
    )
    submit_groups = models.ManyToManyField(
        Group,
        verbose_name=pgettext_lazy("aa_ticket", "groups allowed to submit"),
        blank=True,
        related_name="+",
    )
    restrict_submissions = models.BooleanField(
        default=False,
        editable=False,
        help_text="Set when states or groups allowed to submit were chosen. Stays on if they are deleted later, "
        "so the department does not silently open up to everyone.",
    )
    accepts_submissions = models.BooleanField(
        pgettext_lazy("aa_ticket", "accepts tickets from players"),
        default=True,
        help_text=pgettext_lazy("aa_ticket", "When off, tickets can only reach this department by transfer or invitation."),
    )
    is_active = models.BooleanField(pgettext_lazy("aa_ticket", "active"), default=True)
    order = models.IntegerField(pgettext_lazy("aa_ticket", "order"), default=0)
    webhook_url = models.CharField(pgettext_lazy("aa_ticket", "Discord webhook"), max_length=255, blank=True)
    mention_role_ids = models.CharField(
        pgettext_lazy("aa_ticket", "Discord role IDs to mention"),
        max_length=255,
        blank=True,
        validators=[validate_role_ids],
    )
    last_webhook_error = models.CharField(max_length=255, blank=True)
    last_webhook_error_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()
        ordering = ("order", "name")
        verbose_name = pgettext_lazy("aa_ticket", "department")
        verbose_name_plural = pgettext_lazy("aa_ticket", "departments")

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
            raise ValidationError({"parent": pgettext_lazy("aa_ticket", "A department cannot be its own parent.")})
        if self.pk and self.parent_id in self.descendant_ids():
            raise ValidationError(
                {"parent": pgettext_lazy("aa_ticket", "This parent would create a loop. Pick a department above this one.")}
            )

    def mention_role_id_list(self):
        return [int(x) for x in re.findall(r"[0-9]+", self.mention_role_ids or "")]

    def masked_webhook(self):
        if not self.webhook_url:
            return ""
        return "…" + self.webhook_url[-4:]


class Priority(models.Model):
    name = models.CharField(pgettext_lazy("aa_ticket", "name"), max_length=50)
    color = models.CharField(pgettext_lazy("aa_ticket", "colour"), max_length=20, choices=PRIORITY_COLORS, default="primary")
    order = models.IntegerField(pgettext_lazy("aa_ticket", "order"), default=0, help_text=pgettext_lazy("aa_ticket", "Higher means more urgent."))
    mention_on_new = models.BooleanField(
        pgettext_lazy("aa_ticket", "mention roles for new tickets"),
        default=True,
        help_text=pgettext_lazy("aa_ticket", "When on, new tickets with this priority mention the department's Discord roles."),
    )
    remind_after_minutes = models.PositiveIntegerField(
        pgettext_lazy("aa_ticket", "remind after (minutes)"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=pgettext_lazy("aa_ticket", "Mention the department again if nobody claims the ticket in time. Leave empty to turn off."),
    )
    escalate_after_minutes = models.PositiveIntegerField(
        pgettext_lazy("aa_ticket", "escalate after (minutes)"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=pgettext_lazy("aa_ticket", "Mention the parent department if nobody claims the ticket in time. Leave empty to turn off."),
    )
    is_urgent = models.BooleanField(
        pgettext_lazy("aa_ticket", "counts as urgent"),
        default=False,
        help_text=pgettext_lazy("aa_ticket", "Urgent tickets are listed first and highlighted on the overview and the Alliance Auth dashboard."),
    )
    is_active = models.BooleanField(pgettext_lazy("aa_ticket", "active"), default=True)

    class Meta:
        default_permissions = ()
        ordering = ("order", "name")
        verbose_name = pgettext_lazy("aa_ticket", "priority")
        verbose_name_plural = pgettext_lazy("aa_ticket", "priorities")

    def __str__(self):
        return self.name


class Category(models.Model):
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="categories", verbose_name=pgettext_lazy("aa_ticket", "department")
    )
    name = models.CharField(pgettext_lazy("aa_ticket", "name"), max_length=100)
    template = models.TextField(
        pgettext_lazy("aa_ticket", "template"), blank=True, help_text=pgettext_lazy("aa_ticket", "Pre-filled into the ticket text when a player picks this category.")
    )
    order = models.IntegerField(pgettext_lazy("aa_ticket", "order"), default=0)
    is_active = models.BooleanField(pgettext_lazy("aa_ticket", "active"), default=True)

    class Meta:
        default_permissions = ()
        ordering = ("order", "name")
        verbose_name = pgettext_lazy("aa_ticket", "category")
        verbose_name_plural = pgettext_lazy("aa_ticket", "categories")

    def __str__(self):
        return self.name


class CannedReply(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="canned_replies",
        verbose_name=pgettext_lazy("aa_ticket", "department"),
        help_text=pgettext_lazy("aa_ticket", "Leave empty to share with all departments."),
    )
    title = models.CharField(pgettext_lazy("aa_ticket", "title"), max_length=100)
    body = models.TextField(pgettext_lazy("aa_ticket", "text"))

    class Meta:
        default_permissions = ()
        ordering = ("title",)
        verbose_name = pgettext_lazy("aa_ticket", "canned reply")
        verbose_name_plural = pgettext_lazy("aa_ticket", "canned replies")

    def __str__(self):
        return self.title


class TicketSettings(SingletonModel):
    autoclose_days = models.PositiveIntegerField(
        pgettext_lazy("aa_ticket", "auto-close after (days)"),
        default=7,
        validators=[MinValueValidator(1)],
        help_text=pgettext_lazy("aa_ticket", "Tickets waiting for the requester are closed automatically after this many days without a reply."),
    )
    autoclose_warning_hours = models.PositiveIntegerField(
        pgettext_lazy("aa_ticket", "warn before auto-close (hours)"),
        default=24,
        help_text=pgettext_lazy("aa_ticket", "The requester and the assignee are warned this many hours before a ticket closes automatically."),
    )
    reopen_days = models.PositiveIntegerField(
        pgettext_lazy("aa_ticket", "requester can reopen for (days)"),
        default=7,
        help_text=pgettext_lazy("aa_ticket", "For this many days after closing, the requester can reopen the ticket. Staff can always reopen."),
    )
    max_open_tickets = models.PositiveIntegerField(
        pgettext_lazy("aa_ticket", "open tickets per person"),
        default=5,
        validators=[MinValueValidator(1)],
        help_text=pgettext_lazy("aa_ticket", "A person cannot submit a new ticket while this many of their tickets are still open."),
    )
    max_new_tickets_per_hour = models.PositiveIntegerField(
        pgettext_lazy("aa_ticket", "new tickets per person per hour"),
        default=5,
        help_text=pgettext_lazy(
            "aa_ticket", "Limits how often one person can submit (and so ping a department). 0 means no limit."
        ),
    )
    max_image_mb = models.PositiveIntegerField(
        pgettext_lazy("aa_ticket", "maximum image size (MB)"), default=5, validators=[MinValueValidator(1)]
    )
    attachment_retention_days = models.PositiveIntegerField(
        pgettext_lazy("aa_ticket", "delete images after (days)"),
        null=True,
        blank=True,
        help_text=pgettext_lazy("aa_ticket", "Images of tickets closed longer than this are deleted. Leave empty to keep them forever."),
    )
    discord_dm_enabled = models.BooleanField(
        pgettext_lazy("aa_ticket", "Discord direct messages"),
        default=True,
        help_text=pgettext_lazy("aa_ticket", "When on and aa-discordbot is installed, people also get notifications as Discord direct messages."),
    )
    channel_language = models.CharField(
        pgettext_lazy("aa_ticket", "Language of Discord channel messages"),
        max_length=10,
        choices=CHANNEL_LANGUAGES,
        default="en",
        help_text=pgettext_lazy("aa_ticket", "All messages posted to department channels use this language."),
    )
    dm_language_mode = models.CharField(
        pgettext_lazy("aa_ticket", "Language of Discord direct messages"),
        max_length=10,
        choices=DM_LANGUAGE_MODES,
        default="personal",
        help_text=pgettext_lazy("aa_ticket", "Direct messages can follow each person's language setting in Alliance Auth, or use the channel language."),
    )

    class Meta:
        default_permissions = ()
        verbose_name = pgettext_lazy("aa_ticket", "ticket settings")

    def __str__(self):
        return str(pgettext_lazy("aa_ticket", "Ticket settings"))


class UserPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="aa_ticket_pref")
    discord_dm_enabled = models.BooleanField(pgettext_lazy("aa_ticket", "Discord direct messages"), default=True)

    class Meta:
        default_permissions = ()

    @classmethod
    def for_user(cls, user):
        """The saved preference, or the defaults (not saved) if the person never changed anything."""
        return cls.objects.filter(user=user).first() or cls(user=user)
