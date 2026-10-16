# Причина «Склейка видео» (merge_video). Только choices.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plans', '0024_reason_creator_credit'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tokentransaction',
            name='reason',
            field=models.CharField(choices=[('chat', 'Списание за чат'), ('purchase', 'Покупка пакета'), ('admin', 'Ручная корректировка'), ('bonus', 'Бонус'), ('welcome', 'Приветственный бонус'), ('daily_bonus', 'Ежедневный бонус'), ('refund', 'Возврат'), ('referral', 'Реферальное начисление'), ('transfer_in', 'Перевод получен'), ('transfer_out', 'Перевод отправлен'), ('promo', 'Промокод'), ('creator_credit', 'Creator Credits'), ('cartoon_keyframe', 'Студия: кадр'), ('cartoon_scene', 'Студия: сцена'), ('cartoon_character', 'Студия: свой герой'), ('cartoon_voice', 'Студия: озвучка'), ('cartoon_music', 'Студия: музыка'), ('cartoon_sfx', 'Студия: звуковой эффект'), ('stt', 'Распознавание голоса'), ('vstudio_video', 'Видеостудия: видео'), ('vstudio_image', 'Видеостудия: картинка'), ('merge_video', 'Склейка видео')], max_length=20, verbose_name='Причина'),
        ),
    ]
