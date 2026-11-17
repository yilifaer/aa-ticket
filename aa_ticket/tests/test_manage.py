from unittest.mock import patch

from django.test import TestCase

from aa_ticket import services
from aa_ticket.models import CannedReply, Category, Department, Priority, TicketSettings

from .factories import make_department, make_group, make_user, priority

URL = "https://discord.com/api/webhooks/123456789012345678/SECRETtokenVALUE_abc-XYZ"


class ManageFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_dip = make_group("Diplomats")
        cls.g_log = make_group("Logistics")
        cls.top = make_department("Leadership")
        cls.dip = make_department("Diplomacy", groups=[cls.g_dip], parent=cls.top)
        cls.log = make_department("Logistics", groups=[cls.g_log])
        cls.admin = make_user("Admin A", perms=("basic_access", "manage"))
        cls.staff = make_user("Diplomat B", groups=[cls.g_dip])
        cls.requester = make_user("Pilot C")

    def login(self, user):
        self.client.force_login(user)

    def dept_post(self, **overrides):
        data = {
            "name": "Recruitment",
            "description": "Join us",
            "parent": "",
            "groups": [],
            "accepts_submissions": "on",
            "is_active": "on",
            "order": "5",
            "new_webhook_url": "",
            "mention_role_ids": "",
        }
        data.update(overrides)
        return data


