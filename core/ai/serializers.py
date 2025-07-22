from rest_framework import serializers
from .models import AiPromptTemplate


class AiPromptTemplateSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    created_by_user = serializers.CharField(source='created_by.email', read_only=True)

    class Meta:
        model = AiPromptTemplate
        fields = [
            'id',
            'name',
            'template',
            'description',
            'provider',
            'provider_name',
            'created_by',
            'created_by_user',
            'created_at',
            'updated_at',
            'usage_count',
            'is_active',
            'is_public',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at', 'usage_count']
