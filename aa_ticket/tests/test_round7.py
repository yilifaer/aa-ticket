"""0.4.3: decisions from the 0.4.2 test report (section 6)."""

import io
import os
import time
from unittest.mock import patch

import polib
from PIL import Image

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.utils import translation

from aa_ticket import access, services
from aa_ticket.auth_hooks import TicketDashboardHook
from aa_ticket.constants import ClosedReason, Event, Status
from aa_ticket.models import Attachment, Department, Priority, Ticket, TicketSettings
from aa_ticket.notifications import dispatch
from aa_ticket.tasks import cleanup_attachments, send_webhook

from .factories import make_department, make_group, make_user, priority

LOCALE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locale")
TEMPLATES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
URL = "https://discord.com/api/webhooks/1/abc"


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def png(name="a.png"):
    buf = io.BytesIO()
    Image.new("RGB", (6, 6), (9, 9, 9)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue())


def media_files():
    found = set()
    for dirpath, _d, files in os.walk(os.path.join(settings.MEDIA_ROOT, "aa_ticket")):
        found |= {os.path.join(dirpath, f) for f in files}
    return found


def po(lang):
    return {e.msgid: e for e in polib.pofile(os.path.join(LOCALE, lang, "LC_MESSAGES", "django.po"))}


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.g_lead = make_group("Lead")
        cls.g_dip = make_group("Dip")
        cls.g_fc = make_group("FC")
        cls.lead = make_department("Lead", groups=[cls.g_lead])
        cls.dip = make_department("Dip", groups=[cls.g_dip], parent=cls.lead, webhook_url=URL)
        cls.fc = make_department("FC", groups=[cls.g_fc])
        cls.requester = make_user("Pilot A")
        cls.officer = make_user("Diplomat B", groups=[cls.g_dip])
        cls.colleague = make_user("Diplomat C", groups=[cls.g_dip])
        cls.leader = make_user("Leader D", groups=[cls.g_lead])

    def setUp(self):
        cache.clear()
        self.t = services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "Help", "Body")

    def card(self, user, language="en"):
        request = RequestFactory().get("/dashboard/")
        request.user = fresh(user)
        with translation.override(language):
            return TicketDashboardHook().render(request)

    def run_events(self, func, *args, **kwargs):
        with self.captureOnCommitCallbacks(execute=True), patch("aa_ticket.notifications.send_webhook"), \
                patch("aa_ticket.notifications.notify"):
            return func(*args, **kwargs)


class TestLow1PreviousAssigneeCard(Fixture):
    def test_card_of_parent_department_assignee_refreshes_on_reassign(self):
        self.run_events(services.claim, fresh(self.leader), self.t)
        self.assertIn("Help", self.card(self.leader))
        self.run_events(services.assign, fresh(self.officer), fresh(self.t), self.colleague)
        self.assertNotIn("Help", self.card(self.leader))

    def test_card_refreshes_on_transfer(self):
        self.run_events(services.claim, fresh(self.leader), self.t)
        self.card(self.leader)
        self.run_events(services.transfer, fresh(self.officer), fresh(self.t), self.fc, keep_as_collaborator=False)
        self.assertNotIn("Help", self.card(self.leader))


class TestLow2CardPerLanguage(Fixture):
    def test_other_language_entry_keeps_its_own_expiry(self):
        with patch("aa_ticket.auth_hooks.cache.set", wraps=cache.set) as cache_set:
            self.card(self.requester, "en")
            self.card(self.requester, "de")
        keys = [c.args[0] for c in cache_set.call_args_list if "card" in str(c.args[0])]
        self.assertEqual(len(keys), 2)
        self.assertNotEqual(keys[0], keys[1])
        for call in cache_set.call_args_list:
            self.assertNotIsInstance(call.args[1], dict)

    def test_invalidation_covers_every_language(self):
        en, de = self.card(self.requester, "en"), self.card(self.requester, "de")
        self.assertIn("Help", en)
        services.close(fresh(self.requester), self.t, ClosedReason.REQUESTER)
        with patch("aa_ticket.notifications.send_webhook"), patch("aa_ticket.notifications.notify"):
            dispatch(Event.CLOSED, self.t.pk, self.requester.pk, {})
        self.assertEqual(self.card(self.requester, "en").strip(), "")
        self.assertEqual(self.card(self.requester, "de").strip(), "")


