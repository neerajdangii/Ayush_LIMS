from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0019_letterhead_upload_permission"),
    ]

    operations = [
        migrations.AlterField(
            model_name="report",
            name="manager",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="managed_reports", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="report",
            name="incharge",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="incharge_reports", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="report",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reports", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="report",
            name="updated_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_reports", to=settings.AUTH_USER_MODEL),
        ),
    ]
