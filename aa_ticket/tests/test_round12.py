"""1.0.1: findings of the AA App Checklist review of 1.0.0."""

import logging
import sys
import types
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import translation

from aa_ticket import attachments, services
from aa_ticket.checks import check_beat_schedule
from aa_ticket.constants import Event
from aa_ticket.forms import TicketSettingsForm
from aa_ticket.models import TicketSettings
from aa_ticket.tasks import send_dm

from .factories import make_department, make_user, priority

BEAT = {
    "aa_ticket_check_unclaimed": {"task": "aa_ticket.tasks.check_unclaimed", "schedule": 300},
    "aa_ticket_check_auto_close": {"task": "aa_ticket.tasks.check_auto_close", "schedule": 900},
    "aa_ticket_cleanup_attachments": {"task": "aa_ticket.tasks.cleanup_attachments", "schedule": 86400},
}


class TestBeatScheduleCheck(TestCase):
    @override_settings(CELERYBEAT_SCHEDULE=BEAT)
    def test_all_three_entries_present_no_warning(self):
        self.assertEqual(check_beat_schedule(None), [])

    @override_settings(CELERYBEAT_SCHEDULE={"other": {"task": "x.y", "schedule": 60}})
    def test_missing_entries_are_named(self):
        warnings = check_beat_schedule(None)
        self.assertEqual([w.id for w in warnings], ["aa_ticket.W003"])
        for name in ("check_unclaimed", "check_auto_close", "cleanup_attachments"):
            self.assertIn(f"aa_ticket.tasks.{name}", warnings[0].msg)

    @override_settings(CELERYBEAT_SCHEDULE={k: v for k, v in BEAT.items() if "cleanup" not in k})
    def test_one_missing(self):
        warnings = check_beat_schedule(None)
        self.assertIn("aa_ticket.tasks.cleanup_attachments", warnings[0].msg)
        self.assertNotIn("check_unclaimed", warnings[0].msg)

    def test_entry_names_do_not_matter_only_task_paths(self):
        renamed = {f"my-{i}": v for i, v in enumerate(BEAT.values())}
        with override_settings(CELERYBEAT_SCHEDULE=renamed):
            self.assertEqual(check_beat_schedule(None), [])

    def test_no_schedule_setting_at_all(self):
        with override_settings():
            from django.conf import settings

            if hasattr(settings, "CELERYBEAT_SCHEDULE"):
                del settings.CELERYBEAT_SCHEDULE
            self.assertEqual([w.id for w in check_beat_schedule(None)], ["aa_ticket.W003"])


class TestImageSizeCap(TestCase):
    def form(self, mb):
        s = TicketSettings.get_solo()
        data = {f: getattr(s, f) for f in TicketSettingsForm.Meta.fields}
        data["max_image_mb"] = mb
        data = {k: ("" if v is None else v) for k, v in data.items()}
        return TicketSettingsForm(data=data, instance=s)

    def test_six_is_allowed(self):
        f = self.form(6)
        self.assertTrue(f.is_valid(), f.errors)

    def test_seven_is_refused_with_a_clear_message(self):
        with translation.override("en"):
            f = self.form(7)
            self.assertFalse(f.is_valid())
            self.assertIn("6", " ".join(f.errors["max_image_mb"]))

    def test_old_value_above_cap_is_capped_at_upload(self):
        TicketSettings.objects.filter(pk=TicketSettings.get_solo().pk).update(max_image_mb=20)
        big = SimpleUploadedFile("a.png", b"\x89PNG" + b"0" * (7 * 1024 * 1024))
        with translation.override("en"), self.assertRaises(ValidationError) as ctx:
            attachments.prepare_images([big])
        self.assertIn("6 MB", " ".join(ctx.exception.messages))


class TestDmFailureIsAWarning(TestCase):
    def test_bot_error_logged_as_warning(self):
        dept = make_department("Diplomacy")
        user = make_user("Pilot A")
        ticket = services.create_ticket(user, dept, priority("normal"), "Help", "Body")
        bot = types.ModuleType("aadiscordbot")
        bot_tasks = types.ModuleType("aadiscordbot.tasks")
        bot_tasks.send_message = MagicMock(side_effect=RuntimeError("no route"))
        bot.tasks = bot_tasks
        discord_mod = types.ModuleType("discord")
        from .test_notifications import FakeEmbed

        discord_mod.Embed = FakeEmbed
        with patch.dict(sys.modules, {"aadiscordbot": bot, "aadiscordbot.tasks": bot_tasks, "discord": discord_mod}), \
                patch("aa_ticket.discord.dm.bot_installed", return_value=True), \
                self.assertLogs("extensions.aa_ticket.tasks", level="WARNING") as logs:
            send_dm.apply(args=[user.pk, ticket.pk, Event.CLOSED])
        self.assertTrue(any("RuntimeError" in line and "WARNING" in line for line in logs.output), logs.output)
