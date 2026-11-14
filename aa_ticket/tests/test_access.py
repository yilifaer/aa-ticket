import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from allianceauth.authentication.models import State

from aa_ticket import access
from aa_ticket.constants import Status
from aa_ticket.models import EscalationRequest, Ticket

from .factories import make_department, make_group, make_user
from .test_models_tickets import make_ticket

STAFF_ACTIONS = ("claim", "assign", "invite", "transfer", "priority", "category")


def fresh(user):
    return User.objects.get(pk=user.pk)


class AccessFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_top = make_group("Leadership")
        cls.g_dip = make_group("Diplomats")
        cls.g_log = make_group("Logistics")
        cls.top = make_department("Leadership", groups=[cls.g_top], accepts_submissions=False)
        cls.dip = make_department("Diplomacy", groups=[cls.g_dip], parent=cls.top)
        cls.log = make_department("Logistics", groups=[cls.g_log])
        cls.requester = make_user("Pilot A")
        cls.dip_staff = make_user("Diplomat B", groups=[cls.g_dip])
        cls.top_staff = make_user("Leader C", groups=[cls.g_top])
        cls.log_staff = make_user("Hauler D", groups=[cls.g_log])
        cls.outsider = make_user("Outsider E")
        cls.viewer = make_user("Viewer F", perms=("basic_access", "view_all"))
        cls.superuser = User.objects.create_superuser("admin", "admin@example.com", "pw")
        cls.ticket = make_ticket(cls.requester, cls.dip)
        cls.ticket.collaborating_departments.add(cls.log)


class TestAccessMatrix(AccessFixture):
    def test_requester(self):
        u, t = fresh(self.requester), self.ticket
        self.assertTrue(access.can_view(u, t))
        self.assertFalse(access.can_view_internal(u, t))
        self.assertTrue(access.can_act(u, t, "reply"))
        self.assertFalse(access.can_act(u, t, "note"))
        self.assertTrue(access.can_act(u, t, "close"))
        for action in STAFF_ACTIONS:
            self.assertFalse(access.can_act(u, t, action), action)

    def test_department_staff(self):
        u, t = fresh(self.dip_staff), self.ticket
        self.assertTrue(access.can_view(u, t))
        self.assertTrue(access.can_view_internal(u, t))
        self.assertTrue(access.is_controller(u, t))
        for action in STAFF_ACTIONS + ("reply", "note", "close"):
            self.assertTrue(access.can_act(u, t, action), action)
        self.assertFalse(access.can_act(u, t, "escalate"))

    def test_parent_department_staff(self):
        u, t = fresh(self.top_staff), self.ticket
        self.assertTrue(access.can_view(u, t))
        self.assertTrue(access.can_view_internal(u, t))
        self.assertTrue(access.is_controller(u, t))
        self.assertTrue(access.can_act(u, t, "claim"))

    def test_collaborator(self):
        u, t = fresh(self.log_staff), self.ticket
        self.assertTrue(access.can_view(u, t))
        self.assertTrue(access.can_view_internal(u, t))
        self.assertTrue(access.can_act(u, t, "reply"))
        self.assertTrue(access.can_act(u, t, "note"))
        for action in STAFF_ACTIONS + ("close",):
            self.assertFalse(access.can_act(u, t, action), action)

    def test_outsider(self):
        u, t = fresh(self.outsider), self.ticket
        self.assertFalse(access.can_view(u, t))
        self.assertFalse(access.can_view_internal(u, t))
        for action in STAFF_ACTIONS + ("reply", "note", "close", "escalate", "reopen"):
            self.assertFalse(access.can_act(u, t, action), action)

    def test_view_all_is_controller(self):
        u, t = fresh(self.viewer), self.ticket
        self.assertTrue(access.can_view(u, t))
        self.assertTrue(access.can_view_internal(u, t))
        for action in STAFF_ACTIONS + ("reply", "note", "close"):
            self.assertTrue(access.can_act(u, t, action), action)

    def test_superuser_like_view_all_but_no_departments(self):
        u, t = fresh(self.superuser), self.ticket
        self.assertTrue(access.can_view(u, t))
        self.assertTrue(access.is_controller(u, t))
        self.assertEqual(access.staff_department_ids(u), set())

    def test_assignee_removed_from_department_loses_access(self):
        t = self.ticket
        t.assignee = self.dip_staff
        t.save()
        self.dip_staff.groups.remove(self.g_dip)
        u = fresh(self.dip_staff)
        self.assertFalse(access.can_view(u, t))
        self.assertFalse(access.can_view_internal(u, t))
        self.assertFalse(access.is_controller(u, t))
        self.assertNotIn(t.pk, set(access.visible_tickets(u).values_list("pk", flat=True)))

    def test_inactive_department_staff_lose_access(self):
        self.dip.is_active = False
        self.dip.save()
        self.assertFalse(access.can_view(fresh(self.dip_staff), self.ticket))
        # parent still sees it
        self.assertTrue(access.can_view(fresh(self.top_staff), self.ticket))


class TestRequesterIsStaff(AccessFixture):
    def test_requester_who_is_staff_never_sees_internal(self):
        ticket = make_ticket(self.dip_staff, self.dip)
        u = fresh(self.dip_staff)
        self.assertTrue(access.can_view(u, ticket))
        self.assertFalse(access.can_view_internal(u, ticket))
        self.assertFalse(access.is_staff_for(u, ticket))
        self.assertFalse(access.can_act(u, ticket, "claim"))
        self.assertFalse(access.can_act(u, ticket, "note"))
        self.assertTrue(access.can_act(u, ticket, "reply"))
        self.assertNotIn(self.dip_staff, access.assignable_users(ticket))

    def test_view_all_requester_never_sees_internal(self):
        ticket = make_ticket(self.viewer, self.dip)
        self.assertFalse(access.can_view_internal(fresh(self.viewer), ticket))


