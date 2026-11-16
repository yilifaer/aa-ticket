"""0.4.2: items 13-19 (wording, docs, tests against real dependencies, packaging)."""

import importlib.util
import os
import threading
import unittest
from unittest.mock import patch

import polib

from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from aa_ticket import services
from aa_ticket.constants import Status
from aa_ticket.exceptions import TicketActionError

from .factories import make_department, make_group, make_user, priority

DEFAULTS = (("Low", "secondary", 10), ("Normal", "primary", 20), ("Urgent", "danger", 30))


def seed_priorities(model):
    """TransactionTestCase flushes the tables, so the migration's default rows may be gone."""
    for name, color, order in DEFAULTS:
        model.objects.get_or_create(name=name, defaults={"color": color, "order": order})


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
LOCALE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locale")
HAS_BOT = importlib.util.find_spec("aadiscordbot") is not None and importlib.util.find_spec("discord") is not None


def po(lang):
    return {e.msgid: e for e in polib.pofile(os.path.join(LOCALE, lang, "LC_MESSAGES", "django.po"))}


class TestWording(TestCase):
    def test_chinese_invite_uses_glossary_term(self):
        self.assertEqual(po("zh_Hans")["Invite department"].msgstr, "邀请协作")

    def test_stats_closed_column_has_own_string(self):
        ru = po("ru")
        self.assertIn("Tickets closed", ru)
        self.assertNotEqual(ru["Tickets closed"].msgstr, ru["Closed"].msgstr)

    def test_readme_documents_priority_notification(self):
        text = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertIn("priority is changed", text)


@unittest.skipUnless(HAS_BOT, "aa-discordbot is not installed")
class TestRealDiscordBot(TestCase):
    def test_send_uses_the_real_signature_and_embed(self):
        import discord

        from aa_ticket.discord import dm

        with patch("aadiscordbot.tasks.send_message", autospec=True) as send_message:
            dm.send(
                42, "#1 Help", "The ticket was closed.", "https://auth.example.com/ticket/1/",
                [("Department", "Diplomacy"), ("Assignee", "Pilot")],
            )
        kwargs = send_message.call_args.kwargs
        self.assertEqual([(f.name, f.value) for f in kwargs["embed"].fields], [("Department", "Diplomacy"), ("Assignee", "Pilot")])
        self.assertEqual(kwargs["user_pk"], 42)
        self.assertIsInstance(kwargs["embed"], discord.Embed)
        self.assertEqual(kwargs["embed"].url, "https://auth.example.com/ticket/1/")


@unittest.skipUnless(connection.vendor == "mysql", "needs a real database server with row locks")
class TestConcurrentClaim(TransactionTestCase):
    def test_two_simultaneous_claims_one_winner(self):
        from aa_ticket.models import Priority

        seed_priorities(Priority)
        group = make_group("Dip")
        dept = make_department("Dip", groups=[group])
        requester = make_user("Pilot A")
        officers = [make_user(f"Diplomat {i}", groups=[group]) for i in range(2)]
        ticket = services.create_ticket(requester, dept, priority("normal"), "Help", "Body")
        barrier = threading.Barrier(2)
        results = []

        def claim(user):
            try:
                barrier.wait(timeout=10)
                services.claim(user, ticket)
                results.append("won")
            except TicketActionError:
                results.append("lost")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=claim, args=(u,)) for u in officers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(sorted(results), ["lost", "won"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.IN_PROGRESS)
        self.assertIn(ticket.assignee, officers)


class TestMigration0004(TransactionTestCase):
    def _migrate(self, name):
        executor = MigrationExecutor(connection)
        executor.migrate([("aa_ticket", name)])
        executor.loader.build_graph()
        return executor.loader.project_state([("aa_ticket", name)]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes("aa_ticket"))
        from aa_ticket.models import Priority

        seed_priorities(Priority)
        Priority.objects.filter(name="Urgent").update(is_urgent=True)

    def test_named_urgent_is_flagged(self):
        apps = self._migrate("0003_language_settings_and_view_all_name")
        seed_priorities(apps.get_model("aa_ticket", "Priority"))
        apps = self._migrate("0004_priority_is_urgent")
        Priority = apps.get_model("aa_ticket", "Priority")
        self.assertEqual(list(Priority.objects.filter(is_urgent=True).values_list("name", flat=True)), ["Urgent"])

    def test_renamed_priorities_flag_the_highest(self):
        apps = self._migrate("0003_language_settings_and_view_all_name")
        Priority = apps.get_model("aa_ticket", "Priority")
        seed_priorities(Priority)
        Priority.objects.filter(name="Urgent").update(name="Fire")
        apps = self._migrate("0004_priority_is_urgent")
        Priority = apps.get_model("aa_ticket", "Priority")
        self.assertEqual(list(Priority.objects.filter(is_urgent=True).values_list("name", flat=True)), ["Fire"])

    def test_single_priority_is_not_flagged(self):
        apps = self._migrate("0003_language_settings_and_view_all_name")
        Priority = apps.get_model("aa_ticket", "Priority")
        seed_priorities(Priority)
        Priority.objects.exclude(name="Normal").delete()
        apps = self._migrate("0004_priority_is_urgent")
        self.assertFalse(apps.get_model("aa_ticket", "Priority").objects.filter(is_urgent=True).exists())


class TestPackagingFiles(TestCase):
    def test_sdist_manifest_includes_docs(self):
        manifest = open(os.path.join(ROOT, "MANIFEST.in"), encoding="utf-8").read()
        for name in ("CHANGELOG.md", "README.zh-hans.md", "LICENSE"):
            self.assertIn(name, manifest)

    def test_ci_checks_packaging_and_migrations(self):
        ci = open(os.path.join(ROOT, ".github", "workflows", "tests.yml"), encoding="utf-8").read()
        self.assertIn("python -m build", ci)
        self.assertIn("makemigrations aa_ticket --check", ci)
        self.assertIn("allianceauth-discordbot", ci)

    def test_readme_task_names_exist(self):
        import re

        from aa_ticket import tasks

        text = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        names = re.findall(r'"task": "aa_ticket\.tasks\.(\w+)"', text)
        self.assertEqual(len(names), 3)
        for name in names:
            self.assertTrue(hasattr(tasks, name), name)
