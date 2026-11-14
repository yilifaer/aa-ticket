from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from aa_ticket import services
from aa_ticket.constants import ClosedReason, Event, MessageKind, Status
from aa_ticket.exceptions import TicketActionError
from aa_ticket.models import Category, EscalationRequest, Ticket, TicketSettings

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class ServiceFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_root = make_group("Root staff")
        cls.g_top = make_group("Leadership")
        cls.g_dip = make_group("Diplomats")
        cls.g_log = make_group("Logistics")
        cls.root = make_department("Root", groups=[cls.g_root])
        cls.top = make_department("Leadership", groups=[cls.g_top], parent=cls.root)
        cls.dip = make_department("Diplomacy", groups=[cls.g_dip], parent=cls.top)
        cls.log = make_department("Logistics", groups=[cls.g_log])
        cls.requester = make_user("Pilot A")
        cls.dip_staff = make_user("Diplomat B", groups=[cls.g_dip])
        cls.dip_staff2 = make_user("Diplomat C", groups=[cls.g_dip])
        cls.log_staff = make_user("Hauler D", groups=[cls.g_log])
        cls.outsider = make_user("Outsider E")

    def new_ticket(self, **kwargs):
        kwargs.setdefault("department", self.dip)
        kwargs.setdefault("priority", priority("normal"))
        kwargs.setdefault("title", "Standing request")
        kwargs.setdefault("body", "Please set blue standing.")
        return services.create_ticket(fresh(self.requester), **kwargs)

    def claimed_ticket(self):
        t = self.new_ticket()
        services.claim(fresh(self.dip_staff), t)
        return fresh(t)


class TestCreate(ServiceFixture):
    def test_create_ticket(self):
        t = self.new_ticket()
        self.assertEqual(t.status, Status.OPEN)
        self.assertEqual(t.requester_character, self.requester.profile.main_character)
        self.assertFalse(t.last_reply_by_staff)
        self.assertIsNotNone(t.open_since)
        kinds = list(t.messages.values_list("kind", "event_type"))
        self.assertIn((MessageKind.REPLY, ""), kinds)
        self.assertEqual(t.messages.filter(kind=MessageKind.REPLY).get().body, "Please set blue standing.")

    def test_create_requires_submittable_department(self):
        self.dip.accepts_submissions = False
        self.dip.save()
        with self.assertRaises(PermissionDenied):
            self.new_ticket()

    def test_create_rejects_inactive_priority(self):
        p = priority("low")
        p.is_active = False
        p.save()
        with self.assertRaises(TicketActionError):
            self.new_ticket(priority=p)

    def test_create_rejects_foreign_category(self):
        cat = Category.objects.create(department=self.log, name="Freight")
        with self.assertRaises(TicketActionError):
            self.new_ticket(category=cat)

    def test_create_rejects_empty_title(self):
        with self.assertRaises(TicketActionError):
            self.new_ticket(title="   ")

    def test_open_ticket_limit(self):
        s = TicketSettings.get_solo()
        s.max_open_tickets = 2
        s.save()
        self.new_ticket()
        self.new_ticket()
        with self.assertRaises(TicketActionError) as ctx:
            self.new_ticket()
        self.assertIn("2", ctx.exception.message)


class TestReplies(ServiceFixture):
    def test_reply_by_staff_sets_flag_and_clears_warnings(self):
        t = self.claimed_ticket()
        Ticket.objects.filter(pk=t.pk).update(autoclose_warned_at=timezone.now(), staff_reminded_at=timezone.now())
        msg = services.add_reply(fresh(self.dip_staff), fresh(t), "Done.")
        t = fresh(t)
        self.assertTrue(t.last_reply_by_staff)
        self.assertIsNone(t.autoclose_warned_at)
        self.assertIsNone(t.staff_reminded_at)
        self.assertEqual(msg.author_department, self.dip)

    def test_reply_by_requester_clears_staff_flag(self):
        t = self.claimed_ticket()
        services.add_reply(fresh(self.dip_staff), t, "Need more info.")
        services.add_reply(fresh(self.requester), fresh(t), "Here it is.")
        self.assertFalse(fresh(t).last_reply_by_staff)

    def test_reply_empty_rejected(self):
        t = self.new_ticket()
        with self.assertRaises(TicketActionError):
            services.add_reply(fresh(self.requester), t, "  ")

    def test_reply_by_outsider_denied(self):
        with self.assertRaises(PermissionDenied):
            services.add_reply(fresh(self.outsider), self.new_ticket(), "hi")

    def test_note_does_not_touch_last_reply(self):
        t = self.claimed_ticket()
        before = t.last_reply_at
        msg = services.add_note(fresh(self.dip_staff), t, "Internal")
        t = fresh(t)
        self.assertEqual(t.last_reply_at, before)
        self.assertFalse(t.last_reply_by_staff)
        self.assertEqual(msg.kind, MessageKind.INTERNAL)

    def test_note_by_requester_denied(self):
        with self.assertRaises(PermissionDenied):
            services.add_note(fresh(self.requester), self.new_ticket(), "x")


