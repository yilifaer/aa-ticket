import os
import re

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from aa_ticket import services
from aa_ticket.auth_hooks import TicketDashboardHook
from aa_ticket.constants import ClosedReason
from aa_ticket.models import Department, Priority

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_lead = make_group("Leadership")
        cls.g_dip = make_group("Diplo")
        cls.g_fc = make_group("FC")
        cls.lead = make_department("Leadership", groups=[cls.g_lead], accepts_submissions=False)
        cls.dip = make_department("Diplo", groups=[cls.g_dip], parent=cls.lead)
        cls.fc = make_department("FC", groups=[cls.g_fc], parent=cls.lead)
        cls.player = make_user("Pilot A")
        cls.officer = make_user("Diplomat B", groups=[cls.g_dip])
        cls.other_officer = make_user("Diplomat C", groups=[cls.g_dip])
        cls.leader = make_user("Leader D", groups=[cls.g_lead])
        cls.noperm = make_user("Guest E", perms=())

    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def new(self, user=None, dept=None, prio="normal", title="Ticket"):
        return services.create_ticket(fresh(user or self.player), dept or self.dip, priority(prio), title, "Body")

    def overview(self, user):
        self.client.force_login(user)
        r = self.client.get("/ticket/")
        self.assertEqual(r.status_code, 200)
        return r


class TestUrgentFlag(TestCase):
    def test_default_urgent_flag(self):
        self.assertEqual(
            list(Priority.objects.filter(is_urgent=True).values_list("name", flat=True)), ["Urgent"]
        )


class TestPlayerOverview(Fixture):
    def test_player_sees_own_open_tickets_waiting_first(self):
        a = self.new(title="Older waiting")
        b = self.new(title="Newer not waiting")
        services.claim(fresh(self.officer), a)
        services.add_reply(fresh(self.officer), fresh(a), "Please answer")
        closed = self.new(title="Closed one")
        services.close(fresh(self.player), closed, ClosedReason.REQUESTER)
        r = self.overview(self.player)
        sections = {s["key"]: s for s in r.context["sections"]}
        self.assertEqual(list(sections), ["own"])
        self.assertEqual([t.title for t in sections["own"]["items"]], ["Older waiting", "Newer not waiting"])
        self.assertContains(r, 'href="/ticket/new/"')
        self.assertNotContains(r, "Closed one")

    def test_empty_section_is_one_line(self):
        r = self.overview(self.player)
        self.assertContains(r, "No open tickets.")
        self.assertNotContains(r, "<table")

    def test_requires_basic_access(self):
        self.client.force_login(self.noperm)
        self.assertEqual(self.client.get("/ticket/").status_code, 403)


class TestOfficerOverview(Fixture):
    def test_officer_sections_in_order(self):
        r = self.overview(self.officer)
        self.assertEqual([s["key"] for s in r.context["sections"]], ["mine", "unclaimed", "escalated", "own"])

    def test_mine_waiting_for_me_first(self):
        a = self.new(title="Requester replied")
        b = self.new(title="I replied last")
        for t in (a, b):
            services.claim(fresh(self.officer), t)
        services.add_reply(fresh(self.officer), fresh(b), "Answer")
        services.add_reply(fresh(self.officer), fresh(a), "Answer")
        services.add_reply(fresh(self.player), fresh(a), "Reply back")
        r = self.overview(self.officer)
        mine = next(s for s in r.context["sections"] if s["key"] == "mine")
        self.assertEqual([t.title for t in mine["items"]], ["Requester replied", "I replied last"])

    def test_unclaimed_urgent_first_with_claim_button(self):
        normal = self.new(title="Normal one")
        urgent = self.new(prio="urgent", title="Urgent one")
        self.new(dept=self.fc, title="Other department")
        r = self.overview(self.officer)
        unclaimed = next(s for s in r.context["sections"] if s["key"] == "unclaimed")
        self.assertEqual([t.title for t in unclaimed["items"]], ["Urgent one", "Normal one"])
        self.assertContains(r, f"/ticket/{urgent.pk}/action/claim/")

    def test_escalated_section_for_parent_department(self):
        t = self.new(dept=self.fc, title="Escalated to leadership")
        services.request_escalation(fresh(self.player), t)
        invited = self.new(dept=self.fc, title="Invited Diplo")
        fc_officer = make_user("Fleet F", groups=[self.g_fc])
        services.invite(fc_officer, invited, self.dip)
        r = self.overview(self.leader)
        esc = next(s for s in r.context["sections"] if s["key"] == "escalated")
        self.assertEqual([x.title for x in esc["items"]], ["Escalated to leadership"])
        r = self.overview(self.officer)
        esc = next(s for s in r.context["sections"] if s["key"] == "escalated")
        self.assertEqual([x.title for x in esc["items"]], ["Invited Diplo"])

    def test_own_submitted_section(self):
        self.new(user=self.officer, dept=self.fc, title="My own request")
        r = self.overview(self.officer)
        own = next(s for s in r.context["sections"] if s["key"] == "own")
        self.assertEqual([t.title for t in own["items"]], ["My own request"])
        unclaimed = next(s for s in r.context["sections"] if s["key"] == "unclaimed")
        self.assertNotIn("My own request", [t.title for t in unclaimed["items"]])

    def test_preview_limit_and_total(self):
        from aa_ticket.models import TicketSettings

        s = TicketSettings.get_solo()
        s.max_open_tickets = 20
        s.max_new_tickets_per_hour = 0
        s.save()
        for i in range(7):
            self.new(title=f"T{i}")
        r = self.overview(self.officer)
        unclaimed = next(s for s in r.context["sections"] if s["key"] == "unclaimed")
        self.assertEqual(len(unclaimed["items"]), 5)
        self.assertEqual(unclaimed["count"], 7)
        self.assertEqual(unclaimed["url"], "/ticket/staff/?tab=unclaimed")

    def test_view_all_user_only_sees_own_departments(self):
        boss = make_user("Boss G", perms=("basic_access", "view_all"), groups=[self.g_fc])
        self.new(title="Diplo ticket")
        r = self.overview(boss)
        titles = [t.title for s in r.context["sections"] for t in s["items"]]
        self.assertNotIn("Diplo ticket", titles)


