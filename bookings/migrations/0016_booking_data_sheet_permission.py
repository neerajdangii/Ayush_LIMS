from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("bookings", "0015_customermaster_contact_details")]

    operations = [
        migrations.AlterModelOptions(
            name="booking",
            options={
                "ordering": ["-created_at"],
                "permissions": [("view_data_sheet", "Can view Data Sheet")],
            },
        ),
    ]
