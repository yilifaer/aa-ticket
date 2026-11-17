import sys
import types
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from aa_ticket import services
from aa_ticket.constants import ClosedReason, Event
from aa_ticket.discord import dm
from aa_ticket.models import TicketSettings, UserPreference
from aa_ticket.notifications import dispatch
from aa_ticket.tasks import send_dm

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class FakeEmbed:
    def __init__(self, title=None, description=None, url=None, color=None):
        self.title, self.description, self.url, self.color = title, description, url, color
        self.fields = []

    def add_field(self, name, value, inline=False):
        self.fields.append((name, value))

    def set_footer(self, text=None, icon_url=None):
        self.footer = text


class NotifyFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_top = make_group("Leadership")
        cls.g_dip = make_group("Diplomats")
        cls.g_log = make_group("Logistics")
        cls.top = make_department("Leadership", groups=[cls.g_top], webhook_url="https://discord.com/api/webhooks/1/abc")
        cls.dip = make_department("Diplomacy", groups=[cls.g_dip], parent=cls.top, webhook_url="https://discord.com/api/webhooks/1/abc")
        cls.log = make_department("Logistics", groups=[cls.g_log], webhook_url="https://discord.com/api/webhooks/1/abc")
        cls.requester = make_user("Pilot A")
        cls.staff = make_user("Diplomat B", groups=[cls.g_dip])
        cls.staff2 = make_user("Diplomat C", groups=[cls.g_dip])

    def setUp(self):
        self.notify = patch("aa_ticket.notifications.notify").start()
        self.webhook = patch("aa_ticket.notifications.send_webhook").start()
        self.dm_task = patch("aa_ticket.notifications.send_dm").start()
        self.dm_available = patch("aa_ticket.notifications.dm.is_available", return_value=True).start()
        self.addCleanup(patch.stopall)

    def make_ticket(self, prio="normal"):
        return services.create_ticket(fresh(self.requester), self.dip, priority(prio), "Need help", "Body")

    def claimed(self):
        t = self.make_ticket()
        services.claim(fresh(self.staff), t)
        return fresh(t)

    def notified_users(self):
        return [c.kwargs["user"].pk for c in self.notify.call_args_list]

    def dm_users(self):
        return [c.args[0] for c in self.dm_task.delay.call_args_list]

    def webhook_calls(self):
        return [tuple(c.args[:4]) for c in self.webhook.delay.call_args_list]


class TestChannelRouting(NotifyFixture):
    def test_submitted_mentions_by_priority(self):
        t = self.make_ticket("low")
        dispatch(Event.SUBMITTED, t.pk, self.requester.pk, {})
        self.assertEqual(self.webhook_calls(), [(self.dip.pk, t.pk, Event.SUBMITTED, False)])
        self.webhook.reset_mock()
        t2 = self.make_ticket("urgent")
        dispatch(Event.SUBMITTED, t2.pk, self.requester.pk, {})
        self.assertEqual(self.webhook_calls(), [(self.dip.pk, t2.pk, Event.SUBMITTED, True)])

    def test_transferred_goes_to_new_department(self):
        t = self.claimed()
        services.transfer(fresh(self.staff), t, self.log)
        dispatch(Event.TRANSFERRED, t.pk, self.staff.pk, {"department_id": self.log.pk})
        self.assertEqual(self.webhook_calls(), [(self.log.pk, t.pk, Event.TRANSFERRED, True)])

    def test_invited(self):
        t = self.claimed()
        dispatch(Event.INVITED, t.pk, self.staff.pk, {"department_id": self.log.pk})
        self.assertEqual(self.webhook_calls(), [(self.log.pk, t.pk, Event.INVITED, True)])

    def test_escalation_requested_always_mentions(self):
        t = self.make_ticket("low")
        dispatch(Event.ESCALATION_REQUESTED, t.pk, self.requester.pk, {"department_id": self.top.pk})
        self.assertEqual(self.webhook_calls(), [(self.top.pk, t.pk, Event.ESCALATION_REQUESTED, True)])

    def test_unclaimed_reminder(self):
        t = self.make_ticket("low")
        dispatch(Event.UNCLAIMED_REMINDER, t.pk, None, {})
        self.assertEqual(self.webhook_calls(), [(self.dip.pk, t.pk, Event.UNCLAIMED_REMINDER, True)])

    def test_escalation_reminder_to_parent(self):
        t = self.make_ticket()
        dispatch(Event.ESCALATION_REMINDER, t.pk, None, {})
        self.assertEqual(self.webhook_calls(), [(self.top.pk, t.pk, Event.ESCALATION_REMINDER, True)])

    def test_awaiting_staff_reminder_no_mention(self):
        t = self.claimed()
        dispatch(Event.AWAITING_STAFF_REMINDER, t.pk, None, {})
        self.assertEqual(self.webhook_calls(), [(self.dip.pk, t.pk, Event.AWAITING_STAFF_REMINDER, False)])

    def test_reply_never_goes_to_channel(self):
        t = self.claimed()
        dispatch(Event.REPLIED, t.pk, self.requester.pk, {"by_staff": False})
        self.assertEqual(self.webhook_calls(), [])


