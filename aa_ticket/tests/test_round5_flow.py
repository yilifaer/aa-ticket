"""Regression tests for the whole-app review (0.4.1): lifecycle, tasks, notifications."""

from datetime import timedelta
from unittest.mock import patch

import requests

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from aa_ticket import access, services
from aa_ticket.constants import ClosedReason, Event, Status
from aa_ticket.models import Ticket, TicketSettings
from aa_ticket.notifications import dispatch
from aa_ticket.tasks import check_auto_close, check_unclaimed, send_webhook

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_top = make_group("Top")
        cls.g_lead = make_group("Lead")
        cls.g_dip = make_group("Dip")
        cls.g_fc = make_group("FC")
        cls.top = make_department("Top", groups=[cls.g_top])
        cls.lead = make_department("Lead", groups=[cls.g_lead], parent=cls.top)
        cls.dip = make_department("Dip", groups=[cls.g_dip], parent=cls.lead)
        cls.fc = make_department("FC", groups=[cls.g_fc])
        cls.requester = make_user("Pilot A")
        cls.officer = make_user("Diplomat B", groups=[cls.g_dip])
        cls.colleague = make_user("Diplomat C", groups=[cls.g_dip])
        cls.leader = make_user("Leader D", groups=[cls.g_lead])

    def setUp(self):
        self.dispatch = patch("aa_ticket.services.dispatch").start()
        self.addCleanup(patch.stopall)
        self.t = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "Body")

    def waiting_for_requester(self):
        services.claim(fresh(self.officer), self.t)
        services.add_reply(fresh(self.officer), fresh(self.t), "Please confirm")
        return fresh(self.t)


class TestEscalationTarget(Fixture):
    def test_double_submit_does_not_skip_a_level(self):
        self.client.force_login(self.requester)
        url = f"/ticket/{self.t.pk}/action/escalate/"
        self.client.post(url, {"target_department_id": self.lead.pk})
        r = self.client.post(url, {"target_department_id": self.lead.pk}, follow=True)
        self.assertEqual(list(self.t.escalations.values_list("to_department__name", flat=True)), ["Lead"])
        self.assertContains(r, "already been asked")

    def test_transfer_without_keep_drops_escalated_departments(self):
        services.request_escalation(fresh(self.requester), self.t)
        services.transfer(fresh(self.officer), fresh(self.t), self.fc, keep_as_collaborator=False)
        self.assertEqual(list(fresh(self.t).collaborating_departments.all()), [])
        self.assertFalse(access.can_view(fresh(self.leader), fresh(self.t)))


class TestRelease(Fixture):
    def test_release_resets_auto_close_state(self):
        t = self.waiting_for_requester()
        Ticket.objects.filter(pk=t.pk).update(autoclose_warned_at=timezone.now(), last_reply_at=timezone.now() - timedelta(days=9))
        self.officer.groups.remove(self.g_dip)
        check_unclaimed()
        t = fresh(t)
        self.assertEqual(t.status, Status.OPEN)
        self.assertFalse(t.last_reply_by_staff)
        self.assertIsNone(t.autoclose_warned_at)
        self.assertGreater(t.last_reply_at, timezone.now() - timedelta(minutes=1))

    def test_release_when_assignee_deleted_inactive_or_without_access(self):
        services.claim(fresh(self.officer), self.t)
        Ticket.objects.filter(pk=self.t.pk).update(assignee=None)
        check_unclaimed()
        self.assertEqual(fresh(self.t).status, Status.OPEN)

        services.claim(fresh(self.colleague), fresh(self.t))
        self.colleague.user_permissions.clear()
        check_unclaimed()
        self.assertEqual(fresh(self.t).status, Status.OPEN)

    def test_release_checks_all_tickets_not_only_first_batch(self):
        services.claim(fresh(self.officer), self.t)
        other = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Second", "Body")
        services.claim(fresh(self.colleague), other)
        self.colleague.groups.remove(self.g_dip)
        with patch("aa_ticket.tasks.BATCH_SIZE", 1):
            check_unclaimed()
        self.assertEqual(fresh(other).status, Status.OPEN)

    def test_reminder_skipped_when_ticket_moved_meanwhile(self):
        from aa_ticket.tasks import _mark_and_emit

        urgent = services.create_ticket(fresh(self.requester), self.dip, priority("urgent"), "U", "Body")
        stale = fresh(urgent)
        services.transfer(fresh(self.officer), urgent, self.fc)
        sent = _mark_and_emit(stale, "reminded_at", timezone.now(), Event.UNCLAIMED_REMINDER, {"status": Status.OPEN, "open_since": stale.open_since})
        self.assertFalse(sent)


