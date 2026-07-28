from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_useractivity")]

    operations = [
        migrations.AddField(
            model_name="useractivity",
            name="user_agent",
            field=models.CharField(blank=True, max_length=1000),
        ),
    ]
