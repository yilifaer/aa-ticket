"""0.4.5: "This was a Ticket Bot Notice from ... to ... at ... EVE" under every Discord message."""

import datetime
import re
import sys
import types
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from aa_ticket import services
from aa_ticket.constants import ClosedReason, Event
from aa_ticket.discord import webhook
from aa_ticket.discord.footer import notice
from aa_ticket.models import TicketMessage, TicketSettings
from aa_ticket.tasks import check_unclaimed, send_dm, send_webhook

from .factories import make_department, make_group, make_user, priority
from .test_notifications import FakeEmbed

URL = "https://discord.com/api/webhooks/1/abc"
FOOTER = re.compile(r"^This was a Ticket Bot Notice from (.+) to (.+) at (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) EVE$")


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_dip = make_group("Dip")
        cls.dip = make_department("Diplomacy", groups=[cls.g_dip], webhook_url=URL)
        cls.fc = make_department("FC", groups=[make_group("FC")], webhook_url=URL)
        cls.requester = make_user("Pilot A")
        cls.officer = make_user("Diplomat B", groups=[cls.g_dip])

    def setUp(self):
        cache.clear()
        self.posted = []
        post = patch("aa_ticket.tasks.webhook.post_webhook", side_effect=self._post)
        post.start()
        self.addCleanup(post.stop)
        # run the queued tasks right away
        wh = patch("aa_ticket.notifications.send_webhook.delay", side_effect=lambda *a: send_webhook.apply(args=a))
        wh.start()
        self.addCleanup(wh.stop)

    def _post(self, url, payload, timeout=None):
        self.posted.append(payload)
        return MagicMock(ok=True, status_code=204)

    def footers(self):
        return [FOOTER.match(p["embeds"][0]["footer"]["text"]).groups() for p in self.posted]

    def run_events(self, func, *args, **kwargs):
        with self.captureOnCommitCallbacks(execute=True), patch("aa_ticket.notifications.notify"):
            return func(*args, **kwargs)


class TestChannelFooter(Fixture):
    def test_new_ticket_is_from_alliance_auth_to_department_at_event_time(self):
        ticket = self.run_events(
            services.create_ticket, fresh(self.requester), self.dip, priority("normal"), "Help", "Body"
        )
        event = TicketMessage.objects.get(ticket=ticket, event_type=Event.SUBMITTED)
        stamp = event.created_at.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.assertEqual(self.footers(), [("Alliance Auth", "Diplomacy", stamp)])

    def test_transfer_is_from_the_person_who_did_it(self):
        ticket = self.run_events(
            services.create_ticket, fresh(self.requester), self.dip, priority("normal"), "Help", "Body"
        )
        self.posted.clear()
        self.run_events(services.transfer, fresh(self.officer), fresh(ticket), self.fc, keep_as_collaborator=False)
        sender, recipient, _ = self.footers()[0]
        self.assertEqual((sender, recipient), ("Diplomat B", "FC"))

    def test_requester_reply_notice_is_from_the_requester(self):
        ticket = self.run_events(
            services.create_ticket, fresh(self.requester), self.dip, priority("normal"), "Help", "Body"
        )
        self.posted.clear()
        self.run_events(services.add_reply, fresh(self.requester), fresh(ticket), "more info")
        self.assertEqual(self.footers()[0][:2], ("Pilot A", "Diplomacy"))

    def test_automatic_reminder_is_from_alliance_auth(self):
        p = priority("normal")
        p.remind_after_minutes = 1
        p.save()
        ticket = self.run_events(services.create_ticket, fresh(self.requester), self.dip, p, "Help", "Body")
        self.posted.clear()
        later = (fresh(ticket).open_since + datetime.timedelta(minutes=5)).isoformat()
        with self.captureOnCommitCallbacks(execute=True), patch("aa_ticket.notifications.notify"):
            check_unclaimed(later)
        self.assertEqual(self.footers()[0][:2], ("Alliance Auth", "Diplomacy"))

    def test_footer_text_is_english_even_for_other_channel_languages(self):
        s = TicketSettings.get_solo()
        s.channel_language = "zh-hans"
        s.save()
        self.run_events(services.create_ticket, fresh(self.requester), self.dip, priority("normal"), "Help", "Body")
        self.assertTrue(self.posted[0]["embeds"][0]["footer"]["text"].startswith("This was a Ticket Bot Notice from "))

    def test_old_queued_tasks_without_actor_and_time_still_work(self):
        ticket = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "Body")
        send_webhook.apply(args=[self.dip.pk, ticket.pk, Event.SUBMITTED, False])
        self.assertEqual(self.footers()[0][:2], ("Alliance Auth", "Diplomacy"))

    def test_test_message_names_the_admin(self):
        admin = make_user("Admin E", perms=("basic_access", "manage"))
        with patch("aa_ticket.discord.webhook.post_webhook", side_effect=self._post):
            webhook.send_test_message(self.dip, admin)
        self.assertEqual(self.footers()[0][:2], ("Admin E", "Diplomacy"))

    def test_test_message_view_passes_the_admin(self):
        admin = make_user("Admin F", perms=("basic_access", "manage"))
        self.client.force_login(admin)
        with patch("aa_ticket.views.manage.send_test_message", return_value=(True, "ok")) as sent:
            self.client.post(reverse("aa_ticket:manage_department_test", args=[self.dip.pk]))
        self.assertEqual(sent.call_args.args[1], admin)


