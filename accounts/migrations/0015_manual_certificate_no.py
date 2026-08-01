from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_manual_sample_reg_no"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsetting",
            name="allow_manual_certificate_no",
            field=models.BooleanField(
                default=False,
                help_text="Allow manual editing of computed certificate numbers on booking and report printouts.",
            ),
        ),
    ]