class TestLow3And11Escalation(Fixture):
    def post(self, target_id):
        self.client.force_login(self.requester)
        return self.client.post(
            f"/ticket/{self.t.pk}/action/escalate/", {"target_department_id": target_id}, follow=True
        )

    def test_second_request_at_top_says_already_asked(self):
        self.post(self.lead.pk)
        r = self.post(self.lead.pk)
        self.assertContains(r, "Lead has already been asked to step in.")
        self.assertEqual(self.t.escalations.count(), 1)

    def test_second_request_without_parameter_also_says_already_asked(self):
        self.post(self.lead.pk)
        self.client.force_login(self.requester)
        r = self.client.post(f"/ticket/{self.t.pk}/action/escalate/", follow=True)
        self.assertContains(r, "Lead has already been asked to step in.")

    def test_foreign_department_id_does_not_reveal_its_name(self):
        hidden = make_department("Secret Ops", is_active=False)
        for dept in (hidden, self.fc):
            r = self.post(dept.pk)
            self.assertNotContains(r, dept.name)
            self.assertContains(r, "no longer possible")
        self.assertEqual(self.t.escalations.count(), 0)


class TestLow5ReopenChecksAssignee(Fixture):
    def test_reopen_returns_to_unclaimed_when_assignee_left(self):
        services.claim(fresh(self.officer), self.t)
        services.close(fresh(self.requester), fresh(self.t), ClosedReason.REQUESTER)
        self.officer.groups.remove(self.g_dip)
        services.reopen(fresh(self.requester), fresh(self.t))
        t = fresh(self.t)
        self.assertEqual(t.status, Status.OPEN)
        self.assertIsNone(t.assignee)
        self.assertIsNotNone(t.open_since)

    def test_reopen_keeps_valid_assignee(self):
        services.claim(fresh(self.officer), self.t)
        services.close(fresh(self.requester), fresh(self.t), ClosedReason.REQUESTER)
        services.reopen(fresh(self.requester), fresh(self.t))
        t = fresh(self.t)
        self.assertEqual((t.status, t.assignee), (Status.IN_PROGRESS, self.officer))

    def test_reopen_drops_deactivated_assignee(self):
        services.claim(fresh(self.officer), self.t)
        services.close(fresh(self.requester), fresh(self.t), ClosedReason.REQUESTER)
        self.officer.is_active = False
        self.officer.save()
        services.reopen(fresh(self.requester), fresh(self.t))
        self.assertEqual(fresh(self.t).status, Status.OPEN)


