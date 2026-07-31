# Generated manually because the local development environment does not include Django.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0016_booking_data_sheet_permission"),
    ]

    operations = [
        migrations.CreateModel(
            name="BillingRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("confirmed_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "booking",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="billing_record",
                        to="bookings.booking",
                    ),
                ),
                (
                    "confirmed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="confirmed_billings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Billing record",
                "verbose_name_plural": "Billing records",
                "ordering": ["-confirmed_at", "-pk"],
            },
        ),
    ]
