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


class TestNoCollisions(TestCase):
    """Other apps (allianceauth, aa-srp, ...) must not override our translations."""

    def test_every_entry_has_app_context(self):
        for lang in LANGUAGES:
            po = polib.pofile(os.path.join(LOCALE_DIR, lang, "LC_MESSAGES", "django.po"))
            self.assertEqual([e.msgid for e in po if e.msgctxt != "aa_ticket"], [], lang)

    def test_runtime_lookup_returns_our_translation(self):
        from django.utils import translation

        for lang in LANGUAGES:
            po = polib.pofile(os.path.join(LOCALE_DIR, lang, "LC_MESSAGES", "django.po"))
            with translation.override(lang.lower().replace("_", "-")):
                for e in po:
                    if e.msgid_plural:
                        continue
                    self.assertEqual(translation.pgettext("aa_ticket", e.msgid), e.msgstr, f"{lang}: {e.msgid}")

    def test_no_untagged_translate_calls(self):
        import re

        root = os.path.dirname(os.path.dirname(__file__))
        for dirpath, _dirs, files in os.walk(root):
            if "tests" in dirpath or "migrations" in dirpath:
                continue
            for name in files:
                path = os.path.join(dirpath, name)
                if name.endswith(".html"):
                    text = open(path, encoding="utf-8").read()
                    for tag in re.findall(r"\{% (?:block)?translate [^%]*%\}", text):
                        self.assertIn("context 'aa_ticket'", tag, f"{path}: {tag}")
                elif name.endswith(".py"):
                    text = open(path, encoding="utf-8").read()
                    self.assertIsNone(re.search(r"(?<![\w.])_\(|(?<!p)gettext(_lazy)?\(", text), path)
