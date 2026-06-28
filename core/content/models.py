from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class BlogPost(models.Model):
    image = models.ImageField(upload_to='media/blog_images/', blank=True, null=True)

    title_ru = models.CharField(max_length=200)
    title_en = models.CharField(max_length=200)
    title_kg = models.CharField(max_length=200)

    content_ru = models.TextField()
    content_en = models.TextField()
    content_kg = models.TextField()

    author = models.CharField(max_length=100, default='EsAI')

    # --- SEO / CMS поля (ТЗ 7.7 / 10.5) ---
    slug = models.SlugField(
        max_length=255, unique=True, blank=True,
        help_text="ЧПУ-адрес статьи (генерируется из заголовка, если пусто)")
    excerpt = models.TextField(
        blank=True, default="", help_text="Краткое описание / анонс")
    cover = models.ImageField(
        upload_to='media/blog_covers/', blank=True, null=True,
        help_text="Обложка статьи")
    cover_url = models.URLField(
        blank=True, default="", help_text="Внешний URL обложки (альтернатива загрузке)")
    meta_title = models.CharField(max_length=255, blank=True, default="")
    meta_description = models.TextField(blank=True, default="")
    is_published = models.BooleanField(default=False, help_text="Опубликована ли статья")
    published_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title_ru

    def get_title(self, lang):
        return getattr(self, f"title_{lang}", self.title_ru)

    def get_content(self, lang):
        return getattr(self, f"content_{lang}", self.content_ru)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title_en or self.title_ru, allow_unicode=False)
            if not base:
                base = slugify(self.title_ru, allow_unicode=True) or "post"
            slug = base
            i = 2
            while BlogPost.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        if self.is_published and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Пост блога"
        verbose_name_plural = "Посты блога"


class SiteSettings(models.Model):
    """Глобальные настройки сайта (синглтон, ТЗ 7.9)."""
    site_name = models.CharField(max_length=255, blank=True, default="")
    logo = models.URLField(blank=True, default="", help_text="URL логотипа")
    favicon = models.URLField(blank=True, default="", help_text="URL favicon")
    contact_email = models.EmailField(blank=True, default="")
    contact_phone = models.CharField(max_length=50, blank=True, default="")
    social_links = models.JSONField(
        blank=True, default=dict,
        help_text='Соцсети, напр. {"telegram": "https://t.me/...", "instagram": "..."}')
    footer_text = models.TextField(blank=True, default="")
    support_text = models.TextField(blank=True, default="")
    error_text = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.site_name or "Настройки сайта"

    def save(self, *args, **kwargs):
        # Синглтон: всегда одна запись с pk=1.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    class Meta:
        verbose_name = "Настройки сайта"
        verbose_name_plural = "Настройки сайта"


class PageSeo(models.Model):
    """SEO-метаданные для конкретного пути фронтенда (ТЗ 7.6 / 10.2)."""
    path = models.CharField(
        max_length=255, unique=True, db_index=True,
        help_text='Путь страницы, напр. "/" или "/model/chatgpt"')
    title = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    keywords = models.CharField(max_length=500, blank=True, default="")
    og_title = models.CharField(max_length=255, blank=True, default="")
    og_description = models.TextField(blank=True, default="")
    og_image = models.URLField(blank=True, default="")
    canonical = models.URLField(blank=True, default="")
    robots = models.CharField(
        max_length=100, blank=True, default="index,follow",
        help_text='Значение мета-тега robots, напр. "index,follow"')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.path

    class Meta:
        ordering = ['path']
        verbose_name = "SEO страницы"
        verbose_name_plural = "SEO страниц"
