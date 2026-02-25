from datetime import timedelta

from django.db import migrations


def backfill_subscription_end_date(apps, schema_editor):
    UserSubscription = apps.get_model('plans', 'UserSubscription')
    Plan = apps.get_model('plans', 'Plan')

    plan_days = {
        row['id']: int(row['duration_days'] or 30)
        for row in Plan.objects.values('id', 'duration_days')
    }

    qs = UserSubscription.objects.filter(end_date__isnull=True).values('id', 'plan_id', 'start_date')
    for row in qs.iterator(chunk_size=500):
        start = row['start_date']
        if not start:
            continue
        days = plan_days.get(row['plan_id'], 30)
        UserSubscription.objects.filter(pk=row['id'], end_date__isnull=True).update(
            end_date=start + timedelta(days=days)
        )


class Migration(migrations.Migration):

    dependencies = [
        ('plans', '0007_backfill_subscription_end_date'),
    ]

    operations = [
        migrations.RunPython(backfill_subscription_end_date, migrations.RunPython.noop),
    ]
