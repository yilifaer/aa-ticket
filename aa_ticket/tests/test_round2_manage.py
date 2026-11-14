from django.contrib.auth.models import Permission
from django.test import TestCase

from aa_ticket.models import Department

from .factories import make_department, make_group, make_user


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_closed = make_group("Diplomats")
        cls.g_closed.authgroup.internal = True
        cls.g_closed.authgroup.save()
        cls.g_open = make_group("Everyone can join")
        cls.g_open.authgroup.internal = False
        cls.g_open.authgroup.open = True
        cls.g_open.authgroup.save()
        cls.top = make_department("Leadership")
        cls.child = make_department("Diplomacy", parent=cls.top, groups=[cls.g_closed])
        cls.admin = make_user("Admin A", perms=("basic_access", "manage"))

    def setUp(self):
        self.client.force_login(self.admin)

    def post_dept(self, dept, **overrides):
        data = {"name": dept.name, "description": "", "parent": dept.parent_id or "", "groups": [g.pk for g in dept.groups.all()],
                "accepts_submissions": "on", "is_active": "on", "order": "0", "new_webhook_url": "", "mention_role_ids": ""}
        data.update(overrides)
        data = {k: v for k, v in data.items() if v is not None}
        return self.client.post(f"/ticket/manage/departments/{dept.pk}/", data)


class TestSettingsValidation(Fixture):
    def test_warning_hours_must_be_shorter_than_auto_close(self):
        r = self.client.post("/ticket/manage/settings/", {
            "autoclose_days": "2", "autoclose_warning_hours": "48", "reopen_days": "3", "max_open_tickets": "2",
            "max_image_mb": "4", "attachment_retention_days": "", "channel_language": "en", "dm_language_mode": "personal",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "shorter than")


class TestDepartmentValidation(Fixture):
    def test_cannot_deactivate_parent_with_active_children(self):
        r = self.post_dept(self.top, is_active=None)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Department.objects.get(pk=self.top.pk).is_active)

    def test_open_group_warning_shown(self):
        self.child.groups.add(self.g_open)
        r = self.client.get("/ticket/manage/departments/")
        self.assertContains(r, "Everyone can join")
        self.assertContains(r, "anyone can join")
        r = self.client.get(f"/ticket/manage/departments/{self.child.pk}/")
        self.assertContains(r, "anyone can join")

    def test_closed_group_no_warning(self):
        r = self.client.get("/ticket/manage/departments/")
        self.assertNotContains(r, "anyone can join")

    def test_delete_confirm_mentions_categories(self):
        r = self.client.get("/ticket/manage/departments/")
        self.assertContains(r, "categories and canned replies")

    def test_role_ids_ascii_only(self):
        r = self.post_dept(self.child, mention_role_ids="١٢٣")
        self.assertEqual(r.status_code, 200)


class TestViewAllName(TestCase):
    def test_view_all_permission_name(self):
        p = Permission.objects.get(content_type__app_label="aa_ticket", codename="view_all")
        self.assertEqual(p.name, "Can view and handle all tickets")
