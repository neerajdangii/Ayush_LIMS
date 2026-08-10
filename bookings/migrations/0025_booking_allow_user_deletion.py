from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0024_booking_certificate_serial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="booking",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="bookings", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="booking",
            name="updated_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_bookings", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="booking",
            name="approved_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_bookings", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="billingrecord",
            name="confirmed_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="confirmed_billings", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="billingundorecord",
            name="confirmed_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="confirmed_billing_undo_records", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="billingundorecord",
            name="undone_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="undone_billing_records", to=settings.AUTH_USER_MODEL),
        ),
    ]
