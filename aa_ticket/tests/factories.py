"""Test helpers. All names and IDs here are fictional."""

import itertools

from django.contrib.auth.models import Group, Permission, User

from allianceauth.eveonline.models import EveCharacter

from aa_ticket.models import Department, Priority

_counter = itertools.count(90000001)

PRIORITY_NAMES = {"low": "Low", "normal": "Normal", "urgent": "Urgent"}


def add_perms(user, *codenames):
    for codename in codenames:
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="aa_ticket", codename=codename)
        )
    # drop permission cache
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        if hasattr(user, attr):
            delattr(user, attr)
    return user


def make_user(name, perms=("basic_access",), main=True, groups=()):
    user = User.objects.create_user(username=name.replace(" ", "_"), password="pw")
    if main:
        char_id = next(_counter)
        character = EveCharacter.objects.create(
            character_id=char_id,
            character_name=name,
            corporation_id=98000001,
            corporation_name="Test Corp",
            corporation_ticker="TEST",
        )
        user.profile.main_character = character
        user.profile.save()
    for group in groups:
        user.groups.add(group)
    add_perms(user, *perms)
    return User.objects.get(pk=user.pk)


def make_group(name):
    return Group.objects.create(name=name)


def make_department(name, groups=(), parent=None, **kwargs):
    department = Department.objects.create(name=name, parent=parent, **kwargs)
    for group in groups:
        department.groups.add(group)
    return department


def priority(code):
    return Priority.objects.get(name=PRIORITY_NAMES[code])
