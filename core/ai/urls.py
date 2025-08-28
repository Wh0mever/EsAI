from django.urls import path
from .views import ChatGptAPIView, AiTemplatesApiView, ChatSessionListAPIView, AiTemplatesFavoriteApiView, ChatSessionDetailAPIView, AiProvidersApiView

urlpatterns = [
    path('chat/', ChatGptAPIView.as_view(), name='chat_api'),
    path('templates/', AiTemplatesApiView.as_view(), name='ai_template'),
    path('templates/favorites/', AiTemplatesFavoriteApiView.as_view(), name='ai_template_favorite'),
    path('sessions/', ChatSessionListAPIView.as_view(), name='chat_sessions'),
    path('sessions/<int:session_id>/', ChatSessionDetailAPIView.as_view(), name='chat_sessions_detail'),
    path("providers/", AiProvidersApiView.as_view(), name="ai-providers"),
]