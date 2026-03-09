from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0006_remove_plan_extra_limits"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="plan",
            name="antiplag_enabled",
        ),
        migrations.RemoveField(
            model_name="plan",
            name="diffusion_images_enabled",
        ),
        migrations.RemoveField(
            model_name="plan",
            name="blog_master_enabled",
        ),
        migrations.RemoveField(
            model_name="plan",
            name="tts_enabled",
        ),
        migrations.RemoveField(
            model_name="plan",
            name="my_templates_enabled",
        ),
        migrations.RemoveField(
            model_name="plan",
            name="manager_enabled",
        ),
    ]