class TestLow6OrphanFiles(Fixture):
    def test_rollback_after_images_were_written_removes_files(self):
        before = media_files()
        with patch("aa_ticket.services.dispatch"), patch.object(Ticket, "save", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                services.add_reply(fresh(self.requester), self.t, "x", images=[png(), png("b.png")])
        self.assertEqual(media_files(), before)

    def test_create_ticket_rollback_removes_files(self):
        before = media_files()
        with patch("aa_ticket.services._emit", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                services.create_ticket(fresh(self.requester), self.dip, priority("normal"), "T", "B", images=[png()])
        self.assertEqual(media_files(), before)

    def test_success_keeps_files(self):
        services.add_reply(fresh(self.requester), self.t, "x", images=[png()])
        self.assertTrue(os.path.exists(Attachment.objects.get().file.path))

    def test_daily_cleanup_removes_old_unreferenced_files_only(self):
        services.add_reply(fresh(self.requester), self.t, "x", images=[png()])
        kept = Attachment.objects.get().file.path
        folder = os.path.dirname(kept)
        old_orphan = os.path.join(folder, "orphan_old.png")
        new_orphan = os.path.join(folder, "orphan_new.png")
        for path in (old_orphan, new_orphan):
            with open(path, "wb") as fh:
                fh.write(b"x")
        two_days_ago = time.time() - 2 * 86400
        os.utime(old_orphan, (two_days_ago, two_days_ago))
        os.utime(kept, (two_days_ago, two_days_ago))
        self.assertIsNone(TicketSettings.get_solo().attachment_retention_days)
        cleanup_attachments()
        self.assertFalse(os.path.exists(old_orphan))
        self.assertTrue(os.path.exists(new_orphan))
        self.assertTrue(os.path.exists(kept))
        os.remove(new_orphan)


class TestLow7Plurals(Fixture):
    def setUp(self):
        super().setUp()
        self.admin = make_user("Admin E", perms=("basic_access", "manage"))
        self.client.force_login(self.admin)

    def test_singular_messages(self):
        r = self.client.post(f"/ticket/manage/departments/{self.dip.pk}/", {
            "name": "Dip", "description": "", "parent": self.lead.pk, "groups": [self.g_dip.pk], "accepts_submissions": "on",
            "order": "0", "new_webhook_url": "", "mention_role_ids": "",
        })
        self.assertContains(r, "still has 1 open ticket.")
        p = priority("normal")
        r = self.client.post(f"/ticket/manage/priorities/{p.pk}/", {
            "name": "Normal", "color": "primary", "order": "20", "mention_on_new": "on", "remind_after_minutes": "1440", "escalate_after_minutes": "",
        })
        self.assertContains(r, "1 open ticket still uses this priority.")

    def test_russian_has_plural_forms(self):
        ru = polib.pofile(os.path.join(LOCALE, "ru", "LC_MESSAGES", "django.po"))
        entries = [e for e in ru if e.msgid_plural and "open ticket" in e.msgid]
        self.assertEqual(len(entries), 2)
        for e in entries:
            self.assertGreaterEqual(len(set(e.msgstr_plural.values())), 2)


class TestLow8NoticeQuota(Fixture):
    def reply_dispatch(self):
        with patch("aa_ticket.notifications.send_webhook") as wh, patch("aa_ticket.notifications.notify"), \
                patch("aa_ticket.notifications.dm.is_available", return_value=False):
            dispatch(Event.REPLIED, self.t.pk, self.requester.pk, {"by_staff": False})
        return wh.delay.call_count

    def test_no_webhook_does_not_use_the_quota(self):
        Department.objects.filter(pk=self.dip.pk).update(webhook_url="")
        self.assertEqual(self.reply_dispatch(), 0)
        Department.objects.filter(pk=self.dip.pk).update(webhook_url=URL)
        self.assertEqual(self.reply_dispatch(), 1)
        self.assertEqual(self.reply_dispatch(), 0)

    def test_inactive_department_does_not_use_the_quota(self):
        Department.objects.filter(pk=self.dip.pk).update(is_active=False)
        self.assertEqual(self.reply_dispatch(), 0)
        Department.objects.filter(pk=self.dip.pk).update(is_active=True)
        self.assertEqual(self.reply_dispatch(), 1)

    def test_queue_failure_releases_the_quota(self):
        with patch("aa_ticket.notifications.send_webhook") as wh, patch("aa_ticket.notifications.notify"), \
                patch("aa_ticket.notifications.dm.is_available", return_value=False):
            wh.delay.side_effect = ConnectionError("broker")
            with self.assertLogs("extensions.aa_ticket", level="WARNING"):
                dispatch(Event.REPLIED, self.t.pk, self.requester.pk, {"by_staff": False})
        self.assertEqual(self.reply_dispatch(), 1)

    @patch("aa_ticket.discord.webhook.requests.post")
    def test_final_delivery_failure_releases_the_quota(self, post):
        self.assertEqual(self.reply_dispatch(), 1)
        response = post.return_value
        response.ok, response.status_code = False, 404
        with self.assertLogs("extensions.aa_ticket", level="WARNING"):
            send_webhook.apply(args=[self.dip.pk, self.t.pk, Event.REPLIED, False])
        self.assertEqual(self.reply_dispatch(), 1)


class TestContrastClasses(TestCase):
    def all_templates(self):
        for dirpath, _d, files in os.walk(TEMPLATES):
            for name in files:
                yield name, open(os.path.join(dirpath, name), encoding="utf-8").read()

    def test_no_white_on_yellow_or_grey_badges(self):
        for name, text in self.all_templates():
            self.assertNotIn("text-bg-warning", text, name)
            self.assertNotIn("text-bg-secondary", text, name)

    def test_css_makes_outline_buttons_readable(self):
        css = open(os.path.join(os.path.dirname(TEMPLATES), "static", "aa_ticket", "css", "ticket.css"), encoding="utf-8").read()
        self.assertIn(".aa-ticket .btn-outline-primary", css)
        self.assertIn(".aa-ticket .btn-outline-secondary", css)
        self.assertIn("aa-badge-muted", css)


class TestWording(TestCase):
    def test_spanish_assignee_is_responsable(self):
        es = po("es")
        self.assertEqual(es["Assignee"].msgstr, "Responsable")
        for entry in es.values():
            self.assertNotIn("asignado recib", entry.msgstr.lower())
            self.assertNotIn("el asignado", entry.msgstr.lower())

    def test_chinese_uses_one_term_for_escalation(self):
        zh = po("zh_Hans")
        for entry in zh.values():
            text = entry.msgstr or "".join(entry.msgstr_plural.values())
            self.assertNotIn("升级提醒", text, entry.msgid)
            self.assertNotIn("上报", text, entry.msgid)
            self.assertNotIn("不升级", text, entry.msgid)
        self.assertEqual(zh["Request escalation"].msgstr, "申请上级介入")
        self.assertIn("自动申请上级介入", zh["escalate after (minutes)"].msgstr)
        self.assertEqual(zh["escalation reminder sent"].msgstr, "已自动申请上级介入")
        self.assertEqual(zh["Escalated or shared with my departments"].msgstr, "申请上级介入或邀请协作的工单")


class TestReleaseReview(Fixture):
    """Findings of the pre-release review of 0.4.3."""

    def test_reopen_that_drops_the_assignee_tells_the_department(self):
        services.claim(fresh(self.officer), self.t)
        services.close(fresh(self.requester), fresh(self.t), ClosedReason.REQUESTER)
        self.officer.groups.remove(self.g_dip)
        with patch("aa_ticket.services.dispatch") as dispatched, self.captureOnCommitCallbacks(execute=True):
            services.reopen(fresh(self.requester), fresh(self.t))
        events = {c.args[0]: c.args[3] for c in dispatched.call_args_list}
        self.assertIn(Event.ASSIGNEE_LEFT, events)
        self.assertEqual(events[Event.ASSIGNEE_LEFT]["previous_assignee_id"], self.officer.pk)

    def test_reopen_with_valid_assignee_sends_no_assignee_left(self):
        services.claim(fresh(self.officer), self.t)
        services.close(fresh(self.requester), fresh(self.t), ClosedReason.REQUESTER)
        with patch("aa_ticket.services.dispatch") as dispatched, self.captureOnCommitCallbacks(execute=True):
            services.reopen(fresh(self.requester), fresh(self.t))
        self.assertNotIn(Event.ASSIGNEE_LEFT, [c.args[0] for c in dispatched.call_args_list])

    @patch("aa_ticket.discord.webhook.requests.post")
    def test_read_timeout_keeps_the_quota(self, post):
        import requests

        with patch("aa_ticket.notifications.send_webhook") as wh, patch("aa_ticket.notifications.notify"), \
                patch("aa_ticket.notifications.dm.is_available", return_value=False):
            dispatch(Event.REPLIED, self.t.pk, self.requester.pk, {"by_staff": False})
            post.side_effect = requests.ReadTimeout("slow")
            with self.assertLogs("extensions.aa_ticket", level="WARNING"):
                send_webhook.apply(args=[self.dip.pk, self.t.pk, Event.REPLIED, False])
            wh.reset_mock()
            dispatch(Event.REPLIED, self.t.pk, self.requester.pk, {"by_staff": False})
        self.assertEqual(wh.delay.call_count, 0)

    def test_racing_second_escalation_says_already_asked(self):
        from aa_ticket.exceptions import TicketActionError

        services.request_escalation(fresh(self.requester), self.t, expected_target=self.lead)
        with self.assertRaises(TicketActionError) as ctx:
            services.request_escalation(fresh(self.requester), fresh(self.t), expected_target=self.lead)
        self.assertIn("Lead has already been asked", ctx.exception.message)

    def test_low_priority_badge_uses_fixed_colours(self):
        low = services.create_ticket(fresh(self.requester), self.dip, priority("low"), "Low one", "Body")
        self.client.force_login(self.officer)
        html = self.client.get(f"/ticket/{low.pk}/").content.decode()
        self.assertIn("aa-prio-secondary", html)
        self.assertNotIn("text-bg-secondary", html)
        admin = make_user("Admin F", perms=("basic_access", "manage"))
        self.client.force_login(admin)
        html = self.client.get("/ticket/manage/priorities/").content.decode()
        self.assertNotIn("text-bg-", html.split('class="aa-ticket"')[1])

    def test_css_covers_focus_and_fixed_pairs(self):
        css = open(os.path.join(os.path.dirname(TEMPLATES), "static", "aa_ticket", "css", "ticket.css"), encoding="utf-8").read()
        for needle in (":focus-visible", ".aa-ticket .btn-warning", ".aa-prio-secondary", ".aa-prio-success", ".aa-prio-info", ".aa-prio-primary", ".aa-prio-danger", ".aa-prio-warning"):
            self.assertIn(needle, css, needle)

    def test_no_theme_dependent_badges_left(self):
        for dirpath, _d, files in os.walk(TEMPLATES):
            for name in files:
                if name == "dashboard_card.html":
                    continue
                text = open(os.path.join(dirpath, name), encoding="utf-8").read()
                self.assertNotRegex(text, r"badge[^\"]*text-bg-", name)


class TestFilesAfterCommit(TransactionTestCase):
    def test_files_survive_a_failure_after_commit(self):
        from .test_round6b import seed_priorities

        seed_priorities(Priority)
        dept = make_department("Dip")
        requester = make_user("Pilot A")
        ticket = services.create_ticket(requester, dept, priority("normal"), "Help", "Body")
        # the worker is killed (SystemExit) while the after-commit notifications run
        with patch("aa_ticket.services.dispatch", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                services.add_reply(requester, ticket, "x", images=[png()])
        attachment = Attachment.objects.get()
        self.assertTrue(os.path.exists(attachment.file.path))
        attachment.file.delete(save=False)
