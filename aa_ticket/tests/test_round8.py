"""0.4.4: decisions from the 0.4.3 test report (sections 5 and 6)."""

import io
import os
import sys
import time
import types
from unittest.mock import MagicMock, patch

from PIL import Image

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from aa_ticket import access, attachments, services
from aa_ticket.constants import Event
from aa_ticket.models import Attachment
from aa_ticket.services import TicketActionError
from aa_ticket.tasks import cleanup_attachments, send_dm

from .factories import make_department, make_group, make_user, priority
from .test_notifications import FakeEmbed

STATIC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "aa_ticket", "css", "ticket.css")


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def upload(img, fmt="PNG", name="a.png", **save):
    buf = io.BytesIO()
    img.save(buf, format=fmt, **save)
    return SimpleUploadedFile(name, buf.getvalue())


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_dip = make_group("Dip")
        cls.dip = make_department("Dip", groups=[cls.g_dip])
        cls.requester = make_user("Pilot A")
        cls.officer = make_user("Diplomat B", groups=[cls.g_dip])
        cls.no_access = make_user("Diplomat C", perms=(), groups=[cls.g_dip])

    def setUp(self):
        cache.clear()
        self.t = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "SECRET-BODY")


class TestLow4AssignableNeedsBasicAccess(Fixture):
    def test_member_without_basic_access_is_not_offered(self):
        users = access.assignable_users(self.t)
        self.assertIn(self.officer, users)
        self.assertNotIn(self.no_access, users)

    def test_member_without_basic_access_cannot_be_assigned(self):
        with self.assertRaises(TicketActionError):
            services.assign(fresh(self.officer), self.t, fresh(self.no_access))
        self.assertIsNone(fresh(self.t).assignee_id)

    def test_inactive_member_is_not_offered(self):
        self.officer.is_active = False
        self.officer.save()
        self.assertNotIn(self.officer, access.assignable_users(self.t))

    def test_dropdown_lists_only_people_who_can_handle(self):
        self.client.force_login(self.officer)
        html = self.client.get(reverse("aa_ticket:detail", args=[self.t.pk])).content.decode()
        select = html[html.index('id="assign-user"'):]
        select = select[: select.index("</select>")]
        self.assertIn(f'value="{self.officer.pk}"', select)
        self.assertNotIn(f'value="{self.no_access.pk}"', select)


