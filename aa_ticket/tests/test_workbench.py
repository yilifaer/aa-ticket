from django.test import TestCase

from aa_ticket import services

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class WorkbenchFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_top = make_group("Leadership")
        cls.g_dip = make_group("Diplomats")
        cls.g_log = make_group("Logistics")
        cls.top = make_department("Leadership", groups=[cls.g_top])
        cls.dip = make_department("Diplomacy", groups=[cls.g_dip], parent=cls.top)
        cls.log = make_department("Logistics", groups=[cls.g_log])
        cls.requester = make_user("Pilot A")
        cls.staff = make_user("Diplomat B", groups=[cls.g_dip])
        cls.staff2 = make_user("Diplomat C", groups=[cls.g_dip])
        cls.top_staff = make_user("Leader D", groups=[cls.g_top])
        cls.log_staff = make_user("Hauler E", groups=[cls.g_log])
        cls.outsider = make_user("Outsider F")
        cls.viewer = make_user("Viewer G", perms=("basic_access", "view_all"))

    def setUp(self):
        r = fresh(self.requester)
        self.unclaimed = services.create_ticket(r, self.dip, priority("urgent"), "Unclaimed one", "x")
        self.mine = services.create_ticket(r, self.dip, priority("normal"), "Mine one", "x")
        services.claim(fresh(self.staff), self.mine)
        self.other = services.create_ticket(r, self.dip, priority("low"), "Other staff one", "x")
        services.claim(fresh(self.staff2), self.other)
        self.collab = services.create_ticket(r, self.log, priority("normal"), "Logistics with us", "x")
        services.invite(fresh(self.log_staff), self.collab, self.dip)
        self.closed = services.create_ticket(r, self.dip, priority("normal"), "Closed one", "x")
        services.close(fresh(self.requester), self.closed, "requester")
        self.own = services.create_ticket(fresh(self.staff), self.dip, priority("normal"), "Own ticket", "x")

    def titles(self, user, query=""):
        self.client.force_login(user)
        r = self.client.get(f"/ticket/staff/{query}")
        self.assertEqual(r.status_code, 200)
        return {t.title for t in r.context["tickets"]}


class TestTabs(WorkbenchFixture):
    def test_unclaimed_tab(self):
        self.assertEqual(self.titles(self.staff, "?tab=unclaimed"), {"Unclaimed one"})

    def test_default_tab_is_unclaimed(self):
        self.assertEqual(self.titles(self.staff), {"Unclaimed one"})

    def test_mine_tab(self):
        self.assertEqual(self.titles(self.staff, "?tab=mine"), {"Mine one"})

    def test_department_tab(self):
        self.assertEqual(
            self.titles(self.staff, "?tab=department"), {"Unclaimed one", "Mine one", "Other staff one"}
        )

    def test_collab_tab(self):
        self.assertEqual(self.titles(self.staff, "?tab=collab"), {"Logistics with us"})

    def test_closed_tab(self):
        self.assertEqual(self.titles(self.staff, "?tab=closed"), {"Closed one"})

    def test_parent_sees_children_tab_not_badge(self):
        self.assertEqual(self.titles(self.top_staff, "?tab=unclaimed"), set())
        self.assertEqual(
            self.titles(self.top_staff, "?tab=children"),
            {"Unclaimed one", "Mine one", "Other staff one", "Own ticket"},
        )

    def test_view_all_children_tab_sees_everything_open(self):
        self.assertIn("Logistics with us", self.titles(self.viewer, "?tab=children"))

    def test_filters(self):
        self.assertEqual(
            self.titles(self.staff, f"?tab=department&priority={priority('urgent').pk}"), {"Unclaimed one"}
        )

    def test_search_by_number_and_title(self):
        self.assertEqual(self.titles(self.staff, "?tab=department&q=mine"), {"Mine one"})
        self.assertEqual(self.titles(self.staff, f"?tab=department&q=%23{self.other.pk}"), {"Other staff one"})
        self.assertEqual(self.titles(self.staff, "?tab=department&q=Pilot"), {"Unclaimed one", "Mine one", "Other staff one"})

    def test_non_staff_403(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get("/ticket/staff/").status_code, 403)
        self.client.force_login(self.requester)
        self.assertEqual(self.client.get("/ticket/staff/").status_code, 403)
