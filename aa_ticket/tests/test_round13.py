"""1.0.1: further pitfalls from the AA App Checklist review (section 7)."""

import io
import os
from datetime import timedelta
from unittest.mock import patch

from PIL import Image

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from allianceauth.authentication.models import State

from aa_ticket import access, services
from aa_ticket.checks import check_site_url
from aa_ticket.constants import ClosedReason, Status
from aa_ticket.forms import DepartmentForm
from aa_ticket.models import Attachment, Department, Ticket, TicketMessage, TicketSettings, UserPreference
from aa_ticket.services import TicketActionError
from aa_ticket.views.manage import joinable_groups

from .factories import make_department, make_group, make_user, priority


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def png():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="PNG")
    return SimpleUploadedFile("a.png", buf.getvalue())


class TestStaffGroupWarning(TestCase):
    def test_internal_group_without_states_is_fine(self):
        g = make_group("Diplomats")
        g.authgroup.internal = True
        g.authgroup.save()
        dept = make_department("Diplomacy", groups=[g])
        self.assertEqual(joinable_groups(dept), [])

    def test_group_restricted_to_a_state_is_not_flagged(self):
        # In Alliance Auth a group's states only limit who may join; nobody is added automatically.
        g = make_group("Diplomats")
        g.authgroup.internal = True
        g.authgroup.save()
        g.authgroup.states.add(State.objects.create(name="Fake Member", priority=5000))
        dept = make_department("Diplomacy", groups=[g])
        self.assertEqual(joinable_groups(dept), [])

    def test_corp_autogroup_is_flagged(self):
        g = make_group("Corp Some Corp")
        g.authgroup.internal = True
        g.authgroup.save()
        dept = make_department("Diplomacy", groups=[g])
        with patch("aa_ticket.views.manage.auto_filled_group_ids", return_value={g.pk}):
            rows = joinable_groups(dept)
        self.assertEqual([(r["name"], r["auto"]) for r in rows], [("Corp Some Corp", True)])

    def test_without_autogroups_app_nothing_is_auto(self):
        from aa_ticket.views.manage import auto_filled_group_ids

        with patch("django.apps.apps.is_installed", return_value=False):
            self.assertEqual(auto_filled_group_ids(), set())

    def test_joinable_group_is_flagged(self):
        g = make_group("Open")
        g.authgroup.internal = False
        g.authgroup.save()
        dept = make_department("Diplomacy", groups=[g])
        self.assertEqual([(r["name"], r["auto"]) for r in joinable_groups(dept)], [("Open", False)])

    def test_warning_text_on_manage_page(self):
        admin = make_user("Admin E", perms=("basic_access", "manage"))
        g = make_group("Corp Some Corp")
        g.authgroup.internal = True
        g.authgroup.save()
        make_department("Diplomacy", groups=[g])
        self.client.force_login(admin)
        with translation.override("en"), patch("aa_ticket.views.manage.auto_filled_group_ids", return_value={g.pk}):
            html = self.client.get(reverse("aa_ticket:manage_departments")).content.decode()
        self.assertIn("fills this group automatically with a whole corporation or alliance", html)


class TestSmallFixes(TestCase):
    @override_settings(SITE_URL="")
    def test_missing_site_url_warns(self):
        self.assertEqual([w.id for w in check_site_url(None)], ["aa_ticket.W004"])

    @override_settings(SITE_URL="https://auth.example.com")
    def test_site_url_set_no_warning(self):
        self.assertEqual(check_site_url(None), [])

    def test_opening_prefs_page_does_not_create_a_row(self):
        user = make_user("Pilot A")
        self.client.force_login(user)
        self.client.get(reverse("aa_ticket:prefs"))
        self.assertFalse(UserPreference.objects.filter(user=user).exists())
        self.assertTrue(UserPreference.for_user(user).discord_dm_enabled)

    def test_image_cache_is_short(self):
        dept = make_department("Diplomacy")
        user = make_user("Pilot A")
        services.create_ticket(user, dept, priority("normal"), "Help", "Body", images=[png()])
        self.client.force_login(user)
        r = self.client.get(reverse("aa_ticket:attachment", args=[Attachment.objects.get().pk]))
        self.assertEqual(r["Cache-Control"], "private, max-age=300")


