from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_announcement_customization")]

    operations = [
        migrations.AlterField(
            model_name="welcomeannouncement",
            name="display_mode",
            field=models.CharField(
                choices=[
                    ("once", "Only once per user"),
                    ("daily", "Once per day for each user"),
                    ("login", "Once per login"),
                    ("every_login", "Every login while active"),
                ],
                default="every_login",
                max_length=20,
            ),
        ),
    ]
