from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0007_welcomeannouncement")]

    operations = [
        migrations.AlterField(model_name="welcomeannouncement", name="announcement_type", field=models.CharField(default="Welcome", max_length=60)),
        migrations.AlterField(model_name="welcomeannouncement", name="button_action", field=models.CharField(choices=[("close", "Close popup"), ("url", "Open a URL"), ("internal", "Open an internal page")], default="internal", max_length=20)),
        migrations.AlterField(model_name="welcomeannouncement", name="button_text", field=models.CharField(blank=True, default="Get Started", max_length=60)),
        migrations.AlterField(model_name="welcomeannouncement", name="button_url", field=models.CharField(blank=True, default="/", max_length=500)),
        migrations.AddField(model_name="welcomeannouncement", name="presentation", field=models.CharField(choices=[("popup", "Popup"), ("page", "Full page")], default="popup", max_length=12)),
    ]
