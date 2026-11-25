# Rebrand: outgoing mail defaults to the real trading name.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0006_alter_emaillog_kind"),
    ]

    operations = [
        migrations.AlterField(
            model_name="emailsettings",
            name="from_name",
            field=models.CharField(
                blank=True, default="M&M Austin Limousine",
                help_text="Display name on outgoing mail.", max_length=120,
            ),
        ),
    ]