class TestClaimAssign(ServiceFixture):
    def test_claim(self):
        t = self.claimed_ticket()
        self.assertEqual(t.status, Status.IN_PROGRESS)
        self.assertEqual(t.assignee, self.dip_staff)
        self.assertIsNotNone(t.claimed_at)
        self.assertTrue(t.messages.filter(event_type=Event.CLAIMED).exists())

    def test_claim_is_atomic(self):
        t = self.new_ticket()
        stale = fresh(t)
        services.claim(fresh(self.dip_staff2), fresh(t))
        with self.assertRaises(TicketActionError) as ctx:
            services.claim(fresh(self.dip_staff), stale)
        self.assertIn("Diplomat C", ctx.exception.message)
        self.assertEqual(fresh(t).assignee, self.dip_staff2)

    def test_claim_by_collaborator_denied(self):
        t = self.new_ticket()
        services.invite(fresh(self.dip_staff), t, self.log)
        with self.assertRaises(PermissionDenied):
            services.claim(fresh(self.log_staff), fresh(t))

    def test_assign(self):
        t = self.new_ticket()
        services.assign(fresh(self.dip_staff), t, self.dip_staff2)
        t = fresh(t)
        self.assertEqual(t.assignee, self.dip_staff2)
        self.assertEqual(t.status, Status.IN_PROGRESS)

    def test_assign_to_non_staff_rejected(self):
        t = self.new_ticket()
        with self.assertRaises(TicketActionError):
            services.assign(fresh(self.dip_staff), t, self.outsider)
        with self.assertRaises(TicketActionError):
            services.assign(fresh(self.dip_staff), t, self.requester)


class TestInviteTransfer(ServiceFixture):
    def test_invite_and_uninvite(self):
        t = self.claimed_ticket()
        services.invite(fresh(self.dip_staff), t, self.log)
        self.assertIn(self.log, fresh(t).collaborating_departments.all())
        with self.assertRaises(TicketActionError):
            services.invite(fresh(self.dip_staff), fresh(t), self.dip)
        services.uninvite(fresh(self.dip_staff), fresh(t), self.log)
        self.assertNotIn(self.log, fresh(t).collaborating_departments.all())

    def test_transfer_resets_timers_and_keeps_collaborator(self):
        t = self.claimed_ticket()
        Ticket.objects.filter(pk=t.pk).update(reminded_at=timezone.now(), escalated_at=timezone.now())
        services.transfer(fresh(self.dip_staff), fresh(t), self.log, reason="Logistics issue")
        t = fresh(t)
        self.assertEqual(t.department, self.log)
        self.assertEqual(t.status, Status.OPEN)
        self.assertIsNone(t.assignee)
        self.assertIsNone(t.reminded_at)
        self.assertIsNone(t.escalated_at)
        self.assertEqual(t.escalation_cycle, 1)
        self.assertEqual(list(t.collaborating_departments.all()), [self.dip])

    def test_transfer_without_keep(self):
        t = self.claimed_ticket()
        services.invite(fresh(self.dip_staff), t, self.log)
        services.transfer(fresh(self.dip_staff), fresh(t), self.log, keep_as_collaborator=False)
        t = fresh(t)
        self.assertEqual(list(t.collaborating_departments.all()), [])

    def test_transfer_to_same_department_rejected(self):
        t = self.claimed_ticket()
        with self.assertRaises(TicketActionError):
            services.transfer(fresh(self.dip_staff), t, self.dip)

    def test_transfer_to_inactive_rejected(self):
        t = self.claimed_ticket()
        self.log.is_active = False
        self.log.save()
        with self.assertRaises(TicketActionError):
            services.transfer(fresh(self.dip_staff), t, self.log)


class TestEscalation(ServiceFixture):
    def test_escalation_twice_goes_to_grandparent(self):
        t = self.claimed_ticket()
        first = services.request_escalation(fresh(self.requester), t, reason="Not happy")
        self.assertEqual(first.to_department, self.top)
        second = services.request_escalation(fresh(self.requester), fresh(t))
        self.assertEqual(second.to_department, self.root)
        t = fresh(t)
        self.assertEqual(set(t.collaborating_departments.all()), {self.top, self.root})
        self.assertEqual(t.department, self.dip)
        self.assertEqual(t.assignee, self.dip_staff)

    def test_escalation_at_top_raises(self):
        t = self.claimed_ticket()
        services.request_escalation(fresh(self.requester), t)
        services.request_escalation(fresh(self.requester), fresh(t))
        with self.assertRaises(PermissionDenied):
            services.request_escalation(fresh(self.requester), fresh(t))

    def test_escalation_by_staff_denied(self):
        with self.assertRaises(PermissionDenied):
            services.request_escalation(fresh(self.dip_staff), self.claimed_ticket())

    def test_transfer_resets_escalation(self):
        t = self.claimed_ticket()
        services.request_escalation(fresh(self.requester), t)
        services.transfer(fresh(self.dip_staff), fresh(t), self.top)
        req = services.request_escalation(fresh(self.requester), fresh(t))
        self.assertEqual(req.to_department, self.root)
        self.assertEqual(EscalationRequest.objects.filter(ticket=t).count(), 2)


