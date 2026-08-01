from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_manual_certificate_no"),
    ]

    # 0015 already introduced this field.  Keep this migration as a no-op so
    # installations applying the migration sequence from scratch do not try to
    # add the same database column twice.
    operations = []