class TestSubmitRestriction(TestCase):
    def setUp(self):
        self.allowed = make_group("Allowed")
        self.member = make_user("Pilot A", groups=[self.allowed])
        self.other = make_user("Pilot B")
        self.dept = make_department("Diplomacy")

    def form(self, groups):
        data = {
            "name": "Diplomacy", "description": "", "order": 0, "is_active": "on", "accepts_submissions": "on",
            "submit_groups": [g.pk for g in groups], "submit_states": [], "groups": [], "mention_role_ids": "",
        }
        return DepartmentForm(data=data, instance=self.dept)

    def test_picking_groups_turns_the_restriction_on(self):
        f = self.form([self.allowed])
        self.assertTrue(f.is_valid(), f.errors)
        f.save()
        self.assertTrue(fresh(self.dept).restrict_submissions)
        self.assertIn(self.dept, access.submittable_departments(fresh(self.member)))
        self.assertNotIn(self.dept, access.submittable_departments(fresh(self.other)))

    def test_clearing_the_lists_opens_the_department(self):
        self.form([self.allowed]).save()
        f = self.form([])
        self.assertTrue(f.is_valid(), f.errors)
        f.save()
        self.assertFalse(fresh(self.dept).restrict_submissions)
        self.assertIn(self.dept, access.submittable_departments(fresh(self.other)))

    def test_deleting_the_only_group_closes_the_department(self):
        self.form([self.allowed]).save()
        self.allowed.delete()
        self.assertNotIn(self.dept, access.submittable_departments(fresh(self.member)))
        self.assertNotIn(self.dept, access.submittable_departments(fresh(self.other)))

    def test_manage_page_warns_when_nobody_can_submit(self):
        self.form([self.allowed]).save()
        self.allowed.delete()
        admin = make_user("Admin E", perms=("basic_access", "manage"))
        self.client.force_login(admin)
        with translation.override("en"):
            html = self.client.get(reverse("aa_ticket:manage_departments")).content.decode()
        self.assertIn("nobody can submit tickets", html)

    def test_migration_turns_on_restriction_for_existing_lists(self):
        import importlib

        from django.apps import apps

        migration = importlib.import_module("aa_ticket.migrations.0006_submit_restriction_and_hourly_limit")
        self.dept.submit_groups.add(self.allowed)
        open_dept = make_department("Logistics")
        migration.mark_restricted(apps, None)
        self.assertTrue(fresh(self.dept).restrict_submissions)
        self.assertFalse(fresh(open_dept).restrict_submissions)


class TestHourlyLimit(TestCase):
    def setUp(self):
        self.dept = make_department("Diplomacy")
        self.user = make_user("Pilot A")
        s = TicketSettings.get_solo()
        s.max_open_tickets = 50
        s.max_new_tickets_per_hour = 2
        s.save()

    def submit(self):
        t = services.create_ticket(fresh(self.user), self.dept, priority("normal"), "Help", "Body")
        services.close(fresh(self.user), t, ClosedReason.REQUESTER)
        return t

    def test_third_ticket_within_an_hour_is_refused(self):
        self.submit()
        self.submit()
        with translation.override("en"), self.assertRaises(TicketActionError) as ctx:
            self.submit()
        self.assertIn("2 tickets per hour", str(ctx.exception))
        self.assertIn("min", str(ctx.exception))

    def test_older_tickets_do_not_count(self):
        self.submit()
        t = self.submit()
        Ticket.objects.filter(requester=self.user).update(created_at=timezone.now() - timedelta(minutes=61))
        self.submit()
        self.assertEqual(Ticket.objects.filter(requester=self.user).count(), 3)
        self.assertTrue(t.pk)

    def test_zero_means_no_limit(self):
        s = TicketSettings.get_solo()
        s.max_new_tickets_per_hour = 0
        s.save()
        for _ in range(4):
            self.submit()
        self.assertEqual(Ticket.objects.filter(requester=self.user).count(), 4)

    def test_default_is_five(self):
        self.assertEqual(TicketSettings._meta.get_field("max_new_tickets_per_hour").default, 5)


