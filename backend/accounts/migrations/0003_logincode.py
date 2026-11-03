import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_user_stripe_customer_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoginCode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(db_index=True, help_text='Stored lowercase.', max_length=254)),
                ('code_hash', models.CharField(help_text='Salted hash of the six-digit code.', max_length=255)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('expires_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, help_text='Stamped on a successful verify (or when superseded). A stamped code is spent.', null=True)),
                ('attempts', models.PositiveSmallIntegerField(default=0, help_text='Failed/used verification attempts against this code.')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['email', '-created_at'], name='accounts_lo_email_f50002_idx')],
            },
        ),
    ]
