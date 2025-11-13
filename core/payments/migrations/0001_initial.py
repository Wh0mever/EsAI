from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PaymentLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('provider', models.CharField(choices=[('freedompay', 'FreedomPay')], default='freedompay', max_length=32)),
                ('amount', models.IntegerField()),
                ('currency', models.CharField(default='KGS', max_length=10)),
                ('order_id', models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ('description', models.CharField(blank=True, max_length=255, null=True)),
                ('is_test', models.BooleanField(default=False)),
                ('success', models.BooleanField(default=False)),
                ('response', models.JSONField(default=dict)),
                ('error', models.TextField(blank=True, null=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payment_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-created_at', '-id')},
        ),
        migrations.AddIndex(
            model_name='paymentlog',
            index=models.Index(fields=['created_at'], name='payments_pa_created_7d2f84_idx'),
        ),
        migrations.AddIndex(
            model_name='paymentlog',
            index=models.Index(fields=['order_id'], name='payments_pa_order_i_6b0a95_idx'),
        ),
    ]

