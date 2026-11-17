from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from aa_ticket.constants import ClosedReason, Status
from aa_ticket.models import Ticket
from aa_ticket.stats import department_stats

from .factories import make_department, make_group, make_user, priority


class TestStats(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_top = make_group("Leadership")
        cls.g_dip = make_group("Diplomats")
        cls.top = make_department("Leadership", groups=[cls.g_top])
        cls.dip = make_department("Diplomacy", groups=[cls.g_dip], parent=cls.top)
        cls.log = make_department("Logistics")
        cls.requester = make_user("Pilot A")
        cls.dip_staff = make_user("Diplomat B", groups=[cls.g_dip])
        cls.viewer = make_user("Viewer C", perms=("basic_access", "view_all"))
        now = timezone.now()
        cls.since = now - timedelta(days=30)

        def ticket(dept, created_ago_h, claimed_after_h=None, closed_after_h=None, reason=""):
            created = now - timedelta(hours=created_ago_h)
            t = Ticket.objects.create(
                title="t", requester=cls.requester, department=dept, priority=priority("normal"),
                open_since=created, last_reply_at=created,
            )
            fields = {"created_at": created}
            if claimed_after_h is not None:
                fields.update(status=Status.IN_PROGRESS, claimed_at=created + timedelta(hours=claimed_after_h))
            if closed_after_h is not None:
                fields.update(
                    status=Status.CLOSED, closed_at=created + timedelta(hours=closed_after_h), closed_reason=reason
                )
            Ticket.objects.filter(pk=t.pk).update(**fields)

        ticket(cls.dip, 48, claimed_after_h=1, closed_after_h=10, reason=ClosedReason.STAFF)
        ticket(cls.dip, 24, claimed_after_h=3, closed_after_h=20, reason=ClosedReason.AUTO)
        ticket(cls.dip, 5)
        ticket(cls.dip, 24 * 60)  # outside the window, still open
        ticket(cls.log, 10)

    def row(self, rows, dept):
        return next(r for r in rows if r["department"] == dept)

    def test_stats_values(self):
        rows = department_stats(None, self.since)
        dip = self.row(rows, self.dip)
        self.assertEqual(dip["created"], 3)
        self.assertEqual(dip["closed"], 2)
        self.assertEqual(dip["open_now"], 2)
        self.assertAlmostEqual(dip["avg_claim_seconds"], 2 * 3600, delta=5)
        self.assertAlmostEqual(dip["avg_resolve_seconds"], 15 * 3600, delta=5)
        self.assertAlmostEqual(dip["auto_closed_ratio"], 0.5)
        log = self.row(rows, self.log)
        self.assertEqual(log["created"], 1)
        self.assertIsNone(log["avg_claim_seconds"])
        self.assertIsNone(log["auto_closed_ratio"])

    def test_stats_scope_limited(self):
        rows = department_stats({self.dip.pk}, self.since)
        self.assertEqual([r["department"] for r in rows], [self.dip])

    def test_stats_query_count_constant(self):
        with self.assertNumQueries(1):
            department_stats(None, self.since)
        for i in range(7):
            make_department(f"Extra {i}")
        with self.assertNumQueries(1):
            department_stats(None, self.since)

    def test_stats_view_scope(self):
        self.client.force_login(self.dip_staff)
        r = self.client.get("/ticket/stats/?days=30")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([row["department"] for row in r.context["rows"]], [self.dip])
        self.client.force_login(self.viewer)
        r = self.client.get("/ticket/stats/?days=7")
        self.assertEqual(len(r.context["rows"]), 3)
        self.client.force_login(self.requester)
        self.assertEqual(self.client.get("/ticket/stats/").status_code, 403)
