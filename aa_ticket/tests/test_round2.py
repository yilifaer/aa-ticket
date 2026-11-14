"""Regression tests for the Raspberry Pi test report (2026-11-15)."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from aa_ticket import access, services
from aa_ticket.constants import ClosedReason, Event, Status
from aa_ticket.models import Category, Ticket

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class Fixture(TestCase):
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
        cls.log_staff = make_user("Hauler C", groups=[cls.g_log])
        cls.top_staff = make_user("Leader D", groups=[cls.g_top])

    def setUp(self):
        self.dispatch = patch("aa_ticket.services.dispatch").start()
        self.addCleanup(patch.stopall)

    def ticket(self, department=None, **kw):
        return services.create_ticket(
            fresh(self.requester), department or self.dip, priority("normal"), "Help", "Body", **kw
        )


class TestTimersResetOnTransfer(Fixture):
    def test_transfer_resets_auto_close_state(self):
        t = self.ticket()
        services.claim(fresh(self.staff), t)
        services.add_reply(fresh(self.staff), fresh(t), "Waiting for you")
        Ticket.objects.filter(pk=t.pk).update(
            autoclose_warned_at=timezone.now(), staff_reminded_at=timezone.now(),
            last_reply_at=timezone.now() - timedelta(days=10),
        )
        services.transfer(fresh(self.staff), fresh(t), self.log)
        t = fresh(t)
        self.assertFalse(t.last_reply_by_staff)
        self.assertIsNone(t.autoclose_warned_at)
        self.assertIsNone(t.staff_reminded_at)
        self.assertGreater(t.last_reply_at, timezone.now() - timedelta(minutes=1))

    def test_reopen_resets_staff_flag(self):
        t = self.ticket()
        services.claim(fresh(self.staff), t)
        services.add_reply(fresh(self.staff), fresh(t), "Done")
        services.close(fresh(self.requester), fresh(t), ClosedReason.REQUESTER)
        services.reopen(fresh(self.requester), fresh(t))
        self.assertFalse(fresh(t).last_reply_by_staff)


class TestCategoryRules(Fixture):
    def test_transfer_clears_category(self):
        cat = Category.objects.create(department=self.dip, name="Blue")
        t = self.ticket(category=cat)
        services.transfer(fresh(self.staff), t, self.log)
        self.assertIsNone(fresh(t).category)

    def test_inactive_category_rejected(self):
        from aa_ticket.exceptions import TicketActionError

        cat = Category.objects.create(department=self.dip, name="Old", is_active=False)
        t = self.ticket()
        with self.assertRaises(TicketActionError):
            services.change_category(fresh(self.staff), t, cat)

    def test_invalid_category_id_does_not_clear(self):
        cat = Category.objects.create(department=self.dip, name="Blue")
        t = self.ticket(category=cat)
        self.client.force_login(self.staff)
        r = self.client.post(f"/ticket/{t.pk}/action/category/", {"category_id": "zz"}, follow=True)
        self.assertEqual(fresh(t).category, cat)
        self.assertContains(r, "Please pick a category")
        self.client.post(f"/ticket/{t.pk}/action/category/", {"category_id": ""})
        self.assertIsNone(fresh(t).category)


class TestWorkbenchInputs(Fixture):
    def test_unicode_digit_filter_no_500(self):
        self.client.force_login(self.staff)
        for value in ("²", "١٢", "-1"):
            r = self.client.get("/ticket/staff/", {"tab": "department", "department": value, "priority": value})
            self.assertEqual(r.status_code, 200, value)

    def test_children_tab_excludes_own_tickets(self):
        own = services.create_ticket(fresh(self.top_staff), self.dip, priority("normal"), "Own one", "x")
        self.client.force_login(self.top_staff)
        r = self.client.get("/ticket/staff/?tab=children")
        self.assertNotIn(own, list(r.context["tickets"]))

    def test_page_zero_is_first_page(self):
        self.client.force_login(self.staff)
        r = self.client.get("/ticket/staff/?tab=department&page=0")
        self.assertEqual(r.context["page"].number, 1)
        r = self.client.get("/ticket/staff/?tab=department&page=-3")
        self.assertEqual(r.context["page"].number, 1)


class TestReopenInactiveDepartment(Fixture):
    def test_requester_cannot_reopen_in_inactive_department(self):
        t = self.ticket(department=self.log)
        services.close(fresh(self.requester), t, ClosedReason.REQUESTER)
        self.log.is_active = False
        self.log.save()
        self.assertFalse(access.can_act(fresh(self.requester), fresh(t), "reopen"))


class TestEscalationMessage(Fixture):
    def test_no_webhook_no_assignee_tells_truth_and_bells_parent_staff(self):
        t = self.ticket()
        self.client.force_login(self.requester)
        with patch("aa_ticket.notifications.notify") as notify, patch("aa_ticket.notifications.send_webhook"):
            self.dispatch.stop() if hasattr(self.dispatch, "stop") else None
            patch.stopall()
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(f"/ticket/{t.pk}/action/escalate/", {"reason": "x"}, follow=True)
            notified = [c.kwargs["user"].pk for c in notify.call_args_list]
        self.assertIn(self.top_staff.pk, notified)
        self.assertNotContains(r, "has been notified")


class TestManageNeedsBasicAccess(Fixture):
    def test_manage_only_user_gets_403_everywhere(self):
        u = make_user("Manager E", perms=("manage",))
        self.client.force_login(u)
        self.assertEqual(self.client.get("/ticket/manage/departments/").status_code, 403)
        self.assertEqual(self.client.get("/ticket/manage/settings/").status_code, 403)


class TestBreadcrumbTranslated(Fixture):
    def test_breadcrumb_aria_label_translated(self):
        self.client.force_login(self.requester)
        r = self.client.get(f"/ticket/new/{self.dip.pk}/", HTTP_ACCEPT_LANGUAGE="zh-hans")
        self.assertNotContains(r, 'aria-label="breadcrumb"')
