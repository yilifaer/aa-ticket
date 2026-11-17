from contextlib import contextmanager

from django.conf import settings
from django.utils import translation


def language_of(user):
    profile = getattr(user, "profile", None)
    return getattr(profile, "language", "") or settings.LANGUAGE_CODE


def channel_language():
    from .models import TicketSettings

    return TicketSettings.get_solo().channel_language or "en"


def dm_language(user):
    from .models import TicketSettings

    if TicketSettings.get_solo().dm_language_mode == "channel":
        return channel_language()
    return language_of(user)


@contextmanager
def channel_language_active():
    with translation.override(channel_language()):
        yield


@contextmanager
def dm_language_active(user):
    with translation.override(dm_language(user)):
        yield


@contextmanager
def user_language(user):
    with translation.override(language_of(user)):
        yield
