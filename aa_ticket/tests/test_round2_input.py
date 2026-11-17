import io
import os
import tempfile

from PIL import Image

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from aa_ticket import services
from aa_ticket.checks import check_media_root
from aa_ticket.exceptions import TicketActionError
from aa_ticket.models import Attachment

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g = make_group("Diplomats")
        cls.dept = make_department("Diplomacy", groups=[cls.g])
        cls.requester = make_user("Pilot A")
        cls.staff = make_user("Diplomat B", groups=[cls.g])

    def create(self, title="Help", body="Body", **kw):
        return services.create_ticket(fresh(self.requester), self.dept, priority("normal"), title, body, **kw)


class TestText(Fixture):
    def test_zero_width_only_title_rejected(self):
        with self.assertRaises(TicketActionError):
            self.create(title="​‌‍﻿")
        with self.assertRaises(TicketActionError):
            self.create(body="​ ⁠")

    def test_bidi_controls_removed(self):
        t = self.create(title="abc‮dcba⁦x⁩")
        self.assertEqual(t.title, "abcdcbax")

    def test_nul_removed(self):
        t = self.create(body="a\x00b")
        self.assertEqual(t.messages.get(kind="reply").body, "ab")

    def test_body_length_limit(self):
        with self.assertRaises(TicketActionError):
            self.create(body="x" * 10001)
        t = self.create()
        with self.assertRaises(TicketActionError):
            services.add_reply(fresh(self.requester), t, "x" * 10001)

    def test_emoji_with_zero_width_joiner_kept(self):
        t = self.create(body="family \U0001F468‍\U0001F469")
        self.assertIn("‍", t.messages.get(kind="reply").body)


class TestDownloadHeaders(Fixture):
    def test_csp_sandbox_and_filename(self):
        buf = io.BytesIO()
        Image.new("RGB", (5, 5)).save(buf, format="PNG")
        t = self.create(images=[SimpleUploadedFile("My Screenshot.png", buf.getvalue())])
        att = Attachment.objects.get(message__ticket=t)
        self.client.force_login(self.requester)
        r = self.client.get(f"/ticket/files/{att.pk}/")
        self.assertEqual(r["Content-Security-Policy"], "sandbox")
        self.assertIn("inline", r["Content-Disposition"])
        self.assertIn("My Screenshot.png", r["Content-Disposition"])


class TestMediaCheck(TestCase):
    def test_missing_directory_warns(self):
        with override_settings(MEDIA_ROOT=os.path.join(tempfile.gettempdir(), "aa_ticket_does_not_exist_xyz")):
            self.assertEqual([w.id for w in check_media_root(None)], ["aa_ticket.W002"])


class TestPagination(Fixture):
    def test_page_links_have_no_empty_param(self):
        for i in range(55):
            self.create(title=f"T{i}") if i < 5 else None
        from aa_ticket.models import Ticket

        base = Ticket.objects.first()
        for i in range(55):
            Ticket.objects.create(
                title=f"Bulk {i}", requester=self.requester, department=self.dept, priority=priority("normal"),
                open_since=base.open_since, last_reply_at=base.last_reply_at,
            )
        self.client.force_login(self.staff)
        r = self.client.get("/ticket/staff/?tab=department")
        self.assertNotContains(r, "?&page=")
        self.assertContains(r, "page=2")
