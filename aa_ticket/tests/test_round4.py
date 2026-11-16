import os

import polib

from django.test import RequestFactory, TestCase

import aa_ticket
from aa_ticket import services
from aa_ticket.auth_hooks import TicketDashboardHook
from aa_ticket.models import Department, Priority

from .factories import make_department, make_group, make_user, priority

LOCALE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locale")


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_dip = make_group("Diplo")
        cls.g_fc = make_group("FC")
        cls.dip = make_department("Diplo", groups=[cls.g_dip])
        cls.fc = make_department("FC", groups=[cls.g_fc])
        cls.player = make_user("Pilot A")
        cls.officer = make_user("Diplomat B", groups=[cls.g_dip])

    def new(self, user=None, dept=None, prio="normal", title="T"):
        return services.create_ticket(fresh(user or self.player), dept or self.dip, priority(prio), title, "Body")

    def sections(self, user):
        self.client.force_login(user)
        return {s["key"]: s for s in self.client.get("/ticket/").context["sections"]}


class TestVersionInHeader(Fixture):
    def test_brand_shows_version(self):
        self.client.force_login(self.player)
        r = self.client.get("/ticket/")
        self.assertContains(r, f"v{aa_ticket.__version__}")
        title = r.content.decode().split("<title>")[1].split("</title>")[0]
        self.assertNotIn(aa_ticket.__version__, title)


class TestLow1WaitingOrder(Fixture):
    def test_waiting_sort_matches_badge_rule(self):
        unclaimed = self.new(title="Unclaimed with staff flag")
        type(unclaimed).objects.filter(pk=unclaimed.pk).update(last_reply_by_staff=True)
        waiting = self.new(title="Really waiting")
        services.claim(fresh(self.officer), waiting)
        services.add_reply(fresh(self.officer), fresh(waiting), "Q")
        type(waiting).objects.filter(pk=waiting.pk).update(last_reply_at=unclaimed.last_reply_at)
        own = self.sections(self.player)["own"]
        self.assertEqual(own["items"][0].title, "Really waiting")


class TestLow2ViewAllWithoutDepartment(Fixture):
    def test_view_all_sees_assigned_section(self):
        boss = make_user("Boss C", perms=("basic_access", "view_all"))
        t = self.new(title="Taken by boss")
        services.claim(fresh(boss), t)
        sections = self.sections(boss)
        self.assertIn("mine", sections)
        self.assertEqual([x.title for x in sections["mine"]["items"]], ["Taken by boss"])
        self.assertNotIn("unclaimed", sections)
        request = RequestFactory().get("/dashboard/")
        request.user = fresh(boss)
        self.assertIn("Taken by boss", TicketDashboardHook().render(request))


class TestLow3Queries(Fixture):
    def test_overview_query_count_does_not_grow_with_tickets(self):
        from aa_ticket.models import TicketSettings

        s = TicketSettings.get_solo()
        s.max_open_tickets = 50
        s.save()
        self.client.force_login(self.officer)
        self.new(title="first")
        self.client.get("/ticket/")
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as one:
            self.client.get("/ticket/")
        for i in range(4):
            self.new(title=f"more {i}")
        with CaptureQueriesContext(connection) as many:
            self.client.get("/ticket/")
        self.assertEqual(len(one), len(many))


class TestLow4DepartmentTree(Fixture):
    def test_active_child_of_inactive_parent_not_indented(self):
        parent = make_department("Old parent", is_active=False)
        make_department("Active child", parent=parent)
        make_department("Inactive child", parent=self.dip, is_active=False)
        admin = make_user("Admin D", perms=("basic_access", "manage"))
        self.client.force_login(admin)
        r = self.client.get("/ticket/manage/departments/")
        rows = {row["department"].name: row for row in r.context["rows"] + r.context["inactive_rows"]}
        self.assertEqual(rows["Active child"]["indent"], 0)
        self.assertEqual(rows["Inactive child"]["indent"], 0)
        self.assertContains(r, "Parent: Old parent (inactive)")
        self.assertContains(r, "Parent: Diplo")

    def test_only_inactive_shows_empty_message(self):
        Department.objects.update(is_active=False)
        admin = make_user("Admin E", perms=("basic_access", "manage"))
        self.client.force_login(admin)
        r = self.client.get("/ticket/manage/departments/")
        self.assertContains(r, "No active departments.")


