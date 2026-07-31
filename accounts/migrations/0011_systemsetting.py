from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_welcomeannouncement_login_display_default")]

    operations = [
        migrations.CreateModel(
            name="SystemSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("login_enabled", models.BooleanField(default=True)),
                ("session_timeout_minutes", models.PositiveIntegerField(default=0, help_text="Use 0 to disable automatic logout.")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "permissions": [
                    ("manage_system_settings", "Can manage system settings"),
                    ("edit_tinymce_source", "Can edit TinyMCE source code"),
                ],
            },
        ),
    ]
