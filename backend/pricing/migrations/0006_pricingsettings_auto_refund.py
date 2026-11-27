from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("pricing", "0005_delete_cityroute_cityrouteprice")]
    operations = [migrations.AddField(
        model_name="pricingsettings", name="auto_refund",
        field=models.BooleanField(default=False, help_text="Automatically refund paid amounts when customers cancel online."),
    )]
