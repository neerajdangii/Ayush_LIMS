from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0012_coaletterhead"),
    ]

    operations = [
        migrations.AddField(
            model_name="tdsdocumenttemplate",
            name="header_content",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="tdsdocumenttemplate",
            name="footer_content",
            field=models.TextField(blank=True),
        ),
    ]