class TestPersonalRouting(NotifyFixture):
    def test_requester_events(self):
        t = self.claimed()
        for event in (Event.CLAIMED, Event.CLOSED, Event.REOPENED, Event.TRANSFERRED, Event.PRIORITY_CHANGED):
            self.notify.reset_mock()
            self.dm_task.reset_mock()
            dispatch(event, t.pk, self.staff.pk, {})
            self.assertEqual(self.notified_users(), [self.requester.pk], event)
            self.assertEqual(self.dm_users(), [self.requester.pk], event)

    def test_staff_reply_notifies_requester(self):
        t = self.claimed()
        dispatch(Event.REPLIED, t.pk, self.staff.pk, {"by_staff": True})
        self.assertEqual(self.notified_users(), [self.requester.pk])

    def test_requester_reply_notifies_assignee(self):
        t = self.claimed()
        dispatch(Event.REPLIED, t.pk, self.requester.pk, {"by_staff": False})
        self.assertEqual(self.notified_users(), [self.staff.pk])
        self.assertEqual(self.dm_users(), [self.staff.pk])

    def test_requester_reply_without_assignee_notifies_nobody(self):
        t = self.make_ticket()
        dispatch(Event.REPLIED, t.pk, self.requester.pk, {"by_staff": False})
        self.assertEqual(self.notified_users(), [])

    def test_escalation_notifies_assignee(self):
        t = self.claimed()
        dispatch(Event.ESCALATION_REQUESTED, t.pk, self.requester.pk, {"department_id": self.top.pk})
        self.assertEqual(self.notified_users(), [self.staff.pk])

    def test_assigned_notifies_requester_and_new_assignee(self):
        t = self.claimed()
        dispatch(Event.ASSIGNED, t.pk, self.staff.pk, {"assignee_id": self.staff2.pk})
        self.assertEqual(sorted(self.notified_users()), sorted([self.requester.pk, self.staff2.pk]))

    def test_autoclose_warning(self):
        t = self.claimed()
        dispatch(Event.AUTOCLOSE_WARNING, t.pk, None, {})
        self.assertEqual(sorted(self.notified_users()), sorted([self.requester.pk, self.staff.pk]))

    def test_awaiting_staff_reminder_notifies_assignee(self):
        t = self.claimed()
        dispatch(Event.AWAITING_STAFF_REMINDER, t.pk, None, {})
        self.assertEqual(self.notified_users(), [self.staff.pk])

    def test_actor_not_notified(self):
        t = self.claimed()
        dispatch(Event.CLOSED, t.pk, self.requester.pk, {})
        self.assertNotIn(self.requester.pk, self.notified_users())
        self.assertEqual(self.notified_users(), [self.staff.pk])

    def test_requester_staff_gets_requester_notifications_only(self):
        t = services.create_ticket(fresh(self.staff2), self.dip, priority("normal"), "Own", "Body")
        services.claim(fresh(self.staff), t)
        dispatch(Event.REPLIED, t.pk, self.staff.pk, {"by_staff": True})
        self.assertEqual(self.notified_users(), [self.staff2.pk])

    def test_recipient_who_lost_access_skipped(self):
        t = self.claimed()
        self.staff.groups.remove(self.g_dip)
        Ticket = type(t)
        Ticket.objects.filter(pk=t.pk).update(assignee=None)
        dispatch(Event.REPLIED, t.pk, self.requester.pk, {"by_staff": False})
        self.assertEqual(self.notified_users(), [])

    def test_notification_contains_link(self):
        t = self.claimed()
        dispatch(Event.CLOSED, t.pk, self.staff.pk, {})
        kwargs = self.notify.call_args.kwargs
        self.assertIn(f"#{t.pk}", kwargs["title"])
        self.assertIn(f"https://auth.example.com/ticket/{t.pk}/", kwargs["message"])

    def test_dm_not_queued_when_unavailable(self):
        self.dm_available.return_value = False
        t = self.claimed()
        dispatch(Event.CLOSED, t.pk, self.staff.pk, {})
        self.assertEqual(self.notified_users(), [self.requester.pk])
        self.assertEqual(self.dm_users(), [])


