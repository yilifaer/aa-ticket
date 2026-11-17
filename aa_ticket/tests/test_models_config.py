from django.core.exceptions import ValidationError
from django.test import TestCase

from aa_ticket.models import Department, Priority, TicketSettings, UserPreference

from .factories import make_department, make_user


class TestDepartment(TestCase):
    def setUp(self):
        self.a = make_department("A")
        self.b = make_department("B", parent=self.a)
        self.c = make_department("C", parent=self.b)

    def test_ancestors_order(self):
        self.assertEqual(self.c.ancestors(), [self.b, self.a])
        self.assertEqual(self.a.ancestors(), [])

    def test_descendant_ids(self):
        self.assertEqual(self.a.descendant_ids(), {self.b.pk, self.c.pk})
        self.assertEqual(self.c.descendant_ids(), set())

    def test_parent_cycle_rejected(self):
        self.a.parent = self.c
        with self.assertRaises(ValidationError):
            self.a.full_clean()

    def test_self_parent_rejected(self):
        self.a.parent = self.a
        with self.assertRaises(ValidationError):
            self.a.full_clean()

    def test_ancestors_stops_on_existing_cycle(self):
        Department.objects.filter(pk=self.a.pk).update(parent=self.c)
        c = Department.objects.get(pk=self.c.pk)
        self.assertEqual([d.pk for d in c.ancestors()], [self.b.pk, self.a.pk])

    def test_mention_role_id_list(self):
        self.c.mention_role_ids = "123, 456"
        self.c.full_clean()
        self.assertEqual(self.c.mention_role_id_list(), [123, 456])
        self.c.mention_role_ids = "123, 456,abc"
        with self.assertRaises(ValidationError):
            self.c.full_clean()

    def test_masked_webhook(self):
        self.c.webhook_url = "https://discord.com/api/webhooks/1/abcdWXYZ"
        self.assertEqual(self.c.masked_webhook(), "…WXYZ")
        self.c.webhook_url = ""
        self.assertEqual(self.c.masked_webhook(), "")


class TestPriority(TestCase):
    def test_default_priorities_seeded(self):
        rows = list(
            Priority.objects.order_by("order").values_list(
                "name", "color", "mention_on_new", "remind_after_minutes", "escalate_after_minutes"
            )
        )
        self.assertEqual(
            rows,
            [
                ("Low", "secondary", False, None, None),
                ("Normal", "primary", True, 1440, None),
                ("Urgent", "danger", True, 30, 120),
            ],
        )


class TestSettings(TestCase):
    def test_settings_defaults(self):
        s = TicketSettings.get_solo()
        self.assertEqual(s.autoclose_days, 7)
        self.assertEqual(s.autoclose_warning_hours, 24)
        self.assertEqual(s.reopen_days, 7)
        self.assertEqual(s.max_open_tickets, 5)
        self.assertEqual(s.max_image_mb, 5)
        self.assertIsNone(s.attachment_retention_days)
        self.assertTrue(s.discord_dm_enabled)

    def test_user_preference_for_user(self):
        user = make_user("Pilot A")
        pref = UserPreference.for_user(user)
        self.assertTrue(pref.discord_dm_enabled)
        self.assertEqual(UserPreference.for_user(user).pk, pref.pk)


class TestPermissions(TestCase):
    def test_permissions_exist(self):
        from django.contrib.auth.models import Permission

        codenames = set(
            Permission.objects.filter(content_type__app_label="aa_ticket").values_list(
                "codename", flat=True
            )
        )
        self.assertEqual(codenames, {"basic_access", "view_all", "manage"})
