"""Erase one person's ticket data, for example after a data protection request.

Without --yes nothing is changed; the command only lists what would happen.

Only data that clearly belongs to the person is touched: the tickets they submitted, the
author of their messages and events, and the event fields that name them as assignee (found by
their user ID, so older character names are covered too). Nothing is changed by matching text,
so departments, priorities or reasons that happen to have the same name stay as they are.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ...constants import Event, Status
from ...models import Attachment, Department, EscalationRequest, Ticket, TicketMessage, UserPreference

ERASED = "[deleted user]"
# event_data keys that hold a user's primary key; the name of that user is in "assignee"
USER_ID_KEYS = ("assignee_id", "previous_assignee_id")


def _erase_from_event(message, user_pk):
    """Return the event data with the person removed, or None if the event does not name them."""
    data = dict(message.event_data or {})
    changed = False
    names_them = (
        message.author_id == user_pk and message.event_type == Event.CLAIMED
    ) or data.get("assignee_id") == user_pk
    if names_them and "assignee" in data:
        data["assignee"] = ERASED
        changed = True
    for key in USER_ID_KEYS:
        if data.get(key) == user_pk:
            data[key] = None
            changed = True
    if message.author_id == user_pk and message.kind == "event":
        data["author_erased"] = True
        changed = True
    return data if changed else None


def _related_events(user_pk, exclude_ticket_ids):
    by_id = Q(event_data__assignee_id=user_pk) | Q(event_data__previous_assignee_id=user_pk)
    return (
        TicketMessage.objects.filter(kind="event")
        .filter(Q(author_id=user_pk) | by_id)
        .exclude(ticket__in=exclude_ticket_ids)
    )


class Command(BaseCommand):
    help = (
        "Erase a person's ticket data: delete the tickets they submitted (with images) and remove "
        "their name from other tickets. Without --yes only shows what would happen."
    )

    def add_arguments(self, parser):
        parser.add_argument("username", help="Alliance Auth username of the person")
        parser.add_argument("--yes", action="store_true", help="Really erase. Without it nothing is changed.")

    def handle(self, *args, username, yes, **options):
        user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"No user with the username {username!r}.")

        own_ids = list(Ticket.objects.filter(requester=user).values_list("pk", flat=True))
        images = Attachment.objects.filter(message__ticket__in=own_ids).count()
        messages = TicketMessage.objects.filter(author=user).exclude(ticket__in=own_ids).exclude(kind="event").count()
        events = _related_events(user.pk, own_ids).count()
        assigned = Ticket.objects.filter(assignee=user).exclude(pk__in=own_ids).count()

        self.stdout.write(f"Person: {username}")
        self.stdout.write(f"- {len(own_ids)} ticket(s) they submitted will be deleted, with {images} image(s).")
        self.stdout.write(f"- {messages} message(s) they wrote in other tickets will show 'Deleted user'.")
        self.stdout.write(f"- {events} event(s) in other tickets will no longer name them.")
        self.stdout.write(f"- {assigned} other ticket(s) assigned to them lose their assignee.")
        self.stdout.write(
            "Kept: the text and images of messages they wrote in other people's tickets, Alliance Auth "
            "notifications, and Discord messages already sent."
        )
        if user.is_active:
            self.stdout.write(
                self.style.WARNING(
                    "The account is still active. Deactivate it in Alliance Auth first and wait a few minutes, "
                    "so no new ticket data appears and queued Discord messages have been sent. "
                    "Erasing an active account is refused."
                )
            )
        elif Department.objects.filter(groups__in=user.groups.all()).exists():
            self.stdout.write(
                self.style.WARNING("The account is still in a department staff group. Remove it from those groups too.")
            )
        if yes and user.is_active:
            raise CommandError("The account is still active. Deactivate it first, then run the command again.")
        if not yes:
            self.stdout.write("Nothing was changed. Run again with --yes to erase.")
            return

        with transaction.atomic():
            # Lock the person, so they cannot submit a ticket while we erase (create_ticket locks too).
            User.objects.select_for_update().get(pk=user.pk)
            self._erase(user)
        self.stdout.write(self.style.SUCCESS("Erased. The account can now be deleted in Alliance Auth if wanted."))

    def _erase(self, user):
        from ...services import _emit

        own_ids = list(Ticket.objects.filter(requester=user).values_list("pk", flat=True))
        files = [
            (attachment.file.storage, attachment.file.name)
            for attachment in Attachment.objects.filter(message__ticket__in=own_ids)
            if attachment.file
        ]
        Ticket.objects.filter(pk__in=own_ids).delete()  # messages, images and escalations go with them

        def remove_files():
            for storage, name in files:
                try:
                    storage.delete(name)
                except OSError:
                    pass

        transaction.on_commit(remove_files)

        for message in _related_events(user.pk, own_ids).iterator():
            data = _erase_from_event(message, user.pk)
            if data is not None:
                TicketMessage.objects.filter(pk=message.pk).update(event_data=data)
        TicketMessage.objects.filter(author=user).exclude(ticket__in=own_ids).update(author=None)

        now = timezone.now()
        for ticket in Ticket.objects.filter(assignee=user).exclude(pk__in=own_ids).select_for_update():
            if ticket.status == Status.IN_PROGRESS:
                Ticket.objects.filter(pk=ticket.pk).update(
                    status=Status.OPEN,
                    assignee=None,
                    open_since=now,
                    reminded_at=None,
                    escalated_at=None,
                    last_reply_at=now,
                    last_reply_by_staff=False,
                    autoclose_warned_at=None,
                    staff_reminded_at=None,
                )
                _emit(Ticket.objects.get(pk=ticket.pk), Event.ASSIGNEE_LEFT)
            else:
                Ticket.objects.filter(pk=ticket.pk).update(assignee=None)
        Ticket.objects.filter(closed_by=user).update(closed_by=None)
        EscalationRequest.objects.filter(requested_by=user).update(requested_by=None)
        UserPreference.objects.filter(user=user).delete()
