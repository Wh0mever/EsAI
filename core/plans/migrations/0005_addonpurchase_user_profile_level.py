from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def fill_addonpurchase_user(apps, schema_editor):
    AddonPurchase = apps.get_model('plans', 'AddonPurchase')
    UserSubscription = apps.get_model('plans', 'UserSubscription')

    sub_to_user = {
        row['id']: row['user_id']
        for row in UserSubscription.objects.values('id', 'user_id')
    }

    for ap in AddonPurchase.objects.all().only('id', 'subscription_id', 'user_id'):
        uid = sub_to_user.get(ap.subscription_id)
        if uid:
            AddonPurchase.objects.filter(pk=ap.pk).update(user_id=uid)


class Migration(migrations.Migration):

    dependencies = [
        ('plans', '0004_remove_addonpurchase_addon_type_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='addonpurchase',
            name='user',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='addon_purchases',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(fill_addonpurchase_user, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='addonpurchase',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='addon_purchases',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RemoveIndex(
            model_name='addonpurchase',
            name='plans_addon_subscri_923ef9_idx',
        ),
        migrations.RemoveField(
            model_name='addonpurchase',
            name='subscription',
        ),
        migrations.AddIndex(
            model_name='addonpurchase',
            index=models.Index(fields=['user', 'purchase_date'], name='plans_addon_user_id_5ad24d_idx'),
        ),
    ]
