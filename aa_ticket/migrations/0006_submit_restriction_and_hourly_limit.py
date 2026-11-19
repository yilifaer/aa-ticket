"""Submit restriction flag and hourly submission limit.

Departments that already limit submissions to some states or groups get the new flag, so they
stay closed to everyone else even if those states or groups are deleted later.
"""

from django.db import migrations, models


def mark_restricted(apps, schema_editor):
    Department = apps.get_model("aa_ticket", "Department")
    for department in Department.objects.all():
        if department.submit_states.exists() or department.submit_groups.exists():
            Department.objects.filter(pk=department.pk).update(restrict_submissions=True)


class Migration(migrations.Migration):

    dependencies = [
        ("aa_ticket", "0005_ticket_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="department",
            name="restrict_submissions",
            field=models.BooleanField(
                default=False,
                editable=False,
                help_text="Set when states or groups allowed to submit were chosen. Stays on if they are deleted later, so the department does not silently open up to everyone.",
            ),
        ),
        migrations.AddField(
            model_name="ticketsettings",
            name="max_new_tickets_per_hour",
            field=models.PositiveIntegerField(
                default=5,
                help_text="Limits how often one person can submit (and so ping a department). 0 means no limit.",
                verbose_name="new tickets per person per hour",
            ),
        ),
        migrations.RunPython(mark_restricted, migrations.RunPython.noop),
    ]
