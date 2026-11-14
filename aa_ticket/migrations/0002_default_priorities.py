"""Create three default priority levels in this app's own table.

Admins can rename, change or deactivate them afterwards.
"""

from django.db import migrations

DEFAULTS = [
    # name, color, order, mention_on_new, remind_after_minutes, escalate_after_minutes
    ("Low", "secondary", 10, False, None, None),
    ("Normal", "primary", 20, True, 1440, None),
    ("Urgent", "danger", 30, True, 30, 120),
]


def create_defaults(apps, schema_editor):
    Priority = apps.get_model("aa_ticket", "Priority")
    if Priority.objects.exists():
        return
    for name, color, order, mention, remind, escalate in DEFAULTS:
        Priority.objects.create(
            name=name,
            color=color,
            order=order,
            mention_on_new=mention,
            remind_after_minutes=remind,
            escalate_after_minutes=escalate,
        )




class Migration(migrations.Migration):
    dependencies = [("aa_ticket", "0001_initial")]

    operations = [migrations.RunPython(create_defaults, migrations.RunPython.noop)]
