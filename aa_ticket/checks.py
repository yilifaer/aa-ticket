import os

from django.conf import settings
from django.core.checks import Warning, register


@register()
def check_media_root(app_configs, **kwargs):
    if not getattr(settings, "MEDIA_ROOT", ""):
        return [
            Warning(
                "MEDIA_ROOT is not set; image uploads are disabled.",
                hint="Set MEDIA_ROOT in local.py to a writable folder, see the aa-ticket README.",
                id="aa_ticket.W001",
            )
        ]
    root = settings.MEDIA_ROOT
    if not os.path.isdir(root) or not os.access(root, os.W_OK):
        return [
            Warning(
                "MEDIA_ROOT does not exist or is not writable; image uploads are disabled.",
                hint=f"Create the folder and let the Alliance Auth user write to it: {root}",
                id="aa_ticket.W002",
            )
        ]
    return []


BEAT_TASKS = (
    "aa_ticket.tasks.check_unclaimed",
    "aa_ticket.tasks.check_auto_close",
    "aa_ticket.tasks.cleanup_attachments",
)


@register()
def check_beat_schedule(app_configs, **kwargs):
    """Without these periodic tasks reminders, escalation, auto-close and image clean-up never run."""
    schedule = getattr(settings, "CELERYBEAT_SCHEDULE", None) or {}
    configured = {entry.get("task") for entry in schedule.values() if isinstance(entry, dict)}
    missing = [task for task in BEAT_TASKS if task not in configured]
    if not missing:
        return []
    return [
        Warning(
            "Periodic tasks missing from CELERYBEAT_SCHEDULE: " + ", ".join(missing) + ".",
            hint="Add the three aa_ticket entries to local.py as shown in the aa-ticket README, then restart "
            "Celery Beat. Without them reminders, escalation, auto-close and image clean-up do not run.",
            id="aa_ticket.W003",
        )
    ]
