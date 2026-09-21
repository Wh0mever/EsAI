import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Журнал платных генераций: пользователь → модель → ID провайдера → статус."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ai', '0023_generationjob'),
    ]

    operations = [
        migrations.CreateModel(
            name='GenerationLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('video', 'Видео'), ('image', 'Изображение'), ('keyframe', 'Кадр студии'), ('voice', 'Озвучка'), ('music', 'Музыка'), ('sfx', 'Звуковой эффект')], db_index=True, max_length=12, verbose_name='Что')),
                ('source', models.CharField(choices=[('chat', 'Чат'), ('studio', 'Студия'), ('bot', 'Бот')], default='chat', max_length=8, verbose_name='Откуда')),
                ('provider', models.CharField(default='openrouter', max_length=24, verbose_name='Провайдер')),
                ('model', models.CharField(blank=True, default='', max_length=120, verbose_name='Модель')),
                ('status', models.CharField(choices=[('submitting', 'Отправляется'), ('submitted', 'Принято провайдером'), ('delivered', 'Выдано'), ('failed', 'Не удалось'), ('lost', 'Оплачено, но не выдано'), ('recovered', 'Довезено фоном')], db_index=True, default='submitting', max_length=12, verbose_name='Состояние')),
                ('provider_id', models.CharField(blank=True, db_index=True, default='', max_length=160, verbose_name='ID у провайдера')),
                ('polling_url', models.CharField(blank=True, default='', max_length=512, verbose_name='Адрес опроса')),
                ('prompt', models.TextField(blank=True, default='', verbose_name='Запрос')),
                ('params', models.JSONField(blank=True, default=dict, verbose_name='Параметры')),
                ('credits_charged', models.PositiveIntegerField(default=0, verbose_name='Списано кредитов')),
                ('credits_planned', models.PositiveIntegerField(default=0, verbose_name='Цена в кредитах')),
                ('provider_cost_usd', models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True, verbose_name='Стоимость у провайдера, $')),
                ('result_url', models.CharField(blank=True, default='', max_length=512, verbose_name='Результат')),
                ('error', models.TextField(blank=True, default='', verbose_name='Ошибка')),
                ('stages', models.JSONField(blank=True, default=list, verbose_name='Ход')),
                ('scene_id', models.PositiveIntegerField(blank=True, null=True, verbose_name='Сцена студии')),
                ('ip', models.GenericIPAddressField(blank=True, null=True, verbose_name='IP')),
                ('needs_review', models.BooleanField(db_index=True, default=False, verbose_name='Нужен разбор')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='ai.aichatmessage', verbose_name='Сообщение с результатом')),
                ('session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='ai.aichatsession', verbose_name='Чат')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='generation_logs', to=settings.AUTH_USER_MODEL, verbose_name='Пользователь')),
            ],
            options={
                'verbose_name': 'Генерация',
                'verbose_name_plural': 'Журнал генераций',
                'ordering': ('-id',),
                'indexes': [models.Index(fields=['status', 'kind', 'updated_at'], name='genlog_status_kind_upd')],
            },
        ),
    ]
