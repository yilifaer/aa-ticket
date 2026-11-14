from contextlib import contextmanager

from django.conf import settings
from django.utils import translation


def language_of(user):
    profile = getattr(user, "profile", None)
    return getattr(profile, "language", "") or settings.LANGUAGE_CODE


@contextmanager
def user_language(user):
    with translation.override(language_of(user)):
        yield
