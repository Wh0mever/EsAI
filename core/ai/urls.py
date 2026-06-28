from django.urls import path
from .views import (
    ChatGptAPIView,
    AiTemplatesApiView,
    ChatSessionListAPIView,
    AiTemplatesFavoriteApiView,
    ChatSessionDetailAPIView,
    ChatMessageFeedbackAPIView,
    AiProvidersApiView,
    ChatsHistory,
    ChatAttachmentUploadAPIView,
    AiModelsListAPIView,
)

urlpatterns = [
    path('chat/', ChatGptAPIView.as_view(), name='chat_api'),
    path('attachments/upload/', ChatAttachmentUploadAPIView.as_view(), name='chat_attachments_upload'),
    path('chat/history/', ChatsHistory.as_view(), name='chat_history'),
    path('chat/feedback/', ChatMessageFeedbackAPIView.as_view(), name='chat_feedback'),
    path('templates/', AiTemplatesApiView.as_view(), name='ai_template'),
    path('templates/favorites/', AiTemplatesFavoriteApiView.as_view(), name='ai_template_favorite'),
    path('sessions/', ChatSessionListAPIView.as_view(), name='chat_sessions'),
    path('sessions/<str:session_ref>/', ChatSessionDetailAPIView.as_view(), name='chat_sessions_detail'),
    path("providers/", AiProvidersApiView.as_view(), name="ai-providers"),
    path("models/", AiModelsListAPIView.as_view(), name="ai-models"),
]
