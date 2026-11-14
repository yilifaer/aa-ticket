import os

import polib

from django.test import TestCase

from aa_ticket import services

from .factories import make_department, make_group, make_user, priority

LOCALE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locale")
LANGUAGES = ("zh_Hans", "de", "ru", "es")


class TestTranslations(TestCase):
    def test_all_languages_fully_translated(self):
        for lang in LANGUAGES:
            path = os.path.join(LOCALE_DIR, lang, "LC_MESSAGES", "django.po")
            self.assertTrue(os.path.exists(path), path)
            po = polib.pofile(path)
            untranslated = [e.msgid for e in po.untranslated_entries()]
            fuzzy = [e.msgid for e in po.fuzzy_entries()]
            self.assertEqual(untranslated, [], f"{lang} untranslated")
            self.assertEqual(fuzzy, [], f"{lang} fuzzy")
            self.assertTrue(os.path.exists(path[:-3] + ".mo"), f"{lang} not compiled")

    def test_placeholders_kept(self):
        import re

        pattern = re.compile(r"%\(\w+\)[sd]|\{\{ ?\w+ ?\}\}")
        for lang in LANGUAGES:
            po = polib.pofile(os.path.join(LOCALE_DIR, lang, "LC_MESSAGES", "django.po"))
            for entry in po.translated_entries():
                if entry.msgid_plural:
                    continue
                self.assertEqual(
                    sorted(pattern.findall(entry.msgid)), sorted(pattern.findall(entry.msgstr)), f"{lang}: {entry.msgid}"
                )


class TestChinesePage(TestCase):
    def test_chinese_detail_page(self):
        g = make_group("Diplomats")
        dept = make_department("Diplomacy", groups=[g])
        requester = make_user("Pilot A")
        staff = make_user("Diplomat B", groups=[g])
        ticket = services.create_ticket(requester, dept, priority("normal"), "Help", "Body")
        self.client.force_login(staff)
        r = self.client.get(f"/ticket/{ticket.pk}/", HTTP_ACCEPT_LANGUAGE="zh-hans")
        self.assertContains(r, "接手")
        self.assertContains(r, "内部备注")
        self.assertContains(r, "关闭工单")
