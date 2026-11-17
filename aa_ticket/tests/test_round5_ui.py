"""Regression tests for the whole-app review (0.4.1): images, views, pages."""

import io
import os
from unittest.mock import patch

from PIL import Image

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from aa_ticket import access, attachments, services
from aa_ticket.exceptions import TicketActionError
from aa_ticket.models import Attachment, Priority

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def png(name="a.png", size=(6, 6)):
    buf = io.BytesIO()
    Image.new("RGB", size, (9, 9, 9)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue())


def media_files():
    found = []
    for dirpath, _d, files in os.walk(os.path.join(settings.MEDIA_ROOT, "aa_ticket")):
        found += [os.path.join(dirpath, f) for f in files]
    return set(found)


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_dip = make_group("Dip")
        cls.g_fc = make_group("FC")
        cls.dip = make_department("Dip", groups=[cls.g_dip])
        cls.fc = make_department("FC", groups=[cls.g_fc])
        cls.requester = make_user("Pilot A")
        cls.officer = make_user("Diplomat B", groups=[cls.g_dip])
        cls.fc_officer = make_user("Fleet C", groups=[cls.g_fc])

    def setUp(self):
        self.t = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "Body")


class TestImages(Fixture):
    def test_no_orphan_files_when_a_later_image_fails(self):
        before = media_files()
        with patch("aa_ticket.attachments._reencode", side_effect=[b"ok-bytes", attachments._format_error()]):
            with self.assertRaises(TicketActionError):
                services.add_reply(fresh(self.requester), self.t, "x", images=[png("1.png"), png("2.png")])
        self.assertEqual(media_files(), before)
        self.assertEqual(Attachment.objects.count(), 0)

    def test_images_processed_before_ticket_lock(self):
        order = []
        real_prepare = attachments.prepare_images

        def spy_prepare(files):
            order.append("prepare")
            return real_prepare(files)

        real_lock = services._lock

        def spy_lock(ticket):
            order.append("lock")
            return real_lock(ticket)

        with patch("aa_ticket.services.prepare_images", side_effect=spy_prepare), patch("aa_ticket.services._lock", side_effect=spy_lock):
            services.add_reply(fresh(self.requester), self.t, "x", images=[png()])
        self.assertEqual(order[:2], ["prepare", "lock"])

    def test_each_image_decoded_once_for_format(self):
        with patch("aa_ticket.attachments._detect_format", wraps=attachments._detect_format) as detect:
            services.add_reply(fresh(self.requester), self.t, "x", images=[png()])
        self.assertEqual(detect.call_count, 1)

    def test_comment_metadata_removed(self):
        buf = io.BytesIO()
        Image.new("RGB", (5, 5)).save(buf, format="JPEG", comment=b"SECRET-COMMENT user=bob")
        services.add_reply(fresh(self.requester), self.t, "x", images=[SimpleUploadedFile("a.jpg", buf.getvalue())])
        with Attachment.objects.get().file.open("rb") as fh:
            self.assertNotIn(b"SECRET-COMMENT", fh.read())

    def test_pixel_limit_is_25mp(self):
        from aa_ticket.app_settings import MAX_IMAGE_PIXELS

        self.assertEqual(MAX_IMAGE_PIXELS, 25_000_000)


class TestViews(Fixture):
    def test_view_all_without_department_has_no_manage_link(self):
        boss = make_user("Boss D", perms=("basic_access", "view_all"))
        self.client.force_login(boss)
        self.assertNotContains(self.client.get("/ticket/"), "/ticket/manage/canned/")

    def test_transfer_without_keep_redirects_to_workbench(self):
        self.client.force_login(self.officer)
        r = self.client.post(f"/ticket/{self.t.pk}/action/transfer/", {"department_id": self.fc.pk, "keep_present": "1"}, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.redirect_chain[-1][0], "/ticket/staff/")
        self.assertContains(r, "Ticket transferred.")

    def test_collaborator_hint_does_not_say_claim(self):
        services.invite(fresh(self.officer), self.t, self.fc)
        hint = access.reply_hint(fresh(self.fc_officer), fresh(self.t))
        self.assertNotIn("Claim", hint)
        self.assertIn("internal note", hint)

    def test_invite_text_no_longer_promises_reply(self):
        self.client.force_login(self.officer)
        r = self.client.get(f"/ticket/{self.t.pk}/")
        self.assertNotContains(r, "can read and reply")

    def test_rejected_reply_keeps_typed_text(self):
        self.client.force_login(self.requester)
        bad = SimpleUploadedFile("x.png", b"<html>not an image</html>")
        r = self.client.post(f"/ticket/{self.t.pk}/reply/", {"kind": "reply", "body": "My long careful answer", "images": bad}, follow=True)
        self.assertContains(r, "My long careful answer")
        r = self.client.get(f"/ticket/{self.t.pk}/")
        self.assertNotContains(r, "My long careful answer")

    def test_stale_action_shows_message_not_403(self):
        services.claim(fresh(self.officer), self.t)
        self.client.force_login(self.requester)
        services.close(fresh(self.officer), fresh(self.t), "staff")
        r = self.client.post(f"/ticket/{self.t.pk}/action/close/", follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "no longer possible")

    def test_huge_number_filter_no_500(self):
        self.client.force_login(self.officer)
        r = self.client.get("/ticket/staff/", {"tab": "department", "department": "9" * 5000, "q": "#" + "9" * 5000, "page": "9" * 5000})
        self.assertEqual(r.status_code, 200)

    def test_single_department_hides_invite_and_transfer(self):
        self.fc.is_active = False
        self.fc.save()
        self.client.force_login(self.officer)
        r = self.client.get(f"/ticket/{self.t.pk}/")
        self.assertNotContains(r, "#modal-invite")
        self.assertNotContains(r, "#modal-transfer")

    def test_my_tickets_nav_highlighted(self):
        self.client.force_login(self.requester)
        self.assertEqual(self.client.get("/ticket/mine/").context["nav_active"], "mine")

    def test_submit_shows_priority_error(self):
        self.client.force_login(self.requester)
        r = self.client.post(f"/ticket/new/{self.dip.pk}/", {"title": "T", "body": "B", "priority": "99999"})
        self.assertContains(r, "Please pick an available priority.")

    def test_submit_without_priorities_explains(self):
        Priority.objects.update(is_active=False)
        self.client.force_login(self.requester)
        r = self.client.get(f"/ticket/new/{self.dip.pk}/")
        self.assertContains(r, "No priority is available")

    def test_expired_reopen_hint(self):
        from datetime import timedelta
        from django.utils import timezone
        from aa_ticket.models import Ticket

        services.close(fresh(self.requester), self.t, "requester")
        Ticket.objects.filter(pk=self.t.pk).update(closed_at=timezone.now() - timedelta(days=30))
        self.client.force_login(self.requester)
        r = self.client.get(f"/ticket/{self.t.pk}/")
        self.assertContains(r, "submit a new ticket")

    def test_version_label_contrast_class(self):
        self.client.force_login(self.requester)
        r = self.client.get("/ticket/")
        self.assertNotContains(r, 'text-body-secondary">v')
