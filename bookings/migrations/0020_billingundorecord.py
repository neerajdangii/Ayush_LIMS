from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("bookings", "0019_alter_billingrecord_billing_done_date_and_more")]

    operations = [
        migrations.CreateModel(
            name="BillingUndoRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bill_number", models.CharField(max_length=100)),
                ("letter_date", models.DateField(blank=True, null=True)),
                ("billing_done_date", models.DateField(blank=True, null=True)),
                ("confirmed_at", models.DateTimeField()),
                ("undone_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("booking", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="billing_undo_records", to="bookings.booking")),
                ("confirmed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="confirmed_billing_undo_records", to=settings.AUTH_USER_MODEL)),
                ("undone_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="undone_billing_records", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-undone_at", "-pk"]},
        ),
    ]