class TestPermissions(ManageFixture):
    def test_manage_requires_permission(self):
        self.login(self.requester)
        for url in ("/ticket/manage/departments/", "/ticket/manage/priorities/", "/ticket/manage/categories/",
                    "/ticket/manage/settings/", "/ticket/manage/departments/0/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.get("/ticket/manage/canned/").status_code, 403)

    def test_staff_cannot_manage_departments(self):
        self.login(self.staff)
        self.assertEqual(self.client.get("/ticket/manage/departments/").status_code, 403)


class TestDepartments(ManageFixture):
    def test_department_crud(self):
        self.login(self.admin)
        r = self.client.post("/ticket/manage/departments/0/", self.dept_post(groups=[self.g_log.pk]))
        self.assertRedirects(r, "/ticket/manage/departments/")
        dept = Department.objects.get(name="Recruitment")
        self.assertEqual(list(dept.groups.all()), [self.g_log])
        r = self.client.post(f"/ticket/manage/departments/{dept.pk}/", self.dept_post(name="Recruiting"))
        self.assertRedirects(r, "/ticket/manage/departments/")
        self.assertEqual(Department.objects.get(pk=dept.pk).name, "Recruiting")
        r = self.client.post(f"/ticket/manage/departments/{dept.pk}/delete/")
        self.assertFalse(Department.objects.filter(pk=dept.pk).exists())

    def test_list_shows_tree_and_warnings(self):
        Department.objects.filter(pk=self.log.pk).update(webhook_url=URL, last_webhook_error="HTTP 404")
        self.login(self.admin)
        r = self.client.get("/ticket/manage/departments/")
        self.assertContains(r, "Discord channel not configured")
        self.assertContains(r, "HTTP 404")

    def test_cycle_rejected_in_form(self):
        self.login(self.admin)
        r = self.client.post(
            f"/ticket/manage/departments/{self.top.pk}/", self.dept_post(name="Leadership", parent=self.dip.pk)
        )
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(Department.objects.get(pk=self.top.pk).parent)

    def test_invalid_webhook_rejected(self):
        self.login(self.admin)
        r = self.client.post("/ticket/manage/departments/0/", self.dept_post(new_webhook_url="https://evil.example.com/x"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Department.objects.filter(name="Recruitment").exists())

    def test_webhook_never_rendered_in_full(self):
        self.login(self.admin)
        self.client.post(f"/ticket/manage/departments/{self.dip.pk}/", self.dept_post(name="Diplomacy", new_webhook_url=URL))
        self.assertEqual(Department.objects.get(pk=self.dip.pk).webhook_url, URL)
        for url in (f"/ticket/manage/departments/{self.dip.pk}/", "/ticket/manage/departments/"):
            r = self.client.get(url)
            self.assertNotContains(r, "SECRETtoken")
        self.assertContains(self.client.get(f"/ticket/manage/departments/{self.dip.pk}/"), "…-XYZ")

    def test_blank_webhook_keeps_existing(self):
        Department.objects.filter(pk=self.dip.pk).update(webhook_url=URL)
        self.login(self.admin)
        self.client.post(f"/ticket/manage/departments/{self.dip.pk}/", self.dept_post(name="Diplomacy"))
        self.assertEqual(Department.objects.get(pk=self.dip.pk).webhook_url, URL)

    def test_clear_webhook(self):
        Department.objects.filter(pk=self.dip.pk).update(webhook_url=URL)
        self.login(self.admin)
        self.client.post(f"/ticket/manage/departments/{self.dip.pk}/", self.dept_post(name="Diplomacy", clear_webhook="on"))
        self.assertEqual(Department.objects.get(pk=self.dip.pk).webhook_url, "")

    def test_delete_department_with_tickets_refused(self):
        services.create_ticket(self.requester, self.log, priority("normal"), "t", "b")
        self.login(self.admin)
        r = self.client.post(f"/ticket/manage/departments/{self.log.pk}/delete/", follow=True)
        self.assertTrue(Department.objects.filter(pk=self.log.pk).exists())
        self.assertContains(r, "Deactivate it instead")

    def test_delete_department_with_children_refused(self):
        self.login(self.admin)
        self.client.post(f"/ticket/manage/departments/{self.top.pk}/delete/")
        self.assertTrue(Department.objects.filter(pk=self.top.pk).exists())

    def test_delete_requires_post(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(f"/ticket/manage/departments/{self.log.pk}/delete/").status_code, 405)

    @patch("aa_ticket.views.manage.send_test_message", return_value=(False, "Discord refused the message (HTTP 401)."))
    def test_test_send_button_reports_result(self, send):
        self.login(self.admin)
        r = self.client.post(f"/ticket/manage/departments/{self.dip.pk}/test/", follow=True)
        send.assert_called_once()
        self.assertContains(r, "HTTP 401")


class TestPriorities(ManageFixture):
    def test_priority_create_and_edit(self):
        self.login(self.admin)
        r = self.client.post("/ticket/manage/priorities/0/", {
            "name": "Critical", "color": "danger", "order": "40", "mention_on_new": "on",
            "remind_after_minutes": "10", "escalate_after_minutes": "", "is_active": "on",
        })
        self.assertRedirects(r, "/ticket/manage/priorities/")
        self.assertEqual(Priority.objects.get(name="Critical").remind_after_minutes, 10)

    def test_priority_delete_in_use_refused(self):
        services.create_ticket(self.requester, self.dip, priority("normal"), "t", "b")
        self.login(self.admin)
        self.client.post(f"/ticket/manage/priorities/{priority('normal').pk}/delete/")
        self.assertTrue(Priority.objects.filter(name="Normal").exists())
        self.client.post(f"/ticket/manage/priorities/{priority('low').pk}/delete/")
        self.assertFalse(Priority.objects.filter(name="Low").exists())


class TestCategories(ManageFixture):
    def test_category_crud(self):
        self.login(self.admin)
        self.client.post("/ticket/manage/categories/0/", {
            "department": self.dip.pk, "name": "Blue", "template": "CEO:", "order": "0", "is_active": "on",
        })
        cat = Category.objects.get(name="Blue")
        t = services.create_ticket(self.requester, self.dip, priority("normal"), "t", "b", category=cat)
        self.client.post(f"/ticket/manage/categories/{cat.pk}/delete/")
        self.assertFalse(Category.objects.filter(pk=cat.pk).exists())
        t.refresh_from_db()
        self.assertIsNone(t.category)


class TestCanned(ManageFixture):
    def test_staff_can_edit_own_canned_only(self):
        own = CannedReply.objects.create(department=self.dip, title="Own", body="x")
        other = CannedReply.objects.create(department=self.log, title="Other", body="y")
        shared = CannedReply.objects.create(department=None, title="Shared", body="z")
        self.login(self.staff)
        r = self.client.get("/ticket/manage/canned/")
        self.assertContains(r, "Own")
        self.assertContains(r, "Shared")
        self.assertNotContains(r, "Other")
        self.assertEqual(self.client.get(f"/ticket/manage/canned/{other.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/ticket/manage/canned/{shared.pk}/").status_code, 404)
        r = self.client.post(f"/ticket/manage/canned/{own.pk}/", {"department": self.dip.pk, "title": "Own2", "body": "x"})
        self.assertRedirects(r, "/ticket/manage/canned/")
        r = self.client.post("/ticket/manage/canned/0/", {"department": self.log.pk, "title": "Sneaky", "body": "x"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(CannedReply.objects.filter(title="Sneaky").exists())
        r = self.client.post("/ticket/manage/canned/0/", {"department": "", "title": "Sneaky2", "body": "x"})
        self.assertFalse(CannedReply.objects.filter(title="Sneaky2").exists())
        self.client.post(f"/ticket/manage/canned/{other.pk}/delete/")
        self.assertTrue(CannedReply.objects.filter(pk=other.pk).exists())

    def test_admin_can_create_shared(self):
        self.login(self.admin)
        self.client.post("/ticket/manage/canned/0/", {"department": "", "title": "Shared", "body": "x"})
        self.assertTrue(CannedReply.objects.filter(title="Shared", department__isnull=True).exists())


class TestSettings(ManageFixture):
    def test_settings_save(self):
        self.login(self.admin)
        r = self.client.post("/ticket/manage/settings/", {
            "autoclose_days": "10", "autoclose_warning_hours": "12", "reopen_days": "3", "max_open_tickets": "2",
            "max_image_mb": "4", "attachment_retention_days": "", "discord_dm_enabled": "",
            "channel_language": "en", "dm_language_mode": "personal",
        })
        self.assertRedirects(r, "/ticket/manage/settings/")
        s = TicketSettings.get_solo()
        self.assertEqual((s.autoclose_days, s.max_open_tickets, s.discord_dm_enabled), (10, 2, False))
        self.assertIsNone(s.attachment_retention_days)

    def test_settings_page_has_help_text(self):
        self.login(self.admin)
        self.assertContains(self.client.get("/ticket/manage/settings/"), "closed automatically after this many days")
