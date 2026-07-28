from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0014_remove_customermaster_pdf_password"),
    ]

    operations = [
        migrations.AddField(
            model_name="customermaster",
            name="contact_person",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customermaster",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="customermaster",
            name="telephone",
            field=models.CharField(blank=True, max_length=50),
        ),
    ]
