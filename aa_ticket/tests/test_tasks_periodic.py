import os
from datetime import timedelta
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from aa_ticket import services
from aa_ticket.constants import ClosedReason, Event, MessageKind, Status
from aa_ticket.models import Attachment, Ticket, TicketMessage, TicketSettings
from aa_ticket.tasks import check_auto_close, check_unclaimed, cleanup_attachments

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def iso(dt):
    return dt.isoformat()


class PeriodicFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g = make_group("Diplomats")
        cls.top = make_department("Leadership")
        cls.dip = make_department("Diplomacy", groups=[cls.g], parent=cls.top)
        cls.log = make_department("Logistics")
        cls.requester = make_user("Pilot A")
        cls.staff = make_user("Diplomat B", groups=[cls.g])

    def setUp(self):
        self.dispatch = patch("aa_ticket.services.dispatch").start()
        self.addCleanup(patch.stopall)

    def ticket(self, prio="urgent", department=None):
        return services.create_ticket(
            fresh(self.requester), department or self.dip, priority(prio), "Help", "Body"
        )

    def events(self, ticket, event):
        return TicketMessage.objects.filter(ticket=ticket, event_type=event).count()

    def run_on_commit(self, func, *args):
        with self.captureOnCommitCallbacks(execute=True):
            func(*args)


class TestUnclaimed(PeriodicFixture):
    def test_unclaimed_reminder_once(self):
        t = self.ticket("urgent")  # remind after 30, escalate after 120
        now = t.open_since + timedelta(minutes=31)
        check_unclaimed(iso(now))
        check_unclaimed(iso(now + timedelta(minutes=5)))
        self.assertEqual(self.events(t, Event.UNCLAIMED_REMINDER), 1)
        self.assertIsNotNone(fresh(t).reminded_at)
        self.assertEqual(self.events(t, Event.ESCALATION_REMINDER), 0)

    def test_not_due_yet(self):
        t = self.ticket("urgent")
        check_unclaimed(iso(t.open_since + timedelta(minutes=29)))
        self.assertEqual(self.events(t, Event.UNCLAIMED_REMINDER), 0)

    def test_escalation_reminder_after_threshold(self):
        t = self.ticket("urgent")
        check_unclaimed(iso(t.open_since + timedelta(minutes=121)))
        self.assertEqual(self.events(t, Event.ESCALATION_REMINDER), 1)
        check_unclaimed(iso(t.open_since + timedelta(minutes=200)))
        self.assertEqual(self.events(t, Event.ESCALATION_REMINDER), 1)

    def test_escalation_reminder_requires_parent(self):
        t = self.ticket("urgent", department=self.log)
        check_unclaimed(iso(t.open_since + timedelta(minutes=121)))
        self.assertEqual(self.events(t, Event.ESCALATION_REMINDER), 0)
        self.assertEqual(self.events(t, Event.UNCLAIMED_REMINDER), 1)

    def test_low_priority_never_reminded(self):
        t = self.ticket("low")
        check_unclaimed(iso(t.open_since + timedelta(days=30)))
        self.assertEqual(self.events(t, Event.UNCLAIMED_REMINDER), 0)

    def test_claimed_ticket_not_reminded(self):
        t = self.ticket("urgent")
        services.claim(fresh(self.staff), t)
        check_unclaimed(iso(t.open_since + timedelta(minutes=300)))
        self.assertEqual(self.events(t, Event.UNCLAIMED_REMINDER), 0)

    def test_transfer_resets_reminders(self):
        t = self.ticket("urgent")
        check_unclaimed(iso(t.open_since + timedelta(minutes=31)))
        services.transfer(fresh(self.staff), fresh(t), self.log)
        t = fresh(t)
        check_unclaimed(iso(t.open_since + timedelta(minutes=31)))
        self.assertEqual(self.events(t, Event.UNCLAIMED_REMINDER), 2)

    def test_reminder_dispatched(self):
        t = self.ticket("urgent")
        self.dispatch.reset_mock()
        self.run_on_commit(check_unclaimed, iso(t.open_since + timedelta(minutes=31)))
        self.assertEqual(self.dispatch.call_args[0][0], Event.UNCLAIMED_REMINDER)


