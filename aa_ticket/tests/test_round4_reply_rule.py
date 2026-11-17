"""Requirement B (0.4.0): only the requester and the current assignee may reply publicly."""

from django.core.exceptions import PermissionDenied
from django.test import TestCase

from aa_ticket import access, services
from aa_ticket.constants import ClosedReason, MessageKind, Status
from aa_ticket.exceptions import TicketActionError
from aa_ticket.tasks import check_unclaimed

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_lead = make_group("Leadership")
        cls.g_dip = make_group("Diplo")
        cls.g_fc = make_group("FC")
        cls.lead = make_department("Leadership", groups=[cls.g_lead])
        cls.dip = make_department("Diplo", groups=[cls.g_dip], parent=cls.lead)
        cls.fc = make_department("FC", groups=[cls.g_fc])
        cls.requester = make_user("Pilot A")
        cls.officer = make_user("Diplomat B", groups=[cls.g_dip])
        cls.colleague = make_user("Diplomat C", groups=[cls.g_dip])
        cls.leader = make_user("Leader D", groups=[cls.g_lead])
        cls.fc_officer = make_user("Fleet E", groups=[cls.g_fc])
        cls.boss = make_user("Boss F", perms=("basic_access", "view_all"))

    def setUp(self):
        self.t = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "Body")

    def can_reply(self, user):
        return access.can_act(fresh(user), fresh(self.t), "reply")


class TestRule(Fixture):
    def test_requester_always_can_reply_while_open(self):
        self.assertTrue(self.can_reply(self.requester))
        services.claim(fresh(self.officer), self.t)
        self.assertTrue(self.can_reply(self.requester))

    def test_unclaimed_staff_cannot_reply_but_can_note(self):
        for user in (self.officer, self.leader, self.boss):
            self.assertFalse(self.can_reply(user), user.username)
            self.assertTrue(access.can_act(fresh(user), fresh(self.t), "note"), user.username)
        with self.assertRaises(PermissionDenied):
            services.add_reply(fresh(self.officer), fresh(self.t), "hi")
        services.add_note(fresh(self.officer), fresh(self.t), "internal ok")

    def test_after_claim_only_assignee(self):
        services.claim(fresh(self.officer), self.t)
        services.invite(fresh(self.officer), fresh(self.t), self.fc)
        self.assertTrue(self.can_reply(self.officer))
        for user in (self.colleague, self.leader, self.fc_officer, self.boss):
            self.assertFalse(self.can_reply(user), user.username)
            self.assertTrue(access.can_act(fresh(user), fresh(self.t), "note"), user.username)

    def test_reassign_moves_reply_right(self):
        services.claim(fresh(self.officer), self.t)
        services.assign(fresh(self.officer), fresh(self.t), self.colleague)
        self.assertTrue(self.can_reply(self.colleague))
        self.assertFalse(self.can_reply(self.officer))

    def test_assignee_removed_from_group_cannot_reply(self):
        services.claim(fresh(self.officer), self.t)
        self.officer.groups.remove(self.g_dip)
        self.assertFalse(self.can_reply(self.officer))
        check_unclaimed()
        self.assertEqual(fresh(self.t).status, Status.OPEN)
        self.assertFalse(self.can_reply(self.officer))


class TestFinalReply(Fixture):
    def test_colleague_can_close_but_not_with_final_reply(self):
        services.claim(fresh(self.officer), self.t)
        with self.assertRaises(TicketActionError):
            services.close(fresh(self.colleague), fresh(self.t), ClosedReason.STAFF, final_reply="Bye")
        self.assertNotEqual(fresh(self.t).status, Status.CLOSED)
        services.close(fresh(self.colleague), fresh(self.t), ClosedReason.STAFF)
        self.assertEqual(fresh(self.t).status, Status.CLOSED)

    def test_assignee_and_requester_can_add_final_reply(self):
        services.claim(fresh(self.officer), self.t)
        services.close(fresh(self.officer), fresh(self.t), ClosedReason.STAFF, final_reply="Done")
        self.assertTrue(self.t.messages.filter(kind=MessageKind.REPLY, body="Done").exists())
        t2 = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help 2", "Body")
        services.close(fresh(self.requester), t2, ClosedReason.REQUESTER, final_reply="Thanks")
        self.assertTrue(t2.messages.filter(kind=MessageKind.REPLY, body="Thanks").exists())


class TestPage(Fixture):
    def page(self, user):
        self.client.force_login(user)
        return self.client.get(f"/ticket/{self.t.pk}/")

    def test_unclaimed_staff_sees_note_only_and_claim_hint(self):
        r = self.page(self.officer)
        self.assertNotContains(r, 'value="reply"')
        self.assertContains(r, 'value="internal"')
        self.assertContains(r, "Claim the ticket to reply to the requester.")

    def test_colleague_sees_who_handles(self):
        services.claim(fresh(self.officer), self.t)
        r = self.page(self.colleague)
        self.assertNotContains(r, 'value="reply"')
        self.assertContains(r, "This ticket is handled by Diplomat B. You can write an internal note.")
        self.assertNotContains(r, 'name="final_reply"')

    def test_assignee_sees_both(self):
        services.claim(fresh(self.officer), self.t)
        r = self.page(self.officer)
        self.assertContains(r, 'value="reply"')
        self.assertContains(r, 'value="internal"')
        self.assertContains(r, 'name="final_reply"')

    def test_direct_post_rejected_with_message(self):
        self.client.force_login(self.colleague)
        r = self.client.post(f"/ticket/{self.t.pk}/reply/", {"kind": "reply", "body": "sneaky"}, follow=True)
        self.assertContains(r, "Claim the ticket to reply to the requester.")
        self.assertFalse(self.t.messages.filter(body="sneaky").exists())


class TestReviewFollowups(Fixture):
    def test_stale_page_reply_after_reassign_shows_message(self):
        from unittest.mock import patch

        services.claim(fresh(self.officer), self.t)
        services.assign(fresh(self.officer), fresh(self.t), self.colleague)
        self.client.force_login(self.officer)
        # the pre-check passes on stale state; the locked check inside add_reply must still explain
        from aa_ticket import access as real_access

        real_hint = real_access.reply_hint
        calls = []

        def stale_first(user, ticket):
            calls.append(1)
            return "" if len(calls) == 1 else real_hint(user, ticket)

        with patch("aa_ticket.views.ticket.access.reply_hint", side_effect=stale_first):
            r = self.client.post(f"/ticket/{self.t.pk}/reply/", {"kind": "reply", "body": "late"}, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "handled by Diplomat C")
        self.assertFalse(self.t.messages.filter(body="late").exists())

    def test_assignee_who_is_only_collaborator_cannot_reply(self):
        self.officer.groups.add(self.g_fc)
        services.claim(fresh(self.officer), self.t)
        services.invite(fresh(self.officer), fresh(self.t), self.fc)
        self.officer.groups.remove(self.g_dip)
        self.assertFalse(self.can_reply(self.officer))
