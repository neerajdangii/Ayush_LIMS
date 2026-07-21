from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0010_tdsdocumenttemplate_display_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="tdsdocumenttemplate",
            name="source_preview_file",
            field=models.FileField(blank=True, null=True, upload_to="tds_template_previews/"),
        ),
    ]
