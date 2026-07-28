from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_staff_group"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("activity", models.CharField(max_length=255)),
                ("method", models.CharField(max_length=10)),
                ("path", models.CharField(max_length=500)),
                ("status_code", models.PositiveSmallIntegerField()),
                ("browser", models.CharField(blank=True, max_length=100)),
                ("device", models.CharField(blank=True, max_length=50)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activities", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="useractivity",
            index=models.Index(fields=["-created_at"], name="accounts_us_created_0a2cab_idx"),
        ),
        migrations.AddIndex(
            model_name="useractivity",
            index=models.Index(fields=["user", "-created_at"], name="accounts_us_user_id_1c6fa0_idx"),
        ),
    ]
