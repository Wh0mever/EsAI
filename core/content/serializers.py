from rest_framework import serializers
from .models import BlogPost

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
