from rest_framework import serializers
from .models import BlogPost, SiteSettings, PageSeo


class BlogPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogPost
        fields = [
            'id',
            'image',
            'title_ru', 'title_en', 'title_kg',
            'content_ru', 'content_en', 'content_kg',
            'author',
            'created_at',
            'updated_at',
        ]


class ArticleListSerializer(serializers.ModelSerializer):
    """Краткое представление статьи (список опубликованных)."""
    class Meta:
        model = BlogPost
        fields = [
            'id', 'slug',
            'title_ru', 'title_en', 'title_kg',
            'excerpt',
            'image', 'cover', 'cover_url',
            'meta_title', 'meta_description',
            'author',
            'is_published', 'published_at',
            'created_at', 'updated_at',
        ]


class ArticleDetailSerializer(serializers.ModelSerializer):
    """Полное представление статьи (детально)."""
    class Meta:
        model = BlogPost
        fields = [
            'id', 'slug',
            'title_ru', 'title_en', 'title_kg',
            'excerpt',
            'content_ru', 'content_en', 'content_kg',
            'image', 'cover', 'cover_url',
            'meta_title', 'meta_description',
            'author',
            'is_published', 'published_at',
            'created_at', 'updated_at',
        ]


class SiteSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteSettings
        fields = [
            'site_name', 'logo', 'favicon',
            'contact_email', 'contact_phone', 'social_links',
            'footer_text', 'support_text', 'error_text',
            'updated_at',
        ]


class PageSeoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PageSeo
        fields = [
            'path', 'title', 'description', 'keywords',
            'og_title', 'og_description', 'og_image',
            'canonical', 'robots',
            'updated_at',
        ]
