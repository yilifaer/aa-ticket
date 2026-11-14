import io
from unittest.mock import patch

from PIL import Image

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from aa_ticket import attachments, services
from aa_ticket.checks import check_media_root
from aa_ticket.exceptions import TicketActionError
from aa_ticket.models import Attachment, TicketSettings

from .factories import make_department, make_group, make_user, priority


def image_file(fmt="PNG", name=None, size=(10, 10)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 20, 20)).save(buf, format=fmt)
    ext = {"PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp"}[fmt]
    return SimpleUploadedFile(name or f"shot.{ext}", buf.getvalue())


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class TestValidation(TestCase):
    def test_accepts_png_jpg_gif_webp(self):
        attachments.validate_images([image_file(f) for f in ("PNG", "JPEG", "GIF", "WEBP")])

    def test_rejects_html_named_png(self):
        fake = SimpleUploadedFile("evil.png", b"<html><script>alert(1)</script></html>")
        with self.assertRaises(ValidationError) as ctx:
            attachments.validate_images([fake])
        self.assertIn("PNG, JPG, GIF", str(ctx.exception))

    def test_rejects_oversize(self):
        s = TicketSettings.get_solo()
        s.max_image_mb = 1
        s.save()
        big = SimpleUploadedFile("big.png", image_file().read() + b"0" * (2 * 1024 * 1024))
        with self.assertRaises(ValidationError) as ctx:
            attachments.validate_images([big])
        self.assertIn("1 MB", str(ctx.exception))

    def test_rejects_decompression_bomb(self):
        with patch.object(Image, "MAX_IMAGE_PIXELS", 50):
            with self.assertRaises(ValidationError):
                attachments.validate_images([image_file(size=(100, 100))])

    def test_rejects_sixth_image(self):
        with self.assertRaises(ValidationError) as ctx:
            attachments.validate_images([image_file() for _ in range(6)])
        self.assertIn("5", str(ctx.exception))


class AttachmentFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g = make_group("Diplomats")
        cls.dept = make_department("Diplomacy", groups=[cls.g])
        cls.requester = make_user("Pilot A")
        cls.staff = make_user("Diplomat B", groups=[cls.g])
        cls.outsider = make_user("Outsider C")


class TestStorage(AttachmentFixture):
    def test_random_filename_and_real_type(self):
        t = services.create_ticket(
            fresh(self.requester), self.dept, priority("normal"), "Help", "Body",
            images=[image_file("JPEG", name="my secret name.png")],
        )
        att = Attachment.objects.get(message__ticket=t)
        self.assertEqual(att.original_name, "my secret name.png")
        self.assertEqual(att.content_type, "image/jpeg")
        self.assertNotIn("secret", att.file.name)
        self.assertTrue(att.file.name.endswith(".jpg"))

    @override_settings(MEDIA_ROOT="")
    def test_uploads_disabled_without_media_root(self):
        self.assertFalse(attachments.uploads_enabled())
        with self.assertRaises(TicketActionError):
            services.create_ticket(
                fresh(self.requester), self.dept, priority("normal"), "Help", "Body", images=[image_file()]
            )

    @override_settings(MEDIA_ROOT="")
    def test_media_root_check_warns(self):
        warnings = check_media_root(None)
        self.assertEqual([w.id for w in warnings], ["aa_ticket.W001"])

    def test_media_root_check_ok(self):
        self.assertEqual(check_media_root(None), [])


class TestDownload(AttachmentFixture):
    def setUp(self):
        self.ticket = services.create_ticket(
            fresh(self.requester), self.dept, priority("normal"), "Help", "Body", images=[image_file()]
        )
        self.public = Attachment.objects.get(message__ticket=self.ticket)
        note = services.add_note(fresh(self.staff), self.ticket, "internal", images=[image_file("GIF")])
        self.internal = note.attachments.get()

    def get(self, user, att):
        self.client.force_login(user)
        return self.client.get(f"/ticket/files/{att.pk}/")

    def test_requester_gets_public_image(self):
        r = self.get(self.requester, self.public)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")

    def test_attachment_of_invisible_ticket_404(self):
        self.assertEqual(self.get(self.outsider, self.public).status_code, 404)

    def test_internal_attachment_hidden_from_requester(self):
        self.assertEqual(self.get(self.requester, self.internal).status_code, 404)
        self.assertEqual(self.get(self.staff, self.internal).status_code, 200)

    def test_internal_attachment_hidden_from_requester_staff(self):
        t = services.create_ticket(fresh(self.staff), self.dept, priority("normal"), "Own", "Body")
        other = make_user("Diplomat D", groups=[self.g])
        note = services.add_note(fresh(other), t, "about you", images=[image_file()])
        self.assertEqual(self.get(self.staff, note.attachments.get()).status_code, 404)

    def test_missing_attachment_404(self):
        self.client.force_login(self.requester)
        self.assertEqual(self.client.get("/ticket/files/999999/").status_code, 404)

    def test_requires_login(self):
        r = self.client.get(f"/ticket/files/{self.public.pk}/")
        self.assertEqual(r.status_code, 302)