class TestPriorityCategory(ServiceFixture):
    def test_change_priority_and_category(self):
        t = self.claimed_ticket()
        services.change_priority(fresh(self.dip_staff), t, priority("urgent"))
        self.assertEqual(fresh(t).priority, priority("urgent"))
        cat = Category.objects.create(department=self.dip, name="Blue")
        services.change_category(fresh(self.dip_staff), fresh(t), cat)
        self.assertEqual(fresh(t).category, cat)
        services.change_category(fresh(self.dip_staff), fresh(t), None)
        self.assertIsNone(fresh(t).category)

    def test_change_priority_by_requester_denied(self):
        with self.assertRaises(PermissionDenied):
            services.change_priority(fresh(self.requester), self.new_ticket(), priority("urgent"))


class TestCloseReopen(ServiceFixture):
    def test_close_by_requester(self):
        t = self.claimed_ticket()
        services.close(fresh(self.requester), t, ClosedReason.REQUESTER)
        t = fresh(t)
        self.assertEqual(t.status, Status.CLOSED)
        self.assertEqual(t.closed_reason, ClosedReason.REQUESTER)
        self.assertEqual(t.closed_by, self.requester)

    def test_close_with_final_reply(self):
        t = self.claimed_ticket()
        services.close(fresh(self.dip_staff), t, ClosedReason.STAFF, final_reply="All done.")
        t = fresh(t)
        self.assertEqual(t.status, Status.CLOSED)
        self.assertTrue(t.messages.filter(kind=MessageKind.REPLY, body="All done.").exists())

    def test_auto_close_without_actor(self):
        t = self.claimed_ticket()
        services.add_reply(fresh(self.dip_staff), t, "Please confirm.")
        services.close(None, fresh(t), ClosedReason.AUTO)
        t = fresh(t)
        self.assertEqual(t.closed_reason, ClosedReason.AUTO)
        self.assertIsNone(t.closed_by)

    def test_auto_close_refused_while_waiting_for_staff(self):
        t = self.claimed_ticket()
        services.close(None, t, ClosedReason.AUTO)
        self.assertEqual(fresh(t).status, Status.IN_PROGRESS)

    def test_close_by_outsider_denied(self):
        with self.assertRaises(PermissionDenied):
            services.close(fresh(self.outsider), self.claimed_ticket(), ClosedReason.STAFF)

    def test_reopen_with_assignee_goes_in_progress(self):
        t = self.claimed_ticket()
        services.close(fresh(self.requester), t, ClosedReason.REQUESTER)
        services.reopen(fresh(self.requester), fresh(t))
        t = fresh(t)
        self.assertEqual(t.status, Status.IN_PROGRESS)
        self.assertIsNone(t.closed_at)

    def test_reopen_without_assignee_goes_open(self):
        t = self.new_ticket()
        services.close(fresh(self.requester), t, ClosedReason.REQUESTER)
        services.reopen(fresh(self.dip_staff), fresh(t))
        self.assertEqual(fresh(t).status, Status.OPEN)

    def test_reopen_by_requester_after_window_denied(self):
        t = self.claimed_ticket()
        services.close(fresh(self.requester), t, ClosedReason.REQUESTER)
        Ticket.objects.filter(pk=t.pk).update(closed_at=timezone.now() - timedelta(days=30))
        with self.assertRaises(PermissionDenied):
            services.reopen(fresh(self.requester), fresh(t))


class TestDispatch(ServiceFixture):
    def test_dispatch_called_on_commit(self):
        t = self.new_ticket()
        with patch("aa_ticket.services.dispatch") as mock_dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                services.claim(fresh(self.dip_staff), fresh(t))
        mock_dispatch.assert_called_once()
        args = mock_dispatch.call_args[0]
        self.assertEqual(args[0], Event.CLAIMED)
        self.assertEqual(args[1], t.pk)
        self.assertEqual(args[2], self.dip_staff.pk)
        self.assertIsInstance(args[3], dict)

    def test_reply_dispatch_marks_staff(self):
        t = self.claimed_ticket()
        with patch("aa_ticket.services.dispatch") as mock_dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                services.add_reply(fresh(self.dip_staff), fresh(t), "hi")
        self.assertEqual(mock_dispatch.call_args[0][0], Event.REPLIED)
        self.assertTrue(mock_dispatch.call_args[0][3]["by_staff"])