class TestDmFooter(Fixture):
    def setUp(self):
        super().setUp()
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
        dm_task = patch("aa_ticket.notifications.send_dm.delay", side_effect=lambda *a: send_dm.apply(args=a))
        dm_task.start()
        self.addCleanup(dm_task.stop)

    def dm_footer(self):
        return FOOTER.match(self.send_message.call_args.kwargs["embed"].footer).groups()

    def test_staff_reply_is_from_replier_to_requester(self):
        ticket = self.run_events(
            services.create_ticket, fresh(self.requester), self.dip, priority("normal"), "Help", "Body"
        )
        self.run_events(services.claim, fresh(self.officer), fresh(ticket))
        message = self.run_events(services.add_reply, fresh(self.officer), fresh(ticket), "answer")
        stamp = message.created_at.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.assertEqual(self.dm_footer(), ("Diplomat B", "Pilot A", stamp))

    def test_requester_reply_is_from_requester_to_assignee(self):
        ticket = self.run_events(
            services.create_ticket, fresh(self.requester), self.dip, priority("normal"), "Help", "Body"
        )
        self.run_events(services.claim, fresh(self.officer), fresh(ticket))
        self.send_message.reset_mock()
        self.run_events(services.add_reply, fresh(self.requester), fresh(ticket), "thanks")
        self.assertEqual(self.dm_footer()[:2], ("Pilot A", "Diplomat B"))

    def test_close_is_from_the_person_who_closed(self):
        ticket = self.run_events(
            services.create_ticket, fresh(self.requester), self.dip, priority("normal"), "Help", "Body"
        )
        self.run_events(services.claim, fresh(self.officer), fresh(ticket))
        self.run_events(services.close, fresh(self.officer), fresh(ticket), ClosedReason.STAFF)
        self.assertEqual(self.dm_footer()[:2], ("Diplomat B", "Pilot A"))


class TestNoticeFormat(TestCase):
    def test_exact_text(self):
        at = datetime.datetime(2026, 11, 15, 11, 3, 28, 844432, tzinfo=datetime.timezone.utc)
        self.assertEqual(
            notice("Alliance Auth", "Diplomacy", at),
            "This was a Ticket Bot Notice from Alliance Auth to Diplomacy at 2026-11-15 11:03:28 EVE",
        )

    def test_iso_string_from_task_arguments(self):
        self.assertTrue(notice("A", "B", "2026-11-15T11:03:28.844432+00:00").endswith("at 2026-11-15 11:03:28 EVE"))

    def test_other_timezone_is_converted_to_eve(self):
        cst = datetime.timezone(datetime.timedelta(hours=8))
        at = datetime.datetime(2026, 11, 15, 19, 3, 28, tzinfo=cst)
        self.assertTrue(notice("A", "B", at).endswith("at 2026-11-15 11:03:28 EVE"))
