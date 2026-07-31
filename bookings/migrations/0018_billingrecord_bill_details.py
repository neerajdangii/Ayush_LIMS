from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("bookings", "0017_billingrecord")]

    operations = [
        migrations.AddField(model_name="billingrecord", name="bill_number", field=models.CharField(default="", max_length=100), preserve_default=False),
        migrations.AddField(model_name="billingrecord", name="letter_date", field=models.DateField(null=True)),
        migrations.AddField(model_name="billingrecord", name="billing_done_date", field=models.DateField(null=True)),
    ]
