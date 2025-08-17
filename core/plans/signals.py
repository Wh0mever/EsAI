from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import UserSubscription, GenerationUsage
from django.utils import timezone


@receiver(post_save, sender=UserSubscription)
def create_or_reset_usage(sender, instance: UserSubscription, created, **kwargs):
    """
    Initialize usage on subscription creation.
    If limits are 0 (unlimited), we leave usage at 0 and check unlimited on consume.
    """
    if created:
        plan = instance.plan
        usage, _ = GenerationUsage.objects.get_or_create(subscription=instance)
        usage.songs_left = plan.song_limit or 0
        usage.music_left = plan.music_limit or 0
        usage.texts_left = plan.text_limit or 0
        usage.images_left = plan.image_limit or 0

        # Sunday bonus provisioning (one-time per subscription unless you reset monthly)
        is_sunday = timezone.localdate().weekday() == 6  # Monday=0 ... Sunday=6
        if is_sunday and not usage.sunday_bonus_used:
            usage.songs_left += plan.sunday_bonus_songs
            usage.music_left += plan.sunday_bonus_music
            usage.texts_left += plan.sunday_bonus_texts
            usage.images_left += plan.sunday_bonus_images
            usage.sunday_bonus_used = True

        usage.save()
