from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0009_tdsdocumenttemplate"),
    ]

    operations = [
        migrations.AddField(
            model_name="tdsdocumenttemplate",
            name="display_mode",
            field=models.CharField(
                choices=[("editable", "Editable content"), ("source_file", "Display uploaded file")],
                default="editable",
                max_length=20,
            ),
        ),
    ]
