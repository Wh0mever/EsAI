from rest_framework import serializers
from .models import (
    AiPromptTemplate,
    AiPromptTemplateFavorite,
    AiChatSession,
    AiChatMessage,
    AiProvider,
    GPTModels,
)

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
    messages_count = serializers.SerializerMethodField()

    class Meta:
        model = AiChatSession
        fields = ("id", "uid", "title", "provider_id", "created_at", "updated_at", "is_active", "messages_count", "last_message", "chat_mode")

    # Список чатов аннотирует счётчик и последнее сообщение подзапросами
    # (ChatSessionListAPIView) — без запроса на каждый чат. Без аннотаций
    # (другие вызовы) — прежний путь через связь messages.
    def get_messages_count(self, obj) -> int:
        value = getattr(obj, "messages_count_value", None)
        if value is not None:
            return int(value)
        return obj.messages.count()

    def get_last_message(self, obj):
        if hasattr(obj, "last_message_at"):
            if obj.last_message_at is None:
                return None
            content = obj.last_message_content
            role = obj.last_message_role
            created_at = obj.last_message_at
        else:
            m = obj.messages.order_by("-created_at").first()
            if not m:
                return None
            content, role, created_at = m.content, m.role, m.created_at
        return {
            "role": role,
            "content": (content[:200] + "…") if content and len(content) > 200 else content,
            "created_at": created_at,
        }

class AiChatSessionMetaSerializer(serializers.ModelSerializer):
    class Meta:
        model = AiChatSession
        fields = ("id", "uid", "title", "provider_id", "created_at", "updated_at", "is_active")
        
class AiProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = AiProvider
        fields = ("id", "name")   # добавь поля, которые нужны фронту


class AiModelSerializer(serializers.ModelSerializer):
    """Публичный список моделей для свитчера в чате (только активные).

    Дополнительно (ТЗ Этап 3): is_free / markup_coefficient / locked, чтобы
    фронт мог показать «замок» на премиум-моделях для гостя/free и подсветить
    бесплатные. `locked` зависит от текущего пользователя — он берётся из
    context["request"].user (передаётся вью).
    """
    is_free = serializers.SerializerMethodField()
    markup_coefficient = serializers.SerializerMethodField()
    locked = serializers.SerializerMethodField()
    estimated_usage = serializers.SerializerMethodField()

    class Meta:
        model = GPTModels
        fields = (
            "id", "name", "openrouter_id", "description", "short_label", "sort_order",
            "is_free", "markup_coefficient", "locked", "supports_vision",
            "category", "recommended", "estimated_usage",
        )

    def get_is_free(self, obj) -> bool:
        return bool(obj.is_free)

    def get_markup_coefficient(self, obj) -> float:
        try:
            return float(obj.markup_coefficient)
        except Exception:
            return 1.0

    def get_locked(self, obj) -> bool:
        # locked = модель недоступна текущему пользователю по его тиру (ТЗ 4.1).
        # Гость (или отсутствующий request) → тир guest → премиум заблокированы.
        # Обёрнуто в try/except как и get_estimated_usage: публичный список
        # моделей не должен падать целиком (many=True сериализует все объекты
        # одним проходом без изоляции) из-за ошибки тарификации для одной модели.
        from plans.tiers import can_use_model
        try:
            request = self.context.get("request")
            user = getattr(request, "user", None)
            return not can_use_model(user, obj)
        except Exception:
            # Фейлимся в сторону "заблокировано" — безопаснее, чем случайно
            # открыть премиум-модель при сбое проверки тира.
            return True

    def get_estimated_usage(self, obj) -> dict | None:
        # Каталог AI-моделей (Этап 4): "что получит пользователь за один пакет
        # 'Старт' на этой модели" — {count, unit_label, package_name} либо None,
        # если оценить нечего (нет активных пакетов/тарифа). Не должно ронять
        # список моделей — публичный эндпоинт обязан пережить любую ошибку оценки.
        from plans.credit_value import estimate_model_usage_cost
        try:
            return estimate_model_usage_cost(obj)
        except Exception:
            return None
