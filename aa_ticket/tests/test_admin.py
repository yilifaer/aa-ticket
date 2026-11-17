import io

from PIL import Image

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from aa_ticket import services
from aa_ticket.models import Attachment, Department, TicketMessage

from .factories import add_perms, make_department, make_user, priority

URL = "https://discord.com/api/webhooks/123456789012345678/SECRETtokenVALUE_abc-XYZ"


def png():
    buf = io.BytesIO()
    Image.new("RGB", (5, 5)).save(buf, format="PNG")
    return SimpleUploadedFile("a.png", buf.getvalue())


class TestAdmin(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser("root", "root@example.com", "pw")
        cls.dept = make_department("Diplomacy", webhook_url=URL)
        cls.requester = make_user("Pilot A")

    def setUp(self):
        self.ticket = services.create_ticket(self.requester, self.dept, priority("normal"), "t", "b", images=[png()])
        self.client.force_login(self.superuser)

    def test_admin_readonly(self):
        self.assertEqual(self.client.get("/admin/aa_ticket/ticket/add/").status_code, 403)
        self.assertEqual(self.client.get("/admin/aa_ticket/department/add/").status_code, 403)
        r = self.client.post(f"/admin/aa_ticket/department/{self.dept.pk}/change/", {"name": "Changed"})
        self.assertEqual(Department.objects.get(pk=self.dept.pk).name, "Diplomacy")
        self.assertEqual(self.client.get(f"/admin/aa_ticket/ticket/{self.ticket.pk}/delete/").status_code, 403)

    def test_superuser_can_delete_message_and_file(self):
        message = TicketMessage.objects.get(ticket=self.ticket, kind="reply")
        att = Attachment.objects.get(message=message)
        path = att.file.path
        r = self.client.post(f"/admin/aa_ticket/attachment/{att.pk}/delete/", {"post": "yes"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Attachment.objects.filter(pk=att.pk).exists())
        import os

        self.assertFalse(os.path.exists(path))
        r = self.client.post(f"/admin/aa_ticket/ticketmessage/{message.pk}/delete/", {"post": "yes"})
        self.assertFalse(TicketMessage.objects.filter(pk=message.pk).exists())

    def test_staff_non_superuser_cannot_delete_message(self):
        staff = make_user("Staffer B", perms=())
        staff.is_staff = True
        staff.save()
        message = TicketMessage.objects.get(ticket=self.ticket, kind="reply")
        self.client.force_login(staff)
        self.client.post(f"/admin/aa_ticket/ticketmessage/{message.pk}/delete/", {"post": "yes"})
        self.assertTrue(TicketMessage.objects.filter(pk=message.pk).exists())

    def test_admin_hides_webhook(self):
        for url in ("/admin/aa_ticket/department/", f"/admin/aa_ticket/department/{self.dept.pk}/change/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertNotContains(r, "SECRETtoken")
