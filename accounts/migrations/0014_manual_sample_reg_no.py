from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_certificate_numbering_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsetting",
            name="allow_manual_sample_reg_no",
            field=models.BooleanField(
                default=False,
                help_text="Allow manual editing of Sample Reg No. for bookings when editing.",
            ),
        ),
    ]
