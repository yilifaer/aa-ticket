import os

from django.test import TestCase

from aa_ticket import services
from aa_ticket.constants import Status
from aa_ticket.models import Ticket

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class DetailFixture(TestCase):
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
        cls.log_staff = make_user("Hauler D", groups=[cls.g_log])
        cls.outsider = make_user("Outsider E")

    def setUp(self):
        self.ticket = services.create_ticket(
            fresh(self.requester), self.dip, priority("normal"), "Standing request", "First message"
        )
        self.url = f"/ticket/{self.ticket.pk}/"

    def login(self, user):
        self.client.force_login(user)

    def post_action(self, action, data=None):
        return self.client.post(f"{self.url}action/{action}/", data or {}, follow=True)


class TestDetail(DetailFixture):
    def test_detail_requester(self):
        self.login(self.requester)
        r = self.client.get(self.url)
        self.assertContains(r, "Standing request")
        self.assertContains(r, "First message")

    def test_detail_other_users_ticket_404(self):
        self.login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get("/ticket/999999/").status_code, 404)

    def test_detail_hides_internal_for_requester(self):
        services.add_note(fresh(self.staff), self.ticket, "SECRET-NOTE")
        self.login(self.requester)
        self.assertNotContains(self.client.get(self.url), "SECRET-NOTE")
        self.login(self.staff)
        self.assertContains(self.client.get(self.url), "SECRET-NOTE")

    def test_text_is_escaped_and_links_clickable(self):
        services.add_reply(fresh(self.requester), self.ticket, "<script>x</script> see https://example.com/a")
        self.login(self.staff)
        r = self.client.get(self.url)
        self.assertNotContains(r, "<script>x</script>")
        self.assertContains(r, "&lt;script&gt;")
        self.assertContains(r, 'href="https://example.com/a"')

    def test_claim_button_only_for_controller(self):
        self.login(self.requester)
        self.assertNotContains(self.client.get(self.url), "action/claim/")
        self.login(self.log_staff)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.login(self.staff)
        self.assertContains(self.client.get(self.url), "action/claim/")

    def test_escalate_button_hidden_at_top(self):
        self.login(self.requester)
        self.assertContains(self.client.get(self.url), "action/escalate/")
        services.request_escalation(fresh(self.requester), self.ticket)
        self.assertNotContains(self.client.get(self.url), "action/escalate/")

    def test_internal_tab_only_for_staff(self):
        self.login(self.requester)
        self.assertNotContains(self.client.get(self.url), 'value="internal"')
        self.login(self.staff)
        self.assertContains(self.client.get(self.url), 'value="internal"')


class TestReply(DetailFixture):
    def test_reply_by_requester(self):
        self.login(self.requester)
        r = self.client.post(f"{self.url}reply/", {"kind": "reply", "body": "More info"}, follow=True)
        self.assertContains(r, "More info")

    def test_reply_internal_by_requester_forbidden(self):
        self.login(self.requester)
        r = self.client.post(f"{self.url}reply/", {"kind": "internal", "body": "x"})
        self.assertEqual(r.status_code, 403)

    def test_reply_by_outsider_404(self):
        self.login(self.outsider)
        r = self.client.post(f"{self.url}reply/", {"kind": "reply", "body": "x"})
        self.assertEqual(r.status_code, 404)

    def test_empty_reply_shows_error(self):
        self.login(self.requester)
        r = self.client.post(f"{self.url}reply/", {"kind": "reply", "body": " "}, follow=True)
        self.assertContains(r, "Please write a message")


class TestActions(DetailFixture):
    def test_actions_require_post(self):
        self.login(self.staff)
        self.assertEqual(self.client.get(f"{self.url}action/claim/").status_code, 405)
        self.assertEqual(self.client.get(f"{self.url}reply/").status_code, 405)

    def test_unknown_action_404(self):
        self.login(self.staff)
        self.assertEqual(self.client.post(f"{self.url}action/explode/").status_code, 404)

    def test_claim(self):
        self.login(self.staff)
        self.post_action("claim")
        self.assertEqual(fresh(self.ticket).assignee, self.staff)

    def test_action_error_shown_as_message(self):
        services.claim(fresh(self.staff2), self.ticket)
        Ticket.objects.filter(pk=self.ticket.pk).update(status=Status.OPEN)
        self.login(self.staff)
        r = self.post_action("claim")
        self.assertEqual(r.status_code, 200)

    def test_claim_by_requester_forbidden(self):
        self.login(self.requester)
        self.assertEqual(self.client.post(f"{self.url}action/claim/").status_code, 403)

    def test_assign_invite_transfer_priority_category(self):
        from aa_ticket.models import Category

        self.login(self.staff)
        self.post_action("assign", {"user_id": self.staff2.pk})
        self.assertEqual(fresh(self.ticket).assignee, self.staff2)
        self.post_action("invite", {"department_id": self.log.pk})
        self.assertIn(self.log, fresh(self.ticket).collaborating_departments.all())
        self.post_action("uninvite", {"department_id": self.log.pk})
        self.assertNotIn(self.log, fresh(self.ticket).collaborating_departments.all())
        self.post_action("priority", {"priority_id": priority("urgent").pk})
        self.assertEqual(fresh(self.ticket).priority, priority("urgent"))
        cat = Category.objects.create(department=self.dip, name="Blue")
        self.post_action("category", {"category_id": cat.pk})
        self.assertEqual(fresh(self.ticket).category, cat)
        self.post_action("transfer", {"department_id": self.log.pk, "reason": "Hauling"})
        t = fresh(self.ticket)
        self.assertEqual(t.department, self.log)
        self.assertNotIn(self.log, t.collaborating_departments.all())
        self.assertIn(self.dip, t.collaborating_departments.all())

    def test_transfer_without_keep(self):
        self.login(self.staff)
        self.post_action("transfer", {"department_id": self.log.pk, "keep": "", "keep_present": "1"})
        self.assertEqual(list(fresh(self.ticket).collaborating_departments.all()), [])

    def test_escalate_close_reopen_by_requester(self):
        self.login(self.requester)
        self.post_action("escalate", {"reason": "No answer"})
        self.assertEqual(fresh(self.ticket).escalations.count(), 1)
        self.post_action("close", {"final_reply": "Thanks"})
        t = fresh(self.ticket)
        self.assertEqual(t.status, Status.CLOSED)
        self.assertEqual(t.closed_reason, "requester")
        self.post_action("reopen")
        self.assertNotEqual(fresh(self.ticket).status, Status.CLOSED)

    def test_close_by_staff_reason(self):
        self.login(self.staff)
        self.post_action("close")
        self.assertEqual(fresh(self.ticket).closed_reason, "staff")


class TestTemplates(TestCase):
    def test_all_templates_extend_base_bs5(self):
        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "aa_ticket")
        checked = 0
        for dirpath, _dirs, files in os.walk(root):
            if "partials" in dirpath:
                continue
            for name in files:
                # dashboard_card.html is a fragment rendered into the Alliance Auth dashboard
                if not name.endswith(".html") or name == "dashboard_card.html" or name == "base.html" and dirpath == root:
                    continue
                with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                    first = fh.readline().strip()
                self.assertRegex(first, r'^{% extends "(allianceauth/base-bs5|aa_ticket/base|aa_ticket/manage/base)\.html" %}$', name)
                checked += 1
        with open(os.path.join(root, "base.html"), encoding="utf-8") as fh:
            self.assertEqual(fh.readline().strip(), '{% extends "allianceauth/base-bs5.html" %}')
        self.assertGreater(checked, 3)
