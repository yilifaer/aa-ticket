from unittest.mock import patch

from django.test import TestCase

from aa_ticket.models import UserPreference

from .factories import make_user


class TestPrefs(TestCase):
    def setUp(self):
        self.user = make_user("Pilot A")
        self.client.force_login(self.user)

    def test_prefs_toggle_hidden_without_bot(self):
        r = self.client.get("/ticket/prefs/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'name="discord_dm_enabled"')

    @patch("aa_ticket.views.prefs.dm.is_available", return_value=True)
    def test_prefs_toggle_saves(self, _available):
        r = self.client.get("/ticket/prefs/")
        self.assertContains(r, 'name="discord_dm_enabled"')
        r = self.client.post("/ticket/prefs/", {})
        self.assertRedirects(r, "/ticket/prefs/")
        self.assertFalse(UserPreference.for_user(self.user).discord_dm_enabled)
        self.client.post("/ticket/prefs/", {"discord_dm_enabled": "on"})
        self.assertTrue(UserPreference.for_user(self.user).discord_dm_enabled)