class TestImagesScaledDown(Fixture):
    def test_long_edge_over_4096_is_scaled_to_4096(self):
        data = attachments.prepare_images([upload(Image.new("RGB", (5000, 3000), (10, 20, 30)))])[0][3]
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(img.size, (4096, 2458))

    def test_portrait_jpeg_with_rotation_is_scaled_and_stripped(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90 degrees
        exif[0x8825] = {2: (1.0, 2.0, 3.0)}  # GPS
        big = upload(Image.new("RGB", (6000, 4000), (200, 10, 10)), "JPEG", "p.jpg", exif=exif, comment=b"SECRET")
        data = attachments.prepare_images([big])[0][3]
        self.assertNotIn(b"SECRET", data)
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(img.size, (2731, 4096))
            self.assertFalse(img.getexif())

    def test_small_image_keeps_its_size(self):
        data = attachments.prepare_images([upload(Image.new("RGB", (800, 600)))])[0][3]
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(img.size, (800, 600))

    def test_large_animation_is_scaled_and_keeps_frames(self):
        frames = [Image.new("RGB", (300, 200), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
        buf = io.BytesIO()
        frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=[50, 120, 200], loop=0)
        with patch("aa_ticket.attachments.MAX_IMAGE_EDGE", 150):
            data = attachments.prepare_images([SimpleUploadedFile("a.gif", buf.getvalue())])[0][3]
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(img.size, (150, 100))
            self.assertEqual(img.n_frames, 3)
            img.seek(1)
            self.assertEqual(img.info["duration"], 120)

    def test_over_decode_limit_is_refused_with_a_clear_message(self):
        with patch("aa_ticket.attachments.MAX_IMAGE_PIXELS", 1000), translation.override("en"):
            with self.assertRaises(ValidationError) as ctx:
                attachments.prepare_images([upload(Image.new("RGB", (50, 50)))])
        text = " ".join(ctx.exception.messages)
        self.assertIn("50 × 50", text)
        self.assertIn("smaller image", text)

    def test_photo_within_limit_is_scaled(self):
        # 0.4.6 lowered the limit back to 25 MP; a 20 MP photo is accepted and scaled.
        data = attachments.prepare_images([upload(Image.new("L", (5000, 4000)), "JPEG", "x.jpg")])[0][3]
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(max(img.size), 4096)


class TestDmFields(Fixture):
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

    def fields(self):
        send_dm.apply(args=[self.requester.pk, self.t.pk, Event.REPLIED])
        return dict(self.send_message.call_args.kwargs["embed"].fields)

    def test_unclaimed_ticket_shows_department_and_nobody(self):
        self.assertEqual(self.fields(), {"Department": "Dip", "Assignee": "Nobody yet"})

    def test_claimed_ticket_shows_assignee_and_no_body(self):
        services.claim(fresh(self.officer), self.t)
        fields = self.fields()
        self.assertEqual(fields["Assignee"], "Diplomat B")
        self.assertNotIn("SECRET-BODY", " ".join(fields.values()))

    def test_fields_follow_the_dm_language(self):
        from aa_ticket.models import TicketSettings

        s = TicketSettings.get_solo()
        s.channel_language = "zh-hans"
        s.dm_language_mode = "channel"
        s.save()
        self.assertEqual(self.fields(), {"部门": "Dip", "处理人": "还没有"})


class TestEveTime(Fixture):
    def test_detail_timeline_and_lists_say_eve(self):
        self.client.force_login(self.officer)
        stamp = self.t.created_at.strftime("%Y-%m-%d %H:%M") + " EVE"
        detail = self.client.get(reverse("aa_ticket:detail", args=[self.t.pk])).content.decode()
        self.assertGreaterEqual(detail.count(stamp), 2)  # sidebar "Submitted" and the first message
        self.assertNotIn(" UTC", detail)
        overview = self.client.get(reverse("aa_ticket:index")).content.decode()
        self.assertIn(f'title="{self.t.last_reply_at.strftime("%Y-%m-%d %H:%M")} EVE"', overview)

    @override_settings(TIME_ZONE="Asia/Shanghai")
    def test_eve_time_is_utc_even_if_the_server_zone_differs(self):
        from aa_ticket.templatetags.aa_ticket import eve_time

        import datetime

        value = datetime.datetime(2026, 11, 16, 23, 11, tzinfo=datetime.timezone.utc)
        self.assertEqual(eve_time(value), "2026-11-16 23:11 EVE")


class TestOrphanCleanupIsConservative(Fixture):
    def make(self, name, age_days=2):
        folder = os.path.join(settings.MEDIA_ROOT, "aa_ticket", "orphan-test")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "wb") as fh:
            fh.write(b"x")
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
        self.addCleanup(lambda: os.path.lexists(path) and os.remove(path))
        return path

    def test_only_names_this_app_gives_are_removed(self):
        ours = self.make("0123456789abcdef0123456789abcdef.jpg")
        other = self.make("backup-notes.txt")
        upper = self.make("0123456789ABCDEF0123456789ABCDEF.jpg")
        cleanup_attachments()
        self.assertFalse(os.path.exists(ours))
        self.assertTrue(os.path.exists(other))
        self.assertTrue(os.path.exists(upper))

    def test_symlinked_file_is_left_alone(self):
        target = self.make("target.bin")
        link = os.path.join(os.path.dirname(target), "f" * 32 + ".png")
        os.symlink(target, link)
        self.addCleanup(lambda: os.path.lexists(link) and os.remove(link))
        old = time.time() - 3 * 86400
        os.utime(link, (old, old), follow_symlinks=False)
        cleanup_attachments()
        self.assertTrue(os.path.islink(link))
        self.assertTrue(os.path.exists(target))

    def test_symlinked_folder_is_skipped(self):
        real = os.path.join(settings.MEDIA_ROOT, "elsewhere")
        os.makedirs(real, exist_ok=True)
        victim = os.path.join(real, "c" * 32 + ".png")
        with open(victim, "wb") as fh:
            fh.write(b"x")
        old = time.time() - 3 * 86400
        os.utime(victim, (old, old))
        media = os.path.join(settings.MEDIA_ROOT, "linked-media")
        os.makedirs(media, exist_ok=True)
        os.symlink(real, os.path.join(media, "aa_ticket"))
        with override_settings(MEDIA_ROOT=media):
            cleanup_attachments()
        self.assertTrue(os.path.exists(victim))

    def test_nothing_happens_with_other_storage(self):
        ours = self.make("d" * 32 + ".png")
        with patch("django.core.files.storage.default_storage", new=object()):
            cleanup_attachments()
        self.assertTrue(os.path.exists(ours))

    def test_referenced_file_is_kept(self):
        img = io.BytesIO()
        Image.new("RGB", (5, 5)).save(img, format="PNG")
        services.add_reply(fresh(self.requester), self.t, "x", images=[SimpleUploadedFile("a.png", img.getvalue())])
        kept = Attachment.objects.get().file.path
        old = time.time() - 3 * 86400
        os.utime(kept, (old, old))
        cleanup_attachments()
        self.assertTrue(os.path.exists(kept))


class TestLow5FixedColours(TestCase):
    def setUp(self):
        with open(STATIC, encoding="utf-8") as fh:
            self.css = fh.read()

    def test_alerts_and_buttons_have_fixed_pairs_inside_app_and_card(self):
        for cls, colour in (
            ("alert-warning", "#664d03"),
            ("alert-danger", "#842029"),
            ("alert-secondary", "#41464b"),
            ("alert-info", "#055160"),
            ("btn-danger", "#b02a37"),
            ("btn-secondary", "#5c636a"),
        ):
            self.assertIn(f".aa-ticket .{cls}", self.css)
            self.assertIn(f".aa-ticket-dash .{cls}", self.css)
            self.assertIn(colour, self.css)

    def test_close_button_red_in_light_and_dark(self):
        self.assertIn('[data-theme="darkly"] .aa-ticket .aa-ticket-close-btn', self.css)
        self.assertIn('[data-bs-theme="dark"] .aa-ticket .aa-ticket-close-btn', self.css)
        self.assertIn("#ea868f", self.css)

    def test_dashboard_card_loads_the_styles(self):
        from django.template.loader import get_template

        source = open(get_template("aa_ticket/dashboard_card.html").origin.name, encoding="utf-8").read()
        self.assertIn("aa_ticket/css/ticket.css", source)
        self.assertIn("aa-ticket-dash", source)