class TestGroupRemoval(AccessFixture):
    def test_removed_from_group_loses_access(self):
        self.assertTrue(access.can_view(fresh(self.dip_staff), self.ticket))
        self.dip_staff.groups.remove(self.g_dip)
        self.assertFalse(access.can_view(fresh(self.dip_staff), self.ticket))


class TestVisibleTickets(AccessFixture):
    def test_visible_tickets_matches_can_view(self):
        rnd = random.Random(42)
        departments = [self.top, self.dip, self.log]
        users = [self.requester, self.dip_staff, self.top_staff, self.log_staff, self.outsider, self.viewer]
        for i in range(20):
            t = make_ticket(rnd.choice(users), rnd.choice(departments), title=f"T{i}")
            if rnd.random() < 0.4:
                t.collaborating_departments.add(rnd.choice(departments))
            if rnd.random() < 0.3:
                t.assignee = rnd.choice(users)
                t.save()
        for user in users + [self.superuser]:
            u = fresh(user)
            expected = {t.pk for t in Ticket.objects.all() if access.can_view(u, t)}
            got = set(access.visible_tickets(u).values_list("pk", flat=True))
            self.assertEqual(got, expected, user.username)

    def test_visible_tickets_distinct(self):
        self.ticket.collaborating_departments.add(self.dip, self.top)
        qs = access.visible_tickets(fresh(self.top_staff))
        self.assertEqual(qs.count(), len(set(qs.values_list("pk", flat=True))))


class TestSubmittable(AccessFixture):
    def test_submittable_departments_restrictions(self):
        u = fresh(self.requester)
        self.assertEqual(set(access.submittable_departments(u)), {self.dip, self.log})
        member_state = State.objects.create(name="Fake Member State", priority=5000)
        self.log.submit_states.add(member_state)
        self.assertEqual(set(access.submittable_departments(fresh(self.requester))), {self.dip})
        special = make_group("Special")
        self.log.submit_groups.add(special)
        self.requester.groups.add(special)
        self.assertEqual(set(access.submittable_departments(fresh(self.requester))), {self.dip, self.log})
        self.log.is_active = False
        self.log.save()
        self.assertEqual(set(access.submittable_departments(fresh(self.requester))), {self.dip})

    def test_submit_state_matches(self):
        state = self.requester.profile.state
        self.dip.submit_states.add(state)
        self.assertIn(self.dip, access.submittable_departments(fresh(self.requester)))


class TestEscalationTarget(AccessFixture):
    def test_next_escalation_target_climbs_and_resets_after_transfer(self):
        root = make_department("Root")
        self.top.parent = root
        self.top.save()
        t = Ticket.objects.get(pk=self.ticket.pk)
        self.assertEqual(access.next_escalation_target(t), self.top)
        EscalationRequest.objects.create(ticket=t, to_department=self.top, cycle=t.escalation_cycle)
        self.assertEqual(access.next_escalation_target(t), root)
        EscalationRequest.objects.create(ticket=t, to_department=root, cycle=t.escalation_cycle)
        self.assertIsNone(access.next_escalation_target(t))
        self.assertFalse(access.can_act(fresh(self.requester), t, "escalate"))
        t.escalation_cycle += 1
        t.save()
        self.assertEqual(access.next_escalation_target(t), self.top)

    def test_no_parent_no_target(self):
        t = make_ticket(self.requester, self.log)
        self.assertIsNone(access.next_escalation_target(t))


class TestReopen(AccessFixture):
    def _closed(self, days_ago):
        t = make_ticket(self.requester, self.dip, status=Status.CLOSED)
        t.closed_at = timezone.now() - timedelta(days=days_ago)
        t.save()
        return t

    def test_requester_reopen_window(self):
        u = fresh(self.requester)
        self.assertTrue(access.can_act(u, self._closed(6), "reopen"))
        self.assertFalse(access.can_act(u, self._closed(8), "reopen"))

    def test_staff_reopen_any_time(self):
        self.assertTrue(access.can_act(fresh(self.dip_staff), self._closed(100), "reopen"))

    def test_closed_ticket_no_reply_or_close(self):
        t = self._closed(1)
        self.assertFalse(access.can_act(fresh(self.requester), t, "reply"))
        self.assertFalse(access.can_act(fresh(self.dip_staff), t, "close"))
        self.assertFalse(access.can_act(fresh(self.dip_staff), t, "claim"))


class TestStatsScope(AccessFixture):
    def test_stats_scope(self):
        self.assertIsNone(access.stats_department_ids(fresh(self.viewer)))
        self.assertEqual(access.stats_department_ids(fresh(self.top_staff)), {self.top.pk, self.dip.pk})
        self.assertEqual(access.stats_department_ids(fresh(self.dip_staff)), {self.dip.pk})
        self.assertEqual(access.stats_department_ids(fresh(self.outsider)), set())


class TestClaimOnlyOpen(AccessFixture):
    def test_claim_only_when_open(self):
        t = Ticket.objects.get(pk=self.ticket.pk)
        t.status = Status.IN_PROGRESS
        t.save()
        self.assertFalse(access.can_act(fresh(self.dip_staff), t, "claim"))
