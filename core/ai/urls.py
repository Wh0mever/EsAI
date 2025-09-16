from django.urls import path
from .views import ChatGptAPIView, AiTemplatesApiView, ChatSessionListAPIView, AiTemplatesFavoriteApiView, ChatSessionDetailAPIView, AiProvidersApiView, ChatsHistory, DalleImageAPIView

urlpatterns = [
    path('chat/', ChatGptAPIView.as_view(), name='chat_api'),
    path('image/', DalleImageAPIView.as_view(), name='image_api'),
    path('chat/history/', ChatsHistory.as_view(), name='chat_history'),
    path('templates/', AiTemplatesApiView.as_view(), name='ai_template'),
    path('templates/favorites/', AiTemplatesFavoriteApiView.as_view(), name='ai_template_favorite'),
    path('sessions/', ChatSessionListAPIView.as_view(), name='chat_sessions'),
    path('sessions/<int:session_id>/', ChatSessionDetailAPIView.as_view(), name='chat_sessions_detail'),
    path("providers/", AiProvidersApiView.as_view(), name="ai-providers"),
]
