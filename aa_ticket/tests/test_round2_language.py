import sys
import types
from unittest.mock import MagicMock, patch

from django.test import TestCase

from aa_ticket import services
from aa_ticket.constants import Event
from aa_ticket.discord.webhook import build_payload
from aa_ticket.models import TicketSettings
from aa_ticket.tasks import send_dm

from .factories import make_department, make_user, priority


class FakeEmbed:
    def __init__(self, title=None, description=None, url=None, color=None):
        self.title, self.description, self.url = title, description, url
        self.fields = []

    def add_field(self, name, value, inline=False):
        self.fields.append((name, value))


class LanguageFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = make_department("Diplomacy")
        cls.requester = make_user("Pilot A")
        cls.requester.profile.language = "zh-hans"
        cls.requester.profile.save()
        cls.ticket = services.create_ticket(cls.requester, cls.dept, priority("normal"), "Help", "Body")


class TestChannelLanguage(LanguageFixture):
    def test_channel_default_is_english(self):
        payload = build_payload(self.ticket, Event.SUBMITTED, False, self.dept)
        self.assertEqual(payload["embeds"][0]["description"], "New ticket")

    @patch("django.conf.settings.LANGUAGE_CODE", "de")
    def test_channel_ignores_site_language(self):
        payload = build_payload(self.ticket, Event.SUBMITTED, False, self.dept)
        self.assertEqual(payload["embeds"][0]["description"], "New ticket")

    def test_channel_language_setting(self):
        s = TicketSettings.get_solo()
        s.channel_language = "zh-hans"
        s.save()
        payload = build_payload(self.ticket, Event.SUBMITTED, False, self.dept)
        self.assertEqual(payload["embeds"][0]["description"], "新工单")


class TestDmLanguage(LanguageFixture):
    def setUp(self):
        self.send_message = MagicMock()
        bot = types.ModuleType("aadiscordbot")
        bot_tasks = types.ModuleType("aadiscordbot.tasks")
        bot_tasks.send_message = self.send_message
        bot.tasks = bot_tasks
        discord_mod = types.ModuleType("discord")
        discord_mod.Embed = FakeEmbed
        p = patch.dict(sys.modules, {"aadiscordbot": bot, "aadiscordbot.tasks": bot_tasks, "discord": discord_mod})
        p.start()
        self.addCleanup(p.stop)
        q = patch("aa_ticket.discord.dm.bot_installed", return_value=True)
        q.start()
        self.addCleanup(q.stop)

    def text(self):
        send_dm.apply(args=[self.requester.pk, self.ticket.pk, Event.CLOSED])
        return self.send_message.call_args.kwargs["embed"].description

    def test_dm_follows_personal_language(self):
        self.assertEqual(self.text(), "工单已关闭。")

    def test_dm_uses_channel_language_when_set(self):
        s = TicketSettings.get_solo()
        s.dm_language_mode = "channel"
        s.channel_language = "de"
        s.save()
        self.assertNotEqual(self.text(), "工单已关闭。")
        self.assertNotEqual(self.text(), "The ticket was closed.")
