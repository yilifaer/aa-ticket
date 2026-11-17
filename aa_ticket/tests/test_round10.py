"""0.4.6: decisions from the 0.4.5 test report (section 7)."""

import io
import re
import sys
import types
from unittest.mock import MagicMock, patch

from PIL import Image

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from aa_ticket import attachments, services
from aa_ticket.constants import Event
from aa_ticket.models import TicketSettings
from aa_ticket.tasks import send_dm, send_webhook

from .factories import make_department, make_group, make_user, priority
from .test_notifications import FakeEmbed

URL = "https://discord.com/api/webhooks/1/abc"


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def upload(img, fmt="PNG", name="a.png"):
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue())


class TestMid1PixelLimit(TestCase):
    def test_limit_is_25_megapixels_for_every_format(self):
        from aa_ticket.app_settings import MAX_IMAGE_PIXELS

        self.assertEqual(MAX_IMAGE_PIXELS, 25_000_000)

    def test_png_above_25mp_is_refused_with_the_number_25(self):
        with translation.override("en"), self.assertRaises(ValidationError) as ctx:
            attachments.prepare_images([upload(Image.new("1", (6000, 5000)))])
        text = " ".join(ctx.exception.messages)
        self.assertIn("6000 × 5000", text)
        self.assertIn("25 megapixels", text)

    def test_jpeg_above_25mp_is_refused_too(self):
        with self.assertRaises(ValidationError):
            attachments.prepare_images([upload(Image.new("L", (6000, 5000)), "JPEG", "x.jpg")])

    def test_chinese_message_says_25(self):
        with translation.override("zh-hans"), self.assertRaises(ValidationError) as ctx:
            attachments.prepare_images([upload(Image.new("1", (6000, 5000)))])
        self.assertIn("25 百万像素", " ".join(ctx.exception.messages))

    def test_within_limit_but_long_edge_over_4096_is_scaled(self):
        data = attachments.prepare_images([upload(Image.new("L", (5000, 4000)), "JPEG", "x.jpg")])[0][3]
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(img.size, (4096, 3277))


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


class TestLow1StateAtEventTime(Fixture):
    """Department and assignee are taken when the event happens, not when the queue gets to it."""

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
        self.ticket = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "Body")
        services.claim(fresh(self.officer), self.ticket)

    def queued(self, func, *args):
        """Run an action and return the task calls it queued, without running them."""
        # the on-commit callbacks run when the innermost block ends, while the patches are active
        with patch("aa_ticket.notifications.notify"), \
                patch("aa_ticket.notifications.send_dm") as dm_task, \
                patch("aa_ticket.notifications.send_webhook") as wh_task, \
                patch("aa_ticket.notifications.dm.is_available", return_value=True), \
                self.captureOnCommitCallbacks(execute=True):
            func(*args)
        return dm_task.delay.call_args_list, wh_task.delay.call_args_list

    def test_dm_keeps_department_and_assignee_of_the_reply_time(self):
        dms, _ = self.queued(services.add_reply, fresh(self.requester), fresh(self.ticket), "more info")
        args = dms[0].args
        # the ticket moves on before the queue gets to the message
        services.transfer(fresh(self.officer), fresh(self.ticket), self.fc, keep_as_collaborator=False)
        self.send_message.reset_mock()
        send_dm.apply(args=args)
        fields = dict(self.send_message.call_args.kwargs["embed"].fields)
        self.assertEqual(fields, {"Department": "Diplomacy", "Assignee": "Diplomat B"})

    def test_snapshot_of_unclaimed_ticket_has_empty_assignee(self):
        from aa_ticket.notifications import event_snapshot

        ticket = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Other", "Body")
        self.assertEqual(event_snapshot(fresh(ticket)), {"department": "Diplomacy", "assignee": ""})
        self.assertEqual(event_snapshot(fresh(self.ticket)), {"department": "Diplomacy", "assignee": "Diplomat B"})

    def test_empty_assignee_in_snapshot_shows_nobody_yet(self):
        args = [self.requester.pk, self.ticket.pk, Event.REPLIED, {}, None, None, {"department": "X", "assignee": ""}]
        send_dm.apply(args=args)
        fields = dict(self.send_message.call_args.kwargs["embed"].fields)
        self.assertEqual(fields, {"Department": "X", "Assignee": "Nobody yet"})

    def test_channel_message_keeps_department_of_the_event_time(self):
        _, hooks = self.queued(
            services.transfer, fresh(self.officer), fresh(self.ticket), self.fc, False
        )
        args = hooks[0].args
        # the department is renamed before the queue gets to the message
        type(self.fc).objects.filter(pk=self.fc.pk).update(name="Fleet Command")
        posted = []
        with patch(
            "aa_ticket.tasks.webhook.post_webhook",
            side_effect=lambda url, payload, timeout=None: posted.append(payload) or MagicMock(ok=True),
        ):
            send_webhook.apply(args=args)
        embed = posted[0]["embeds"][0]
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        self.assertEqual(fields["Department"], "FC")
        self.assertIn("FC", embed["description"])

    def test_old_tasks_without_snapshot_look_up_the_current_state(self):
        send_dm.apply(args=[self.requester.pk, self.ticket.pk, Event.REPLIED, {}])
        fields = dict(self.send_message.call_args.kwargs["embed"].fields)
        self.assertEqual(fields, {"Department": "Diplomacy", "Assignee": "Diplomat B"})


class TestLow2AutocloseEveTime(Fixture):
    def test_warning_has_eve_time_on_hover(self):
        s = TicketSettings.get_solo()
        s.autoclose_days = 7
        s.save()
        ticket = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "Body")
        services.claim(fresh(self.officer), ticket)
        services.add_reply(fresh(self.officer), fresh(ticket), "Answer")
        self.client.force_login(self.requester)
        html = self.client.get(reverse("aa_ticket:detail", args=[ticket.pk])).content.decode()
        match = re.search(r'<span title="(\d{4}-\d\d-\d\d \d\d:\d\d EVE)">[^<]*Closes automatically', html)
        self.assertIsNotNone(match, "autoclose notice has no EVE time")
        eta = fresh(ticket).last_reply_at + timezone.timedelta(days=7)
        self.assertEqual(match.group(1), eta.strftime("%Y-%m-%d %H:%M") + " EVE")