class TestAutoCloseRecheck(Fixture):
    def test_fresh_staff_reply_prevents_auto_close(self):
        t = self.waiting_for_requester()
        stale = fresh(t)
        Ticket.objects.filter(pk=t.pk).update(last_reply_at=timezone.now() - timedelta(days=9), autoclose_warned_at=timezone.now() - timedelta(days=2))
        stale = fresh(t)
        services.add_reply(fresh(self.officer), fresh(t), "Still there?")
        services.close(None, stale, ClosedReason.AUTO, expected_last_reply_at=stale.last_reply_at)
        self.assertEqual(fresh(t).status, Status.IN_PROGRESS)

    def test_task_still_closes(self):
        t = self.waiting_for_requester()
        base = t.last_reply_at
        check_auto_close((base + timedelta(days=6, hours=1)).isoformat())
        check_auto_close((base + timedelta(days=7, hours=2)).isoformat())
        self.assertEqual(fresh(t).status, Status.CLOSED)


class TestReopenInactive(Fixture):
    def test_nobody_reopens_into_inactive_department(self):
        t = services.create_ticket(fresh(self.requester), self.fc, priority("normal"), "FC", "Body")
        services.close(fresh(self.requester), t, ClosedReason.REQUESTER)
        self.fc.is_active = False
        self.fc.save()
        boss = make_user("Boss E", perms=("basic_access", "view_all"))
        self.assertFalse(access.can_act(fresh(boss), fresh(t), "reply"))
        self.assertFalse(access.can_act(fresh(boss), fresh(t), "reopen"))


class TestDispatchRobust(Fixture):
    def test_broker_failure_does_not_lose_bell(self):
        services.claim(fresh(self.officer), self.t)
        with patch("aa_ticket.notifications.send_webhook") as wh, patch("aa_ticket.notifications.send_dm") as dm_task, \
                patch("aa_ticket.notifications.dm.is_available", return_value=True), patch("aa_ticket.notifications.notify") as notify:
            wh.delay.side_effect = ConnectionError("broker")
            dm_task.delay.side_effect = ConnectionError("broker")
            with self.assertLogs("extensions.aa_ticket", level="WARNING"):
                dispatch(Event.TRANSFERRED, self.t.pk, self.officer.pk, {"department_id": self.dip.pk, "reason": "secret"})
        self.assertEqual([c.kwargs["user"].pk for c in notify.call_args_list], [self.requester.pk])

    def test_one_failing_recipient_does_not_block_others(self):
        t = self.waiting_for_requester()
        with patch("aa_ticket.notifications.send_webhook"), patch("aa_ticket.notifications.dm.is_available", return_value=False), \
                patch("aa_ticket.notifications.notify") as notify:
            notify.side_effect = [RuntimeError("boom"), None]
            with self.assertLogs("extensions.aa_ticket", level="WARNING"):
                dispatch(Event.AUTOCLOSE_WARNING, t.pk, None, {})
        self.assertEqual(notify.call_count, 2)

    def test_dm_task_gets_no_free_text(self):
        services.claim(fresh(self.officer), self.t)
        with patch("aa_ticket.notifications.send_webhook"), patch("aa_ticket.notifications.send_dm") as dm_task, \
                patch("aa_ticket.notifications.dm.is_available", return_value=True), patch("aa_ticket.notifications.notify"):
            dispatch(Event.TRANSFERRED, self.t.pk, self.officer.pk, {"department_id": self.dip.pk, "reason": "secret"})
        self.assertNotIn("secret", repr(dm_task.delay.call_args))


class TestWebhookTimeout(TestCase):
    @patch("aa_ticket.discord.webhook.requests.post")
    def test_read_timeout_not_retried(self, post):
        dept = make_department("Dip", webhook_url="https://discord.com/api/webhooks/1/abc")
        t = services.create_ticket(make_user("Pilot A"), dept, priority("normal"), "Help", "Body")
        post.side_effect = requests.ReadTimeout("slow")
        with self.assertLogs("extensions.aa_ticket", level="WARNING"):
            send_webhook.apply(args=[dept.pk, t.pk, Event.SUBMITTED, True])
        self.assertEqual(post.call_count, 1)
