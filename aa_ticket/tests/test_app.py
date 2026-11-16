from django.apps import apps
from django.test import SimpleTestCase

import aa_ticket


class TestApp(SimpleTestCase):
    def test_app_installed_and_version(self):
        self.assertTrue(apps.is_installed("aa_ticket"))
        self.assertEqual(aa_ticket.__version__, "0.3.0")
