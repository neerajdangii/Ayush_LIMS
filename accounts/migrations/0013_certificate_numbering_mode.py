from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_rename_accounts_ann_announce_5fa283_idx_accounts_an_announc_069374_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsetting",
            name="certificate_numbering_mode",
            field=models.CharField(
                choices=[
                    ("continuous", "Continuous serial (0001... )"),
                    ("daily", "Daily serial by receipt date (001... )"),
                ],
                default="daily",
                help_text="Select how booking certificate numbers are generated for reports.",
                max_length=16,
            ),
        ),
    ]
