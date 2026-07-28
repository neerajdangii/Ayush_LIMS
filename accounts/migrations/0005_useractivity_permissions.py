from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_useractivity_user_agent")]

    operations = [
        migrations.AlterModelOptions(
            name="useractivity",
            options={
                "ordering": ["-created_at"],
                "permissions": [("view_user_activity", "Can view User Activity")],
            },
        ),
    ]