class TestDashboardCard(Fixture):
    def render(self, user):
        request = RequestFactory().get("/dashboard/")
        request.user = fresh(user)
        return TicketDashboardHook().render(request)

    def test_hidden_without_permission(self):
        self.new()
        self.assertEqual(self.render(self.noperm), "")

    def test_hidden_when_nothing_to_show(self):
        self.assertEqual(self.render(self.player).strip(), "")

    def test_player_counts_and_waiting(self):
        t = self.new(title="Needs my answer")
        services.claim(fresh(self.officer), t)
        services.add_reply(fresh(self.officer), fresh(t), "Question")
        self.new(title="Other")
        html = self.render(self.player)
        self.assertIn("Needs my answer", html)
        self.assertIn('data-count="open">2<', html)
        self.assertIn('data-count="waiting">1<', html)
        self.assertIn('href="/ticket/"', html)

    def test_officer_counts_and_urgent(self):
        self.new(prio="urgent", title="Fire")
        t = self.new(title="Mine")
        services.claim(fresh(self.officer), t)
        html = self.render(self.officer)
        self.assertIn('data-count="assigned">1<', html)
        self.assertIn('data-count="unclaimed">1<', html)
        self.assertIn('data-count="urgent">1<', html)

    def test_query_count_small(self):
        for i in range(5):
            self.new(title=f"T{i}")
        user = fresh(self.officer)
        user.has_perm("aa_ticket.basic_access")
        request = RequestFactory().get("/dashboard/")
        request.user = user
        with self.assertNumQueries(8):
            TicketDashboardHook().render(request)


class TestPriorityUrgentSetting(Fixture):
    def test_urgent_flag_editable(self):
        admin = make_user("Admin H", perms=("basic_access", "manage"))
        self.client.force_login(admin)
        p = priority("normal")
        self.client.post(f"/ticket/manage/priorities/{p.pk}/", {
            "name": "Normal", "color": "primary", "order": "20", "mention_on_new": "on",
            "remind_after_minutes": "1440", "escalate_after_minutes": "", "is_active": "on", "is_urgent": "on",
        })
        self.assertTrue(Priority.objects.get(pk=p.pk).is_urgent)


class TestInactiveDepartmentsFolded(Fixture):
    def test_inactive_departments_in_collapsed_block(self):
        Department.objects.create(name="Old department", is_active=False)
        admin = make_user("Admin H", perms=("basic_access", "manage"))
        self.client.force_login(admin)
        r = self.client.get("/ticket/manage/departments/")
        html = r.content.decode()
        self.assertIn("<details", html)
        details = html[html.index("<details"):html.index("</details>")]
        self.assertIn("Old department", details)
        self.assertNotIn(">Diplo<", details)


class TestDarkModeContrast(TestCase):
    def test_no_low_contrast_emphasis_classes(self):
        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        for dirpath, _d, files in os.walk(root):
            for name in files:
                text = open(os.path.join(dirpath, name), encoding="utf-8").read()
                self.assertIsNone(re.search(r"text-(warning|danger)-emphasis", text), name)


class TestAssignedRespectsAccess(Fixture):
    def test_assigned_ticket_hidden_after_leaving_department(self):
        t = self.new(title="Secret assigned")
        services.claim(fresh(self.officer), t)
        self.officer.groups.remove(self.g_dip)
        self.officer.groups.add(self.g_fc)  # still an officer elsewhere
        r = self.overview(self.officer)
        titles = [x.title for s in r.context["sections"] for x in s["items"]]
        self.assertNotIn("Secret assigned", titles)
        request = RequestFactory().get("/dashboard/")
        request.user = fresh(self.officer)
        self.assertNotIn("Secret assigned", TicketDashboardHook().render(request))
