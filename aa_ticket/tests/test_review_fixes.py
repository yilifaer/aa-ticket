"""Regression tests for findings of the final review."""

import io
from datetime import timedelta
from unittest.mock import patch

from PIL import Image

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.migrations.executor import MigrationExecutor
from django.db import connection
from django.test import TestCase, TransactionTestCase

from aa_ticket import attachments, services
from aa_ticket.constants import Event, Status
from aa_ticket.models import Department, Ticket, TicketMessage, TicketSettings
from aa_ticket.tasks import check_auto_close, check_unclaimed

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g = make_group("Diplomats")
        cls.g_log = make_group("Logistics")
        cls.top = make_department("Leadership")
        cls.dip = make_department("Diplomacy", groups=[cls.g], parent=cls.top)
        cls.log = make_department("Logistics", groups=[cls.g_log])
        cls.requester = make_user("Pilot A")
        cls.staff = make_user("Diplomat B", groups=[cls.g])
        cls.admin = make_user("Admin C", perms=("basic_access", "manage"))

    def setUp(self):
        patcher = patch("aa_ticket.services.dispatch")
        patcher.start()
        self.addCleanup(patcher.stop)

    def claimed_with_staff_reply(self):
        t = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "Body")
        services.claim(fresh(self.staff), t)
        services.add_reply(fresh(self.staff), fresh(t), "Please confirm.")
        return fresh(t)


class TestPixelLimit(TestCase):
    def test_rejects_huge_dimensions_with_clear_message(self):
        buf = io.BytesIO()
        Image.new("1", (12000, 12000)).save(buf, format="PNG")
        upload = SimpleUploadedFile("huge.png", buf.getvalue())
        with self.assertRaises(ValidationError) as ctx:
            attachments.validate_images([upload])
        self.assertIn("too large", " ".join(ctx.exception.messages))


class TestAutoCloseNeedsWarning(Fixture):
    def test_shortened_setting_warns_before_closing(self):
        t = self.claimed_with_staff_reply()
        s = TicketSettings.get_solo()
        s.autoclose_days = 3
        s.save()
        now = t.last_reply_at + timedelta(days=5)
        check_auto_close(now.isoformat())
        t = fresh(t)
        self.assertEqual(t.status, Status.IN_PROGRESS)
        self.assertIsNotNone(t.autoclose_warned_at)
        check_auto_close((now + timedelta(hours=23)).isoformat())
        self.assertEqual(fresh(t).status, Status.IN_PROGRESS)
        check_auto_close((now + timedelta(hours=24, minutes=1)).isoformat())
        self.assertEqual(fresh(t).status, Status.CLOSED)

    def test_auto_close_skips_if_requester_replied_meanwhile(self):
        t = self.claimed_with_staff_reply()
        stale = fresh(t)
        services.add_reply(fresh(self.requester), fresh(t), "I am here")
        services.close(None, stale, "auto")
        self.assertEqual(fresh(t).status, Status.IN_PROGRESS)


class TestTransferReasonHidden(Fixture):
    def test_transfer_reason_not_shown_to_requester(self):
        t = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "Body")
        services.transfer(fresh(self.staff), t, self.log, reason="SECRET-REASON")
        self.client.force_login(self.requester)
        r = self.client.get(f"/ticket/{t.pk}/")
        self.assertNotContains(r, "SECRET-REASON")
        log_staff = make_user("Hauler D", groups=[self.g_log])
        self.client.force_login(log_staff)
        self.assertContains(self.client.get(f"/ticket/{t.pk}/"), "SECRET-REASON")


class TestDeactivateWithOpenTickets(Fixture):
    def test_cannot_deactivate_department_with_open_tickets(self):
        services.create_ticket(fresh(self.requester), self.log, priority("normal"), "Help", "Body")
        self.client.force_login(self.admin)
        r = self.client.post(
            f"/ticket/manage/departments/{self.log.pk}/",
            {"name": "Logistics", "description": "", "parent": "", "groups": [self.g_log.pk],
             "accepts_submissions": "on", "order": "0", "new_webhook_url": "", "mention_role_ids": ""},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "open tickets")
        self.assertTrue(Department.objects.get(pk=self.log.pk).is_active)


class TestBatchSkipsDoneTickets(Fixture):
    def test_check_unclaimed_query_excludes_done(self):
        # escalation configured but no parent -> never actionable, must not block the queue
        for i in range(3):
            services.create_ticket(fresh(self.requester), self.log, priority("urgent"), f"T{i}", "x")
        check_unclaimed((Ticket.objects.first().open_since + timedelta(minutes=31)).isoformat())
        from aa_ticket.tasks import _unclaimed_candidates

        later = Ticket.objects.first().open_since + timedelta(days=1)
        self.assertEqual(list(_unclaimed_candidates()), [])


class TestUninstall(TransactionTestCase):
    def test_migrate_zero_with_tickets(self):
        requester = make_user("Pilot Z")
        dept = make_department("Diplomacy")
        services.create_ticket(requester, dept, priority("normal"), "t", "b")
        executor = MigrationExecutor(connection)
        executor.migrate([("aa_ticket", None)])
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes("aa_ticket"))


class TestMigrationDependencies(TestCase):
    def test_depends_only_on_migrations_from_aa_5_0(self):
        import importlib

        migration = importlib.import_module("aa_ticket.migrations.0001_initial").Migration
        deps = {d for d in migration.dependencies if d[0] in ("authentication", "eveonline")}
        self.assertEqual(deps, {("authentication", "0025_v5squash"), ("eveonline", "0019_v5squash")})
