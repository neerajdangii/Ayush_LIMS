from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0011_tdsdocumenttemplate_source_preview_file"),
    ]

    operations = [
        migrations.CreateModel(
            name="COALetterhead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="COA Letterhead", max_length=120)),
                (
                    "layout_mode",
                    models.CharField(
                        choices=[
                            ("default", "Use current default"),
                            ("full", "Full page image"),
                            ("parts", "Header / Middle / Footer"),
                        ],
                        default="default",
                        max_length=20,
                    ),
                ),
                ("full_image", models.FileField(blank=True, null=True, upload_to="coa_letterheads/")),
                ("header_image", models.FileField(blank=True, null=True, upload_to="coa_letterheads/")),
                ("middle_image", models.FileField(blank=True, null=True, upload_to="coa_letterheads/")),
                ("footer_image", models.FileField(blank=True, null=True, upload_to="coa_letterheads/")),
                ("is_active", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "COA Letterhead",
                "verbose_name_plural": "COA Letterhead",
            },
        ),
    ]
