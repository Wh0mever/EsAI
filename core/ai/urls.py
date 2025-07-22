from django.urls import path
from .views import ChatGptAPIView, AiTemplatesApiView

urlpatterns = [
    path('chat/', ChatGptAPIView.as_view(), name='chat_api'),
    path('templates/', AiTemplatesApiView.as_view(), name='ai_template')
]