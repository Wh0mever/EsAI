from rest_framework import serializers
from .models import BlogPost

class BlogPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogPost
        fields = [
            'id',
            'image',
            'title_ru', 'title_en', 'title_ky',
            'content_ru', 'content_en', 'content_ky',
            'author',
            'created_at',
            'updated_at',
        ]
