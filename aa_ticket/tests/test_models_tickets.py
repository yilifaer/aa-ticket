from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from aa_ticket.constants import MessageKind, Status
from aa_ticket.models import Ticket, TicketMessage

from .factories import make_department, make_user, priority


def make_ticket(requester, department, prio="normal", **kwargs):
    now = timezone.now()
    return Ticket.objects.create(
        title=kwargs.pop("title", "Help"),
        requester=requester,
        department=department,
        priority=priority(prio),
        open_since=now,
        last_reply_at=now,
        **kwargs,
    )


class TestTicketModels(TestCase):
    def setUp(self):
        self.user = make_user("Pilot A")
        self.dept = make_department("Diplomacy")
        self.ticket = make_ticket(self.user, self.dept)

    def test_display_number(self):
        self.assertEqual(self.ticket.display_number, f"#{self.ticket.pk}")
        self.assertEqual(self.ticket.status, Status.OPEN)

    def test_department_with_tickets_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.dept.delete()

    def test_priority_in_use_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            priority("normal").delete()

    def test_message_ordering_is_chronological(self):
        first = TicketMessage.objects.create(ticket=self.ticket, author=self.user, kind=MessageKind.REPLY, body="1")
        second = TicketMessage.objects.create(ticket=self.ticket, author=self.user, kind=MessageKind.REPLY, body="2")
        self.assertEqual(list(self.ticket.messages.all()), [first, second])
