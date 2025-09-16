from rest_framework import serializers
from .models import AiPromptTemplate, AiPromptTemplateFavorite, AiChatSession, AiChatMessage, AiProvider

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
            'purpose',
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
           
class AiPromptTemplateFavoriteSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(
        default=serializers.CurrentUserDefault()
    )
    favorites = serializers.JSONField(source='template', read_only=True)
    
    def validate(self, attrs):
        
        print("Validating AiPromptTemplateFavoriteSerializer with attrs:", attrs)
        
        return super().validate(attrs)

class AiChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AiChatMessage
        fields = ("id", "role", "content", "attachments", "meta", "created_at")

class AiChatSessionListSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()
    messages_count = serializers.IntegerField(source="messages.count", read_only=True)

    class Meta:
        model = AiChatSession
        fields = ("id", "title", "provider_id", "created_at", "updated_at", "is_active", "messages_count", "last_message", "chat_mode")

    def get_last_message(self, obj):
        m = obj.messages.order_by("-created_at").first()
        if not m:
            return None
        return {
            "role": m.role,
            "content": (m.content[:200] + "…") if m.content and len(m.content) > 200 else m.content,
            "created_at": m.created_at,
        }

class AiChatSessionMetaSerializer(serializers.ModelSerializer):
    class Meta:
        model = AiChatSession
        fields = ("id", "title", "provider_id", "created_at", "updated_at", "is_active")
        
class AiProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = AiProvider
        fields = ("id", "name")   # добавь поля, которые нужны фронту