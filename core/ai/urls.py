from django.urls import path
from .views_media import (
    TranscribeAPIView,
    GenerationJobCreateView,
    GenerationJobDetailView,
    GenerationJobCancelView,
    GenerationJobListView,
)
from .views import (
    ChatGptAPIView,
    AiTemplatesApiView,
    ChatSessionListAPIView,
    ChatSessionImportAPIView,
    AiTemplatesFavoriteApiView,
    ChatSessionDetailAPIView,
    ChatMessageFeedbackAPIView,
    AiProvidersApiView,
    ChatsHistory,
    ChatAttachmentUploadAPIView,
    AiModelsListAPIView,
    CartoonModelsListAPIView,
    VideoModelParamsAPIView,
    VideoShareCreateAPIView,
    VideoSharePublicAPIView,
)

urlpatterns = [
    # Голос → текст (бот) и долгие генерации из очереди.
    path("transcribe/", TranscribeAPIView.as_view(), name="ai-transcribe"),
    path("jobs/", GenerationJobCreateView.as_view(), name="ai-jobs"),
    path("jobs/list/", GenerationJobListView.as_view(), name="ai-jobs-list"),
    path("jobs/<str:uid>/", GenerationJobDetailView.as_view(), name="ai-job-detail"),
    path("jobs/<str:uid>/cancel/", GenerationJobCancelView.as_view(), name="ai-job-cancel"),
    path('chat/', ChatGptAPIView.as_view(), name='chat_api'),
    path('attachments/upload/', ChatAttachmentUploadAPIView.as_view(), name='chat_attachments_upload'),
    path('chat/history/', ChatsHistory.as_view(), name='chat_history'),
    path('chat/feedback/', ChatMessageFeedbackAPIView.as_view(), name='chat_feedback'),
    path('templates/', AiTemplatesApiView.as_view(), name='ai_template'),
    path('templates/favorites/', AiTemplatesFavoriteApiView.as_view(), name='ai_template_favorite'),
    path('sessions/', ChatSessionListAPIView.as_view(), name='chat_sessions'),
    # ВАЖНО: import/ выше <session_ref>, иначе "import" попадёт в detail-вью.
    path('sessions/import/', ChatSessionImportAPIView.as_view(), name='chat_sessions_import'),
    path('sessions/<str:session_ref>/', ChatSessionDetailAPIView.as_view(), name='chat_sessions_detail'),
    path("providers/", AiProvidersApiView.as_view(), name="ai-providers"),
    path("models/", AiModelsListAPIView.as_view(), name="ai-models"),
    path("cartoon/models/", CartoonModelsListAPIView.as_view(), name="ai-cartoon-models"),
    path("video-params/", VideoModelParamsAPIView.as_view(), name="ai-video-params"),
    # Публичные ссылки на ролики: создание (свои) и чтение (кто угодно по ссылке).
    path("video/share/", VideoShareCreateAPIView.as_view(), name="ai-video-share-create"),
    path("video/share/<slug:slug>/", VideoSharePublicAPIView.as_view(), name="ai-video-share"),
]
