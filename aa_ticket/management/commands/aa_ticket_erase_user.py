"""Erase one person's ticket data, for example after a data protection request.

Without --yes nothing is changed; the command only lists what would happen.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from ...constants import Event, Status
from ...models import Attachment, EscalationRequest, Ticket, TicketMessage, UserPreference
from ...utils import display_name

ERASED = "[deleted user]"


def _scrub(value, names, user_pk):
    """Replace the person's names and IDs inside an event's data."""
    if isinstance(value, dict):
        return {
            key: (None if key.endswith("_id") and item == user_pk else _scrub(item, names, user_pk))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item, names, user_pk) for item in value]
    if isinstance(value, str) and value in names:
        return ERASED
    return value


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
        names = {name for name in (display_name(user), user.username) if name}

        own = Ticket.objects.filter(requester=user)
        own_ids = list(own.values_list("pk", flat=True))
        images = Attachment.objects.filter(message__ticket__in=own_ids)
        others_messages = TicketMessage.objects.filter(author=user).exclude(ticket__in=own_ids)
        assigned = Ticket.objects.filter(assignee=user).exclude(pk__in=own_ids)

        self.stdout.write(f"Person: {username} ({', '.join(sorted(names))})")
        self.stdout.write(f"- {len(own_ids)} ticket(s) they submitted will be deleted, with {images.count()} image(s).")
        self.stdout.write(
            f"- {others_messages.count()} message(s) and event(s) in other tickets will show 'Deleted user'."
        )
        self.stdout.write(f"- {assigned.count()} other ticket(s) assigned to them lose their assignee.")
        self.stdout.write("Messages they wrote in other people's tickets keep their text.")
        if not yes:
            self.stdout.write("Nothing was changed. Run again with --yes to erase.")
            return

        with transaction.atomic():
            self._erase(user, names, own_ids, images, others_messages, assigned)
        self.stdout.write(self.style.SUCCESS("Erased. The account can now be deleted in Alliance Auth if wanted."))

    def _erase(self, user, names, own_ids, images, others_messages, assigned):
        from ...services import _emit

        files = [(attachment.file.storage, attachment.file.name) for attachment in images if attachment.file]
        Ticket.objects.filter(pk__in=own_ids).delete()  # messages, images and escalations go with them

        def remove_files():
            for storage, name in files:
                try:
                    storage.delete(name)
                except OSError:
                    pass

        transaction.on_commit(remove_files)

        for message in others_messages.select_for_update():
            data = _scrub(message.event_data or {}, names, user.pk)
            if message.kind == "event":
                data["author_erased"] = True
            TicketMessage.objects.filter(pk=message.pk).update(author=None, event_data=data)
        for message in TicketMessage.objects.filter(kind="event").exclude(ticket__in=own_ids).iterator():
            data = message.event_data or {}
            scrubbed = _scrub(data, names, user.pk)
            if scrubbed != data:
                TicketMessage.objects.filter(pk=message.pk).update(event_data=scrubbed)

        now = timezone.now()
        for ticket in assigned.select_for_update():
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