class TestAutoClose(PeriodicFixture):
    def claimed_with_staff_reply(self):
        t = self.ticket("normal")
        services.claim(fresh(self.staff), t)
        services.add_reply(fresh(self.staff), fresh(t), "Please confirm.")
        return fresh(t)

    def test_open_ticket_never_autoclosed(self):
        t = self.ticket("normal")
        check_auto_close(iso(timezone.now() + timedelta(days=60)))
        self.assertEqual(fresh(t).status, Status.OPEN)
        self.assertEqual(self.events(t, Event.AUTOCLOSE_WARNING), 0)

    def test_autoclose_warning_then_close(self):
        t = self.claimed_with_staff_reply()
        base = t.last_reply_at
        check_auto_close(iso(base + timedelta(days=5)))
        self.assertEqual(self.events(t, Event.AUTOCLOSE_WARNING), 0)
        check_auto_close(iso(base + timedelta(days=6, hours=1)))
        check_auto_close(iso(base + timedelta(days=6, hours=2)))
        self.assertEqual(self.events(t, Event.AUTOCLOSE_WARNING), 1)
        self.assertEqual(fresh(t).status, Status.IN_PROGRESS)
        check_auto_close(iso(base + timedelta(days=7, minutes=1)))
        t = fresh(t)
        self.assertEqual(t.status, Status.CLOSED)
        self.assertEqual(t.closed_reason, ClosedReason.AUTO)

    def test_new_reply_resets_warning(self):
        t = self.claimed_with_staff_reply()
        check_auto_close(iso(t.last_reply_at + timedelta(days=6, hours=1)))
        self.assertIsNotNone(fresh(t).autoclose_warned_at)
        services.add_reply(fresh(self.staff), fresh(t), "Still there?")
        t = fresh(t)
        self.assertIsNone(t.autoclose_warned_at)
        check_auto_close(iso(t.last_reply_at + timedelta(days=6, hours=1)))
        self.assertEqual(self.events(t, Event.AUTOCLOSE_WARNING), 2)

    def test_requester_last_reply_reminds_staff_not_close(self):
        t = self.ticket("normal")
        services.claim(fresh(self.staff), t)
        t = fresh(t)
        check_auto_close(iso(t.last_reply_at + timedelta(days=8)))
        check_auto_close(iso(t.last_reply_at + timedelta(days=9)))
        t = fresh(t)
        self.assertEqual(t.status, Status.IN_PROGRESS)
        self.assertEqual(self.events(t, Event.AUTOCLOSE_WARNING), 0)
        self.assertEqual(self.events(t, Event.AWAITING_STAFF_REMINDER), 1)

    def test_flags_persist_across_runs(self):
        t = self.claimed_with_staff_reply()
        check_auto_close(iso(t.last_reply_at + timedelta(days=6, hours=1)))
        # simulate a restart: nothing in memory, only database state
        Ticket.objects.get(pk=t.pk)
        check_auto_close(iso(t.last_reply_at + timedelta(days=6, hours=3)))
        self.assertEqual(self.events(t, Event.AUTOCLOSE_WARNING), 1)

    def test_custom_settings(self):
        s = TicketSettings.get_solo()
        s.autoclose_days = 2
        s.autoclose_warning_hours = 0
        s.save()
        t = self.claimed_with_staff_reply()
        check_auto_close(iso(t.last_reply_at + timedelta(days=2, minutes=1)))
        self.assertEqual(fresh(t).status, Status.CLOSED)


class TestCleanup(PeriodicFixture):
    def closed_with_file(self, days_ago):
        t = self.ticket("normal")
        msg = TicketMessage.objects.filter(ticket=t, kind=MessageKind.REPLY).first()
        att = Attachment(message=msg, original_name="a.png", size=3, content_type="image/png")
        att.file.save("x.png", ContentFile(b"abc"), save=True)
        services.close(fresh(self.requester), fresh(t), ClosedReason.REQUESTER)
        Ticket.objects.filter(pk=t.pk).update(closed_at=timezone.now() - timedelta(days=days_ago))
        return att

    def test_cleanup_disabled_by_default(self):
        att = self.closed_with_file(400)
        cleanup_attachments()
        self.assertTrue(Attachment.objects.filter(pk=att.pk).exists())
        self.assertTrue(os.path.exists(att.file.path))

    def test_cleanup_deletes_files(self):
        s = TicketSettings.get_solo()
        s.attachment_retention_days = 30
        s.save()
        old = self.closed_with_file(31)
        recent = self.closed_with_file(10)
        path = old.file.path
        cleanup_attachments()
        self.assertFalse(Attachment.objects.filter(pk=old.pk).exists())
        self.assertFalse(os.path.exists(path))
        self.assertTrue(Attachment.objects.filter(pk=recent.pk).exists())
