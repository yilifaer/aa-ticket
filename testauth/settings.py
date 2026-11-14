"""Minimal Alliance Auth settings for running the aa-ticket test suite."""

import os
import tempfile

from allianceauth.project_template.project_name.settings.base import *  # noqa: F401,F403

SECRET_KEY = "aa-ticket-test-secret-key-not-for-production"
SITE_URL = "https://auth.example.com"
DEBUG = False
ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "aa_ticket_test.sqlite3",
        "TEST": {"NAME": ":memory:"},
    }
}

if os.environ.get("AA_TICKET_TEST_DB") == "mysql":
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "aa_ticket",
        "USER": "root",
        "PASSWORD": "test",
        "HOST": "127.0.0.1",
        "PORT": "3306",
        "OPTIONS": {"charset": "utf8mb4"},
        "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_unicode_ci"},
    }

INSTALLED_APPS += ["aa_ticket"]  # noqa: F405

ROOT_URLCONF = "testauth.urls"
MEDIA_ROOT = tempfile.mkdtemp(prefix="aa_ticket_media_")
MEDIA_URL = "/media/"
STATIC_ROOT = tempfile.mkdtemp(prefix="aa_ticket_static_")

CELERY_TASK_ALWAYS_EAGER = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

LOGGING = None
ESI_SSO_CLIENT_ID = "dummy"
ESI_SSO_CLIENT_SECRET = "dummy"
ESI_SSO_CALLBACK_URL = f"{SITE_URL}/sso/callback"
ESI_USER_CONTACT_EMAIL = "test@example.com"