class TestTranslationsConsistent(TestCase):
    def _po(self, lang):
        return {e.msgid: e for e in polib.pofile(os.path.join(LOCALE, lang, "LC_MESSAGES", "django.po"))}

    def test_german_unclaimed_wording(self):
        po = self._po("de")
        for msgid in ("Unclaimed in my departments", "No unclaimed tickets.", "Urgent unclaimed"):
            self.assertIn("nicht übernommen", po[msgid].msgstr.lower(), msgid)

    def test_russian_unclaimed_wording(self):
        po = self._po("ru")
        base = po["Unclaimed"].msgstr.lower()
        for msgid in ("Unclaimed in my departments", "No unclaimed tickets.", "Urgent unclaimed", "Unclaimed now"):
            self.assertIn(base.split()[0][:6], po[msgid].msgstr.lower(), msgid)

    def test_chinese_no_escalated(self):
        self.assertEqual(self._po("zh_Hans")["No escalated tickets."].msgstr, "没有上报或邀请我的部门的工单。")


class TestOptionalUi(Fixture):
    def test_no_light_badge(self):
        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        for dirpath, _d, files in os.walk(root):
            for name in files:
                self.assertNotIn("text-bg-light", open(os.path.join(dirpath, name), encoding="utf-8").read(), name)

    def test_urgent_marker_independent_of_colour(self):
        p = priority("urgent")
        p.color = "secondary"
        p.save()
        self.new(prio="urgent", title="Grey but urgent")
        self.client.force_login(self.officer)
        r = self.client.get("/ticket/")
        self.assertContains(r, 'data-urgent="1"')

    def test_staff_card_hides_zero_own_counts(self):
        self.new(title="Unclaimed one")
        request = RequestFactory().get("/dashboard/")
        request.user = fresh(self.officer)
        html = TicketDashboardHook().render(request)
        self.assertNotIn('data-count="open"', html)
        self.assertIn('data-count="unclaimed"', html)

    def test_tap_targets(self):
        self.new(title="Unclaimed one")
        self.client.force_login(self.officer)
        r = self.client.get("/ticket/")
        self.assertContains(r, "aa-tap", count=None)
        html = r.content.decode()
        claim = html[html.index("action/claim/"):][:400]
        self.assertIn("aa-tap", claim)


class TestOptionalData(Fixture):
    def test_escalated_matches_workbench_collab(self):
        t = self.new(dept=self.fc, title="Shared with Diplo")
        services.invite(make_user("Fleet F", groups=[self.g_fc]), t, self.dip)
        own_dept_ticket = self.new(title="Own dept also listed")
        own_dept_ticket.collaborating_departments.add(self.dip)
        esc = self.sections(self.officer)["escalated"]
        r = self.client.get("/ticket/staff/?tab=collab")
        self.assertEqual(sorted(x.pk for x in esc["items"]), sorted(x.pk for x in r.context["tickets"]))
        self.assertEqual(esc["count"], r.context["page"].paginator.count)

    def test_dashboard_query_count(self):
        self.new(title="x")
        user = fresh(self.officer)
        user.has_perm("aa_ticket.basic_access")
        request = RequestFactory().get("/dashboard/")
        request.user = user
        with self.assertNumQueries(8):
            TicketDashboardHook().render(request)


class TestSingleUrgentBadge(Fixture):
    def test_urgent_shown_once(self):
        self.new(prio="urgent", title="Fire")
        self.client.force_login(self.officer)
        html = self.client.get("/ticket/").content.decode()
        row = html[html.index("Fire"):]
        row = row[: row.index("action/claim/")]
        self.assertEqual(row.count('data-urgent="1"'), 1)
        self.assertEqual(row.count("fa-flag"), 0)