class TestSendDm(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = make_department("Diplomacy")
        cls.requester = make_user("Pilot A")
        cls.ticket = services.create_ticket(cls.requester, cls.dept, priority("normal"), "Need help", "SECRET-BODY")

    def setUp(self):
        self.send_message = MagicMock()
        bot = types.ModuleType("aadiscordbot")
        bot_tasks = types.ModuleType("aadiscordbot.tasks")
        bot_tasks.send_message = self.send_message
        bot.tasks = bot_tasks
        discord_mod = types.ModuleType("discord")
        discord_mod.Embed = FakeEmbed
        patcher = patch.dict(sys.modules, {"aadiscordbot": bot, "aadiscordbot.tasks": bot_tasks, "discord": discord_mod})
        patcher.start()
        self.addCleanup(patcher.stop)
        installed = patch("aa_ticket.discord.dm.bot_installed", return_value=True)
        installed.start()
        self.addCleanup(installed.stop)

    def test_dm_sent(self):
        send_dm.apply(args=[self.requester.pk, self.ticket.pk, Event.CLOSED])
        self.send_message.assert_called_once()
        kwargs = self.send_message.call_args.kwargs
        self.assertEqual(kwargs["user_pk"], self.requester.pk)
        embed = kwargs["embed"]
        self.assertIn(f"#{self.ticket.pk}", embed.title)
        self.assertEqual(embed.url, f"https://auth.example.com/ticket/{self.ticket.pk}/")

    def test_dm_has_no_body(self):
        send_dm.apply(args=[self.requester.pk, self.ticket.pk, Event.REPLIED])
        embed = self.send_message.call_args.kwargs["embed"]
        self.assertNotIn("SECRET-BODY", f"{embed.title} {embed.description}")

    def test_dm_skipped_when_user_opted_out(self):
        pref = UserPreference.for_user(self.requester)
        pref.discord_dm_enabled = False
        pref.save()
        send_dm.apply(args=[self.requester.pk, self.ticket.pk, Event.CLOSED])
        self.send_message.assert_not_called()

    def test_dm_skipped_when_global_off(self):
        s = TicketSettings.get_solo()
        s.discord_dm_enabled = False
        s.save()
        self.assertFalse(dm.is_available())
        send_dm.apply(args=[self.requester.pk, self.ticket.pk, Event.CLOSED])
        self.send_message.assert_not_called()

    def test_dm_exception_swallowed(self):
        self.send_message.side_effect = RuntimeError("user has no discord")
        with self.assertLogs("extensions.aa_ticket", level="INFO") as logs:
            result = send_dm.apply(args=[self.requester.pk, self.ticket.pk, Event.CLOSED])
        self.assertTrue(result.successful())
        self.assertEqual(len(logs.output), 1)


class TestBotNotInstalled(TestCase):
    def test_dm_skipped_when_bot_not_installed(self):
        self.assertFalse(dm.bot_installed())
        self.assertFalse(dm.is_available())
