from django.db import migrations


def activate_uploaded_full_letterheads(apps, schema_editor):
    for model_name in ("COALetterhead", "TestLetterhead"):
        Letterhead = apps.get_model("reports", model_name)
        Letterhead.objects.filter(layout_mode="default").exclude(full_image="").update(layout_mode="full")


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0016_test_letterhead"),
    ]

    operations = [
        migrations.RunPython(activate_uploaded_full_letterheads, migrations.RunPython.noop),
    ]
