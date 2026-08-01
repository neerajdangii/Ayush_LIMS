from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_manual_certificate_no"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsetting",
            name="allow_manual_certificate_no",
            field=models.BooleanField(
                default=False,
                help_text="Allow manual editing of the certificate number for printed COA reports.",
            ),
        ),
    ]
