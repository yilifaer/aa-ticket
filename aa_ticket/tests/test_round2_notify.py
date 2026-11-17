from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from aa_ticket import services
from aa_ticket.auth_hooks import badge_cache_key
from aa_ticket.constants import ClosedReason, Event, Status
from aa_ticket.models import Ticket
from aa_ticket.notifications import dispatch
from aa_ticket.tasks import check_unclaimed

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g = make_group("Diplomats")
        cls.dip = make_department("Diplomacy", groups=[cls.g])
        cls.requester = make_user("Pilot A")
        cls.staff = make_user("Diplomat B", groups=[cls.g])
        cls.staff2 = make_user("Diplomat C", groups=[cls.g])

    def setUp(self):
        self.notify = patch("aa_ticket.notifications.notify").start()
        patch("aa_ticket.notifications.send_webhook").start()
        patch("aa_ticket.notifications.send_dm").start()
        self.addCleanup(patch.stopall)

    def claimed(self):
        with self.captureOnCommitCallbacks(execute=False):
            t = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "Body")
            services.claim(fresh(self.staff), t)
        return fresh(t)

    def users(self):
        return sorted(c.kwargs["user"].pk for c in self.notify.call_args_list)


class TestMoreRecipients(Fixture):
    def test_requester_close_and_reopen_notify_assignee(self):
        t = self.claimed()
        dispatch(Event.CLOSED, t.pk, self.requester.pk, {})
        self.assertEqual(self.users(), [self.staff.pk])
        self.notify.reset_mock()
        dispatch(Event.REOPENED, t.pk, self.requester.pk, {})
        self.assertEqual(self.users(), [self.staff.pk])

    def test_colleague_reply_notifies_assignee(self):
        t = self.claimed()
        dispatch(Event.REPLIED, t.pk, self.staff2.pk, {"by_staff": True})
        self.assertEqual(self.users(), sorted([self.requester.pk, self.staff.pk]))

    def test_close_with_final_reply_sends_one_notification(self):
        t = self.claimed()
        with self.captureOnCommitCallbacks(execute=True):
            services.close(fresh(self.staff), t, ClosedReason.STAFF, final_reply="Done")
        self.assertEqual(self.users(), [self.requester.pk])

    def test_requester_without_basic_access_not_notified(self):
        t = self.claimed()
        self.requester.user_permissions.clear()
        dispatch(Event.CLOSED, t.pk, self.staff.pk, {})
        self.assertEqual(self.users(), [])


class TestAssigneeLeft(Fixture):
    def test_ticket_returns_to_unclaimed_when_assignee_leaves(self):
        t = self.claimed()
        self.staff.groups.remove(self.g)
        with patch("aa_ticket.services.dispatch"):
            check_unclaimed()
        t = fresh(t)
        self.assertEqual(t.status, Status.OPEN)
        self.assertIsNone(t.assignee)
        self.assertTrue(t.messages.filter(event_type=Event.ASSIGNEE_LEFT).exists())


class TestBadgeInvalidated(Fixture):
    def test_claim_clears_department_badges(self):
        t = self.claimed()
        cache.set(badge_cache_key(self.staff2), 5, 60)
        dispatch(Event.CLAIMED, t.pk, self.staff.pk, {})
        self.assertIsNone(cache.get(badge_cache_key(self.staff2)))
