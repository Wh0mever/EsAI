from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='pay_token',
            field=models.CharField(max_length=1024, blank=True, null=True, verbose_name='Токен платежа'),
        ),
    ]

