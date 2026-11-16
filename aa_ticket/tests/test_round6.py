"""0.4.2: items 2-12 of the open list after the whole-app review."""

import re
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from aa_ticket import access, services
from aa_ticket.auth_hooks import TicketDashboardHook, badge_cache_key
from aa_ticket.constants import Event
from aa_ticket.models import Category, Department, Priority, Ticket, TicketSettings
from aa_ticket.notifications import dispatch

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_dip = make_group("Dip")
        cls.g_fc = make_group("FC")
        cls.dip = make_department("Dip", groups=[cls.g_dip])
        cls.fc = make_department("FC", groups=[cls.g_fc])
        cls.requester = make_user("Pilot A")
        cls.officer = make_user("Diplomat B", groups=[cls.g_dip])
        cls.fc_officer = make_user("Fleet C", groups=[cls.g_fc])
        cls.admin = make_user("Admin D", perms=("basic_access", "manage"))

    def setUp(self):
        cache.clear()
        s = TicketSettings.get_solo()
        s.max_open_tickets = 500
        s.save()
        self.t = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "Body")


class TestItem2UnclaimedReplyNotice(Fixture):
    def run_dispatch(self, by_staff=False):
        with patch("aa_ticket.notifications.send_webhook") as wh, patch("aa_ticket.notifications.notify"), \
                patch("aa_ticket.notifications.dm.is_available", return_value=False):
            dispatch(Event.REPLIED, self.t.pk, self.requester.pk, {"by_staff": by_staff})
        return [tuple(c.args) for c in wh.delay.call_args_list]

    def test_requester_reply_on_unclaimed_ticket_pings_channel_without_mention(self):
        self.assertEqual(self.run_dispatch(), [(self.dip.pk, self.t.pk, Event.REPLIED, False)])

    def test_only_once_per_hour(self):
        self.run_dispatch()
        self.assertEqual(self.run_dispatch(), [])

    def test_not_for_claimed_tickets(self):
        services.claim(fresh(self.officer), self.t)
        cache.clear()
        self.assertEqual(self.run_dispatch(), [])

    def test_channel_text(self):
        from aa_ticket.discord.webhook import build_payload

        text = build_payload(self.t, Event.REPLIED, False, self.dip)["embeds"][0]["description"]
        self.assertIn("unclaimed", text.lower())


