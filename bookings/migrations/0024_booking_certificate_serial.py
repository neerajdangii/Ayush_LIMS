from django.db import migrations, models


def backfill_certificate_serials(apps, schema_editor):
    Booking = apps.get_model("bookings", "Booking")
    SystemSetting = apps.get_model("accounts", "SystemSetting")
    settings = SystemSetting.objects.order_by("pk").first()
    numbering_mode = getattr(settings, "certificate_numbering_mode", None)

    # Preserve the serial values that the previous calculated-number logic
    # produced, then keep them fixed for future report edits.
    for booking in Booking.objects.all().iterator():
        receipt_date = booking.sample_receipt_date or booking.booking_date
        if numbering_mode == "continuous":
            serial = Booking.objects.filter(
                booking_type=booking.booking_type,
                pk__lte=booking.pk,
            ).count()
        elif not receipt_date:
            serial = 1
        elif booking.sample_receipt_date:
            serial = (
                Booking.objects.filter(sample_receipt_date__date=receipt_date.date())
                .filter(
                    models.Q(sample_receipt_date__lt=receipt_date)
                    | models.Q(sample_receipt_date=receipt_date, pk__lte=booking.pk)
                )
                .count()
            )
        else:
            serial = (
                Booking.objects.filter(booking_date__date=receipt_date.date())
                .filter(
                    models.Q(booking_date__lt=receipt_date)
                    | models.Q(booking_date=receipt_date, pk__lte=booking.pk)
                )
                .count()
            )
        Booking.objects.filter(pk=booking.pk).update(certificate_serial=serial)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_manual_certificate_no"),
        ("bookings", "0023_alter_booking_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="certificate_serial",
            field=models.PositiveIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(backfill_certificate_serials, migrations.RunPython.noop),
    ]
