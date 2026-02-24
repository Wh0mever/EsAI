from django.db import models

class BlogPost(models.Model):
    image = models.ImageField(upload_to='media/blog_images/', blank=True, null=True)
    
    title_ru = models.CharField(max_length=200)
    title_en = models.CharField(max_length=200)
    title_kg = models.CharField(max_length=200)

    content_ru = models.TextField()
    content_en = models.TextField()
    content_kg = models.TextField()

    author = models.CharField(max_length=100, default='Vokalo')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title_ru

    def get_title(self, lang):
        return getattr(self, f"title_{lang}", self.title_ru)

    def get_content(self, lang):
        return getattr(self, f"content_{lang}", self.content_ru)

    class Meta:
        verbose_name = "Пост блога"
        verbose_name_plural = "Посты блога"
