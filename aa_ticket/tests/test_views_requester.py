from django.core.cache import cache
from django.test import RequestFactory, TestCase

from aa_ticket import services
from aa_ticket.auth_hooks import TicketMenuItem
from aa_ticket.constants import Status
from aa_ticket.models import Category, Ticket

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class ViewFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_top = make_group("Leadership")
        cls.g_dip = make_group("Diplomats")
        cls.top = make_department("Leadership", groups=[cls.g_top], accepts_submissions=False)
        cls.dip = make_department("Diplomacy", groups=[cls.g_dip], parent=cls.top, description="Standings and treaties")
        cls.log = make_department("Logistics")
        cls.requester = make_user("Pilot A")
        cls.staff = make_user("Diplomat B", groups=[cls.g_dip])
        cls.top_staff = make_user("Leader C", groups=[cls.g_top])
        cls.outsider = make_user("Outsider D")
        cls.noperm = make_user("Guest E", perms=())

    def setUp(self):
        cache.clear()

    def new_ticket(self, user=None, department=None, title="Need standing"):
        return services.create_ticket(
            fresh(user or self.requester), department or self.dip, priority("normal"), title, "Body text"
        )


class TestMenu(ViewFixture):
    def render(self, user):
        request = RequestFactory().get("/")
        request.user = fresh(user)
        item = TicketMenuItem()
        return item, item.render(request)

    def test_menu_hidden_without_permission(self):
        item, html = self.render(self.noperm)
        self.assertEqual(html, "")

    def test_menu_shown_with_permission(self):
        item, html = self.render(self.requester)
        self.assertIn("/ticket/", html)
        self.assertIsNone(item.count)

    def test_badge_counts_direct_department_only_and_is_cached(self):
        self.new_ticket()
        self.new_ticket(user=self.staff, title="own ticket")
        item, _html = self.render(self.staff)
        self.assertEqual(item.count, 1)
        item, _html = self.render(self.top_staff)
        self.assertIsNone(item.count)
        user = fresh(self.staff)
        request = RequestFactory().get("/")
        request.user = user
        user.has_perm("aa_ticket.basic_access")  # warm permission cache
        with self.assertNumQueries(0):
            TicketMenuItem().render(request)


class TestMyTickets(ViewFixture):
    def test_requires_permission(self):
        self.client.force_login(self.noperm)
        self.assertEqual(self.client.get("/ticket/mine/").status_code, 403)

    def test_lists_own_tickets_only(self):
        mine = self.new_ticket()
        other = self.new_ticket(user=self.outsider, title="Other person")
        self.client.force_login(self.requester)
        r = self.client.get("/ticket/mine/")
        self.assertContains(r, mine.title)
        self.assertNotContains(r, other.title)

    def test_closed_tab(self):
        t = self.new_ticket(title="Old issue")
        Ticket.objects.filter(pk=t.pk).update(status=Status.CLOSED)
        self.client.force_login(self.requester)
        self.assertNotContains(self.client.get("/ticket/mine/"), "Old issue")
        self.assertContains(self.client.get("/ticket/mine/?tab=closed"), "Old issue")

    def test_empty_state_offers_submit(self):
        self.client.force_login(self.requester)
        r = self.client.get("/ticket/mine/")
        self.assertContains(r, 'href="/ticket/new/"')

    def test_index_is_overview(self):
        self.client.force_login(self.requester)
        r = self.client.get("/ticket/")
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "aa_ticket/overview.html")


class TestSubmit(ViewFixture):
    def test_choose_department_lists_submittable(self):
        self.client.force_login(self.requester)
        r = self.client.get("/ticket/new/")
        self.assertContains(r, "Diplomacy")
        self.assertContains(r, "Standings and treaties")
        self.assertNotContains(r, "Leadership")

    def test_submit_flow_creates_ticket_and_redirects(self):
        self.client.force_login(self.requester)
        r = self.client.post(
            f"/ticket/new/{self.dip.pk}/",
            {"title": "Blue please", "body": "We are friendly.", "priority": priority("urgent").pk},
        )
        ticket = Ticket.objects.get(title="Blue please")
        self.assertRedirects(r, f"/ticket/{ticket.pk}/")
        self.assertEqual(ticket.priority, priority("urgent"))

    def test_submit_department_not_allowed_404(self):
        self.client.force_login(self.requester)
        self.assertEqual(self.client.get(f"/ticket/new/{self.top.pk}/").status_code, 404)
        r = self.client.post(f"/ticket/new/{self.top.pk}/", {"title": "x", "body": "y", "priority": priority("low").pk})
        self.assertEqual(r.status_code, 404)

    def test_submit_validation_error_shown(self):
        self.client.force_login(self.requester)
        r = self.client.post(f"/ticket/new/{self.dip.pk}/", {"title": "", "body": "y", "priority": priority("low").pk})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_category_template_in_page(self):
        Category.objects.create(department=self.dip, name="Blue request", template="Corp name:\nCEO:")
        self.client.force_login(self.requester)
        r = self.client.get(f"/ticket/new/{self.dip.pk}/")
        self.assertContains(r, "Blue request")
        self.assertContains(r, 'data-template="Corp name:\nCEO:"')

    def test_open_ticket_limit_message(self):
        from aa_ticket.models import TicketSettings

        s = TicketSettings.get_solo()
        s.max_open_tickets = 1
        s.save()
        self.new_ticket()
        self.client.force_login(self.requester)
        r = self.client.post(
            f"/ticket/new/{self.dip.pk}/", {"title": "Second", "body": "y", "priority": priority("low").pk}
        )
        self.assertContains(r, "open tickets")