class TestEraseUser(TestCase):
    def setUp(self):
        self.g = make_group("Diplomats")
        self.dept = make_department("Diplomacy", groups=[self.g])
        self.leaver = make_user("Leaving Pilot")
        self.staff = make_user("Diplomat B", groups=[self.g])
        self.other = make_user("Other Pilot")
        # the leaver's own ticket, with an image
        self.own = services.create_ticket(fresh(self.leaver), self.dept, priority("normal"), "Mine", "My text",
                                          images=[png()])
        # someone else's ticket where the leaver is staff
        self.leaver.groups.add(self.g)
        self.foreign = services.create_ticket(fresh(self.other), self.dept, priority("normal"), "Theirs", "Body")
        services.claim(fresh(self.leaver), self.foreign)
        services.add_reply(fresh(self.leaver), fresh(self.foreign), "Reply by leaver")
        self.files = [a.file.path for a in Attachment.objects.filter(message__ticket=self.own)]

    def erase(self, *args):
        if "--yes" in args:
            User.objects.filter(pk=self.leaver.pk).update(is_active=False)
        out = io.StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("aa_ticket_erase_user", self.leaver.username, *args, stdout=out)
        return out.getvalue()

    def test_dry_run_by_default_changes_nothing(self):
        out = self.erase()
        self.assertIn("1 ticket", out)
        self.assertIn("--yes", out)
        self.assertTrue(Ticket.objects.filter(pk=self.own.pk).exists())

    def test_erase_removes_own_tickets_and_files(self):
        self.erase("--yes")
        self.assertFalse(Ticket.objects.filter(pk=self.own.pk).exists())
        for path in self.files:
            self.assertFalse(os.path.exists(path))

    def test_erase_anonymises_activity_in_other_tickets(self):
        self.erase("--yes")
        foreign = fresh(self.foreign)
        self.assertIsNone(foreign.assignee_id)
        self.assertEqual(foreign.status, Status.OPEN)
        reply = TicketMessage.objects.get(ticket=foreign, body="Reply by leaver")
        self.assertIsNone(reply.author_id)
        for m in TicketMessage.objects.filter(ticket=foreign):
            self.assertNotIn("Leaving Pilot", str(m.event_data))

    def test_user_can_then_be_deleted_in_aa(self):
        self.erase("--yes")
        User.objects.filter(pk=self.leaver.pk).delete()
        self.assertFalse(User.objects.filter(pk=self.leaver.pk).exists())

    def test_deleted_author_is_shown_as_deleted_user_not_system(self):
        self.erase("--yes")
        self.leaver.groups.remove(self.g)  # otherwise still offered in the "Assign" list
        self.client.force_login(self.staff)
        with translation.override("en"):
            html = self.client.get(reverse("aa_ticket:detail", args=[self.foreign.pk])).content.decode()
        self.assertIn("Deleted user", html)
        self.assertNotIn("Leaving Pilot", html)

    def test_unknown_user(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("aa_ticket_erase_user", "nobody-here", stdout=io.StringIO())


class TestEraseTouchesOnlyThePerson(TestCase):
    """Review findings: erasing must never change other people's records by matching numbers or text."""

    def setUp(self):
        self.g = make_group("Diplomats")
        self.leaver = make_user("Leaving Pilot", groups=[self.g])
        self.dept = make_department("Diplomacy", groups=[self.g])
        self.bystander = make_user("Bystander")

    def erase(self):
        User.objects.filter(pk=self.leaver.pk).update(is_active=False)
        with self.captureOnCommitCallbacks(execute=True):
            call_command("aa_ticket_erase_user", self.leaver.username, "--yes", stdout=io.StringIO())

    def test_department_id_equal_to_user_pk_is_kept(self):
        dept = Department.objects.filter(pk=self.leaver.pk).first() or Department.objects.create(
            pk=self.leaver.pk, name="Same Number"
        )
        dept.groups.add(self.g)
        t = services.create_ticket(fresh(self.bystander), dept, priority("normal"), "Help", "Body")
        self.erase()
        submitted = TicketMessage.objects.get(ticket=t, event_type="submitted")
        self.assertEqual(submitted.event_data["department_id"], dept.pk)

    def test_department_named_like_the_person_is_kept(self):
        dept = make_department("Leaving Pilot", groups=[self.g])
        t = services.create_ticket(fresh(self.bystander), dept, priority("normal"), "Help", "Body")
        self.erase()
        submitted = TicketMessage.objects.get(ticket=t, event_type="submitted")
        self.assertEqual(submitted.event_data["department"], "Leaving Pilot")

    def test_old_main_character_name_is_removed_too(self):
        t = services.create_ticket(fresh(self.bystander), self.dept, priority("normal"), "Help", "Body")
        services.claim(fresh(self.leaver), t)
        colleague = make_user("Colleague C", groups=[self.g])
        t2 = services.create_ticket(fresh(self.bystander), self.dept, priority("normal"), "Help 2", "Body")
        services.assign(fresh(colleague), t2, fresh(self.leaver))
        # the person switches main character afterwards
        from allianceauth.eveonline.models import EveCharacter

        EveCharacter.objects.filter(pk=self.leaver.profile.main_character_id).update(character_name="New Main")
        self.erase()
        for m in TicketMessage.objects.filter(ticket__in=[t, t2], kind="event"):
            self.assertNotIn("Leaving Pilot", str(m.event_data), m.event_type)
        assigned = TicketMessage.objects.get(ticket=t2, event_type="assigned")
        self.assertEqual(assigned.event_data["assignee"], "[deleted user]")
        self.assertIsNone(assigned.event_data["assignee_id"])

    def test_colleague_named_in_events_by_the_person_is_kept(self):
        colleague = make_user("Colleague C", groups=[self.g])
        t = services.create_ticket(fresh(self.bystander), self.dept, priority("normal"), "Help", "Body")
        services.assign(fresh(self.leaver), t, fresh(colleague))
        self.erase()
        assigned = TicketMessage.objects.get(ticket=t, event_type="assigned")
        self.assertEqual(assigned.event_data["assignee"], "Colleague C")
        self.assertEqual(assigned.event_data["assignee_id"], colleague.pk)
        self.assertIsNone(assigned.author_id)
        self.assertTrue(assigned.event_data["author_erased"])

    def test_dry_run_warns_about_active_account(self):
        out = io.StringIO()
        call_command("aa_ticket_erase_user", self.leaver.username, stdout=out)
        self.assertIn("still active", out.getvalue())


class TestOrphanedRestrictionStaysClosedOnSave(TestCase):
    def setUp(self):
        self.allowed = make_group("Allowed")
        self.dept = make_department("Diplomacy")
        self.other = make_user("Pilot B")

    def data(self, **extra):
        data = {"name": "Diplomacy", "description": "", "order": 0, "is_active": "on", "accepts_submissions": "on",
                "submit_groups": [], "submit_states": [], "groups": [], "mention_role_ids": ""}
        data.update(extra)
        return data

    def orphan(self):
        f = DepartmentForm(data=self.data(submit_groups=[self.allowed.pk]), instance=self.dept)
        self.assertTrue(f.is_valid(), f.errors)
        f.save()
        self.allowed.delete()

    def test_renaming_keeps_it_closed(self):
        self.orphan()
        f = DepartmentForm(data=self.data(name="Diplomacy Corps"), instance=fresh(self.dept))
        self.assertIn("open_submissions", f.fields)
        self.assertTrue(f.is_valid(), f.errors)
        f.save()
        self.assertTrue(fresh(self.dept).restrict_submissions)
        self.assertNotIn(self.dept, access.submittable_departments(fresh(self.other)))

    def test_ticking_the_box_opens_it(self):
        self.orphan()
        f = DepartmentForm(data=self.data(open_submissions="on"), instance=fresh(self.dept))
        self.assertTrue(f.is_valid(), f.errors)
        f.save()
        self.assertFalse(fresh(self.dept).restrict_submissions)
        self.assertIn(self.dept, access.submittable_departments(fresh(self.other)))

    def test_box_only_shown_when_orphaned(self):
        self.assertNotIn("open_submissions", DepartmentForm(instance=self.dept).fields)


class TestPrefsDoubleSave(TestCase):
    def test_second_post_does_not_fail(self):
        user = make_user("Pilot A")
        self.client.force_login(user)
        with patch("aa_ticket.views.prefs.dm.is_available", return_value=True):
            for _ in range(2):
                r = self.client.post(reverse("aa_ticket:prefs"), {"discord_dm_enabled": ""})
                self.assertEqual(r.status_code, 302)
        self.assertFalse(UserPreference.objects.get(user=user).discord_dm_enabled)


class TestEraseRefusesActiveAccount(TestCase):
    def test_active_account_is_refused(self):
        from django.core.management.base import CommandError

        user = make_user("Still Here")
        dept = make_department("Diplomacy")
        services.create_ticket(user, dept, priority("normal"), "Help", "Body")
        with self.assertRaises(CommandError):
            call_command("aa_ticket_erase_user", user.username, "--yes", stdout=io.StringIO())
        self.assertTrue(Ticket.objects.filter(requester=user).exists())

    def test_deactivated_staff_member_gets_the_right_hint(self):
        g = make_group("Diplomats")
        make_department("Diplomacy", groups=[g])
        user = make_user("Gone Staff", groups=[g])
        User.objects.filter(pk=user.pk).update(is_active=False)
        out = io.StringIO()
        call_command("aa_ticket_erase_user", user.username, stdout=out)
        self.assertNotIn("still active", out.getvalue())
        self.assertIn("staff group", out.getvalue())

    def test_erased_assignee_shows_translated_label(self):
        from aa_ticket.templatetags.aa_ticket import event_text

        g = make_group("Diplomats")
        dept = make_department("Diplomacy", groups=[g])
        staff = make_user("Staff S", groups=[g])
        t = services.create_ticket(make_user("Pilot P"), dept, priority("normal"), "Help", "Body")
        services.claim(staff, t)
        User.objects.filter(pk=staff.pk).update(is_active=False)
        call_command("aa_ticket_erase_user", staff.username, "--yes", stdout=io.StringIO())
        claimed = TicketMessage.objects.get(ticket=t, event_type="claimed")
        with translation.override("zh-hans"):
            self.assertIn("已删除的用户", str(event_text(claimed, True)))


class TestRetentionSkipsBrokenFiles(TestCase):
    def test_one_undeletable_image_does_not_stop_the_rest(self):
        from aa_ticket import tasks

        dept = make_department("Diplomacy")
        user = make_user("Pilot A")
        for _ in range(2):
            t = services.create_ticket(fresh(user), dept, priority("normal"), "Help", "Body", images=[png()])
            services.close(fresh(user), t, ClosedReason.REQUESTER)
        Ticket.objects.update(closed_at=timezone.now() - timedelta(days=40))
        s = TicketSettings.get_solo()
        s.attachment_retention_days = 30
        s.save()
        from aa_ticket import attachments

        original = attachments.delete_attachment
        calls = []

        def flaky(attachment):
            calls.append(attachment.pk)
            if len(calls) == 1:
                raise OSError("read-only")
            return original(attachment)

        with patch("aa_ticket.attachments.delete_attachment", side_effect=flaky):
            tasks.cleanup_attachments()
        self.assertEqual(len(calls), 2)
        self.assertEqual(Attachment.objects.count(), 1)


class TestErasePreviewIsComplete(TestCase):
    def test_preview_counts_closed_and_escalations_and_names_kept_reasons(self):
        g = make_group("Diplomats")
        dept = make_department("Diplomacy", groups=[g])
        leaver = make_user("Leaving Pilot", groups=[g])
        other = make_user("Other Pilot")
        t = services.create_ticket(other, dept, priority("normal"), "Help", "Body")
        services.claim(fresh(leaver), t)
        services.close(fresh(leaver), fresh(t), ClosedReason.STAFF)
        out = io.StringIO()
        call_command("aa_ticket_erase_user", leaver.username, stdout=out)
        text = out.getvalue()
        self.assertIn("1 other ticket(s) they closed", text)
        self.assertIn("escalation request(s)", text)
        self.assertIn("reasons they typed", text)
