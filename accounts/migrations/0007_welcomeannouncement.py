from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_rename_accounts_us_created_0a2cab_idx_accounts_us_created_f371fd_idx_and_more")]

    operations = [
        migrations.CreateModel(
            name="WelcomeAnnouncement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("announcement_type", models.CharField(choices=[("welcome", "Welcome"), ("feature", "New feature"), ("maintenance", "Maintenance notice"), ("holiday", "Holiday greeting"), ("news", "Company news"), ("alert", "Emergency alert"), ("release", "Release notes / version update"), ("training", "Training announcement")], default="welcome", max_length=20)),
                ("title", models.CharField(max_length=180)), ("message", models.TextField(blank=True)), ("image", models.ImageField(blank=True, null=True, upload_to="announcements/")),
                ("button_text", models.CharField(blank=True, max_length=60)), ("button_action", models.CharField(choices=[("close", "Close popup"), ("url", "Open a URL"), ("internal", "Open an internal page")], default="close", max_length=20)), ("button_url", models.CharField(blank=True, max_length=500)),
                ("is_active", models.BooleanField(default=False)), ("display_mode", models.CharField(choices=[("once", "Only once per user"), ("login", "Once per login"), ("every_login", "Every login while active")], default="once", max_length=20)),
                ("start_date", models.DateField(blank=True, null=True)), ("end_date", models.DateField(blank=True, null=True)), ("allow_close", models.BooleanField(default=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_announcements", to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ["-is_active", "-updated_at"], "permissions": [("manage_welcome_announcement", "Can manage Welcome Announcement")]},
        ),
        migrations.CreateModel(name="AnnouncementSeen", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("session_key", models.CharField(blank=True, max_length=64)), ("seen_at", models.DateTimeField(auto_now_add=True)), ("announcement", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="seen_records", to="accounts.welcomeannouncement")), ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="announcement_views", to=settings.AUTH_USER_MODEL))]),
        migrations.AddIndex(model_name="announcementseen", index=models.Index(fields=["announcement", "user"], name="accounts_ann_announce_5fa283_idx")),
        migrations.AddIndex(model_name="announcementseen", index=models.Index(fields=["announcement", "session_key"], name="accounts_ann_announce_62ef0a_idx")),
    ]
