from django.db import migrations, models
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    BlogPost = apps.get_model('content', 'BlogPost')
    used = set()
    for post in BlogPost.objects.all().order_by('pk'):
        if post.slug:
            used.add(post.slug)
            continue
        base = slugify(getattr(post, 'title_en', '') or post.title_ru, allow_unicode=False)
        if not base:
            base = slugify(post.title_ru, allow_unicode=True) or 'post'
        slug = base
        i = 2
        while slug in used or BlogPost.objects.exclude(pk=post.pk).filter(slug=slug).exists():
            slug = f'{base}-{i}'
            i += 1
        post.slug = slug
        used.add(slug)
        post.save(update_fields=['slug'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='blogpost',
            options={
                'ordering': ['-created_at'],
                'verbose_name': 'Пост блога',
                'verbose_name_plural': 'Посты блога',
            },
        ),
        migrations.AddField(
            model_name='blogpost',
            name='slug',
            field=models.SlugField(
                blank=True,
                max_length=255,
                null=True,
                db_index=False,
                help_text='ЧПУ-адрес статьи (генерируется из заголовка, если пусто)',
            ),
        ),
        migrations.AddField(
            model_name='blogpost',
            name='excerpt',
            field=models.TextField(blank=True, default='', help_text='Краткое описание / анонс'),
        ),
        migrations.AddField(
            model_name='blogpost',
            name='cover',
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to='media/blog_covers/',
                help_text='Обложка статьи',
            ),
        ),
        migrations.AddField(
            model_name='blogpost',
            name='cover_url',
            field=models.URLField(
                blank=True,
                default='',
                help_text='Внешний URL обложки (альтернатива загрузке)',
            ),
        ),
        migrations.AddField(
            model_name='blogpost',
            name='meta_title',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='blogpost',
            name='meta_description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='blogpost',
            name='is_published',
            field=models.BooleanField(default=False, help_text='Опубликована ли статья'),
        ),
        migrations.AddField(
            model_name='blogpost',
            name='published_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='SiteSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('site_name', models.CharField(blank=True, default='', max_length=255)),
                ('logo', models.URLField(blank=True, default='', help_text='URL логотипа')),
                ('favicon', models.URLField(blank=True, default='', help_text='URL favicon')),
                ('contact_email', models.EmailField(blank=True, default='', max_length=254)),
                ('contact_phone', models.CharField(blank=True, default='', max_length=50)),
                ('social_links', models.JSONField(
                    blank=True,
                    default=dict,
                    help_text='Соцсети, напр. {"telegram": "https://t.me/...", "instagram": "..."}',
                )),
                ('footer_text', models.TextField(blank=True, default='')),
                ('support_text', models.TextField(blank=True, default='')),
                ('error_text', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Настройки сайта',
                'verbose_name_plural': 'Настройки сайта',
            },
        ),
        migrations.CreateModel(
            name='PageSeo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('path', models.CharField(
                    db_index=True,
                    help_text='Путь страницы, напр. "/" или "/model/chatgpt"',
                    max_length=255,
                    unique=True,
                )),
                ('title', models.CharField(blank=True, default='', max_length=255)),
                ('description', models.TextField(blank=True, default='')),
                ('keywords', models.CharField(blank=True, default='', max_length=500)),
                ('og_title', models.CharField(blank=True, default='', max_length=255)),
                ('og_description', models.TextField(blank=True, default='')),
                ('og_image', models.URLField(blank=True, default='')),
                ('canonical', models.URLField(blank=True, default='')),
                ('robots', models.CharField(
                    blank=True,
                    default='index,follow',
                    help_text='Значение мета-тега robots, напр. "index,follow"',
                    max_length=100,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['path'],
                'verbose_name': 'SEO страницы',
                'verbose_name_plural': 'SEO страниц',
            },
        ),
        # Backfill уникальных slug по существующим постам, затем фиксируем
        # финальное состояние поля (unique=True, null=False) — совпадает с моделью.
        migrations.RunPython(backfill_slugs, noop),
        migrations.AlterField(
            model_name='blogpost',
            name='slug',
            field=models.SlugField(
                blank=True,
                max_length=255,
                unique=True,
                help_text='ЧПУ-адрес статьи (генерируется из заголовка, если пусто)',
            ),
        ),
    ]