class TestItems3to5Manage(Fixture):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_cannot_deactivate_priority_with_open_tickets(self):
        p = priority("normal")
        r = self.client.post(f"/ticket/manage/priorities/{p.pk}/", {
            "name": "Normal", "color": "primary", "order": "20", "mention_on_new": "on", "remind_after_minutes": "1440", "escalate_after_minutes": "",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "open tickets")
        self.assertTrue(Priority.objects.get(pk=p.pk).is_active)

    def test_category_delete_confirm_explains(self):
        Category.objects.create(department=self.dip, name="Blue")
        r = self.client.get("/ticket/manage/categories/")
        self.assertContains(r, "lose their category")

    def test_duplicate_department_name_rejected(self):
        r = self.client.post("/ticket/manage/departments/0/", {
            "name": " dip ", "description": "", "parent": "", "accepts_submissions": "on", "is_active": "on", "order": "0",
            "new_webhook_url": "", "mention_role_ids": "",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Department.objects.filter(name__iexact="dip").count(), 1)
        r = self.client.post(f"/ticket/manage/departments/{self.dip.pk}/", {
            "name": "Dip", "description": "x", "parent": "", "groups": [self.g_dip.pk], "accepts_submissions": "on", "is_active": "on",
            "order": "0", "new_webhook_url": "", "mention_role_ids": "",
        })
        self.assertEqual(r.status_code, 302)


class TestItem6CategoryFilter(Fixture):
    def test_workbench_category_filter(self):
        cat = Category.objects.create(department=self.dip, name="Blue request")
        other = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "With cat", "Body", category=cat)
        self.client.force_login(self.officer)
        r = self.client.get("/ticket/staff/?tab=department")
        self.assertContains(r, 'name="category"')
        self.assertContains(r, "Blue request")
        r = self.client.get(f"/ticket/staff/?tab=department&category={cat.pk}")
        self.assertEqual([t.pk for t in r.context["tickets"]], [other.pk])


class TestItem7DashboardCache(Fixture):
    def render(self, user):
        request = RequestFactory().get("/dashboard/")
        request.user = user
        return TicketDashboardHook().render(request)

    def test_second_render_uses_cache_and_event_invalidates(self):
        user = fresh(self.officer)
        user.has_perm("aa_ticket.basic_access")
        first = self.render(user)
        with self.assertNumQueries(0):
            self.assertEqual(self.render(user), first)
        services.create_ticket(fresh(self.requester), self.dip, priority("urgent"), "Brand new", "Body")
        with patch("aa_ticket.notifications.send_webhook"), patch("aa_ticket.notifications.notify"):
            dispatch(Event.SUBMITTED, Ticket.objects.get(title="Brand new").pk, self.requester.pk, {})
        self.assertIn("Brand new", self.render(user))


class TestItem8VisibleTicketsQuery(Fixture):
    def test_no_distinct_and_no_m2m_join(self):
        with CaptureQueriesContext(connection) as ctx:
            list(access.visible_tickets(fresh(self.officer)))
        sql = ctx.captured_queries[-1]["sql"].upper()
        self.assertNotIn("DISTINCT", sql)
        self.assertNotIn("LEFT OUTER JOIN", sql)

    def test_collaborator_still_sees(self):
        services.invite(fresh(self.officer), self.t, self.fc)
        self.assertIn(self.t, access.visible_tickets(fresh(self.fc_officer)))


class TestItem9BadgeAfterTransfer(Fixture):
    def test_old_department_badge_cleared(self):
        cache.set(badge_cache_key(self.officer), 3, 60)
        with self.captureOnCommitCallbacks(execute=True), patch("aa_ticket.notifications.send_webhook"), patch("aa_ticket.notifications.notify"):
            services.transfer(fresh(self.officer), self.t, self.fc, keep_as_collaborator=False)
        self.assertIsNone(cache.get(badge_cache_key(self.officer)))


class TestItem10MyTicketsPages(Fixture):
    def test_paginated(self):
        base = fresh(self.t)
        Ticket.objects.bulk_create([
            Ticket(title=f"Bulk {i}", requester=self.requester, department=self.dip, priority=priority("normal"),
                   open_since=base.open_since, last_reply_at=base.last_reply_at) for i in range(60)
        ])
        self.client.force_login(self.requester)
        r = self.client.get("/ticket/mine/")
        self.assertEqual(len(r.context["tickets"]), 50)
        self.assertContains(r, "page=2")
        r = self.client.get("/ticket/mine/?page=2")
        self.assertEqual(len(r.context["tickets"]), 11)


class TestItem11NavHighlight(Fixture):
    def test_nav_active_on_submit_and_detail(self):
        self.client.force_login(self.requester)
        self.assertEqual(self.client.get("/ticket/new/").context["nav_active"], "mine")
        self.assertEqual(self.client.get(f"/ticket/new/{self.dip.pk}/").context["nav_active"], "mine")
        self.assertEqual(self.client.get(f"/ticket/{self.t.pk}/").context["nav_active"], "mine")
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(f"/ticket/{self.t.pk}/").context["nav_active"], "workbench")


class TestItem12Accessibility(Fixture):
    def test_modals_are_labelled(self):
        self.client.force_login(self.officer)
        html = self.client.get(f"/ticket/{self.t.pk}/").content.decode()
        modals = re.findall(r'<div class="modal fade" id="(modal-[a-z]+)"([^>]*)>', html)
        self.assertGreater(len(modals), 3)
        for modal_id, attrs in modals:
            self.assertIn(f'aria-labelledby="{modal_id}-title"', attrs)
            self.assertIn(f'id="{modal_id}-title"', html)

    def test_active_nav_has_aria_current(self):
        self.client.force_login(self.officer)
        html = self.client.get("/ticket/staff/?tab=mine").content.decode()
        self.assertGreaterEqual(html.count('aria-current="page"'), 2)

    def test_symbol_cells_have_text(self):
        Category.objects.create(department=self.dip, name="Blue", template="x")
        Category.objects.create(department=self.dip, name="Plain")
        self.client.force_login(self.admin)
        html = self.client.get("/ticket/manage/categories/").content.decode()
        self.assertEqual(html.count('<span class="visually-hidden">'), 2)
