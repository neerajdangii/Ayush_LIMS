from django.db import migrations, models


def convert_dashboard_visit_mode_to_login(apps, schema_editor):
    WelcomeAnnouncement = apps.get_model("accounts", "WelcomeAnnouncement")
    WelcomeAnnouncement.objects.filter(display_mode="every_login").update(display_mode="login")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_welcomeannouncement_daily_display")]

    operations = [
        migrations.RunPython(convert_dashboard_visit_mode_to_login, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="welcomeannouncement",
            name="display_mode",
            field=models.CharField(
                choices=[
                    ("once", "Only once per user"),
                    ("daily", "Once per day for each user"),
                    ("login", "Every login (do not show again on page refresh)"),
                ],
                default="login",
                max_length=20,
            ),
        ),
    ]
