from django.db import transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from .handlers import OpenAIHandler
from .models import (
    AiProvider,
    AiChatSession,
    AiChatMessage,
    AiPromptTemplate,
    AiPromptTemplateFavorite,
    GPTModels,
)
from .serializers import (
    AiChatSessionListSerializer,
    AiChatMessageSerializer,
    AiPromptTemplateSerializer,
    AiProviderSerializer,
    AiModelSerializer,
)
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction, IntegrityError

from rest_framework import status, permissions
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename
import uuid
import os


def _get_session_for_user(session_ref: str, user):
    raw = (session_ref or "").strip()
    if not raw:
        return None
    qs = AiChatSession.objects.filter(user=user)
    if raw.isdigit():
        by_id = qs.filter(id=int(raw)).first()
        if by_id:
            return by_id
    return qs.filter(uid=raw).first()


class ChatGptAPIView(APIView):
    # AllowAny: authenticated users keep the full flow (wallet/sessions/billing);
    # anonymous visitors get a limited free-quota guest flow inside OpenAIHandler.
    authentication_classes = [JWTAuthentication]
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        response = OpenAIHandler(request)
        if isinstance(response, dict) and "error" not in response:
            return Response(response, status=200)
        # Allow the handler to request a specific HTTP status (e.g. 402 for
        # insufficient tokens). Default error status is 400.
        http_status = 400
        if isinstance(response, dict) and isinstance(response.get("http_status"), int):
            http_status = response.pop("http_status")
        return Response(response, status=http_status)


class ChatsHistory(APIView):
    
    def delete(self, request):
        sessions = AiChatSession.objects.filter(user=request.user)
        if sessions.exists():
            sessions.delete();
        return Response({}, status=200)


class ChatSessionListAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            AiChatSession.objects
            .filter(user=request.user)
            .order_by("-updated_at")
            .prefetch_related("messages")
        )
        data = AiChatSessionListSerializer(qs, many=True).data
        return Response(data)


class ChatSessionDetailAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, session_ref: str):
        session = _get_session_for_user(session_ref, request.user)
        if not session:
            return Response({"error": "Session not found"}, status=404)

        messages_qs = session.messages.order_by("created_at")
        messages = AiChatMessageSerializer(messages_qs, many=True).data
        payload = {
            "id": session.id,
            "uid": session.uid,
            "title": session.title,
            "provider_id": session.provider_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "is_active": session.is_active,
            "messages": messages,
        }
        return Response(payload, status=200)


class AiTemplatesApiView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.AllowAny]  # GET доступен всем

    def get_permissions(self):
        if self.request.method.lower() == "post":
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    def get(self, request):
        personal_data = []

        global_queryset = AiPromptTemplate.objects.filter(
            is_public=True, is_active=True
        ).select_related("provider", "created_by")
        global_data = AiPromptTemplateSerializer(global_queryset, many=True).data

        if request.user.is_authenticated:
            personal_queryset = AiPromptTemplate.objects.filter(
                is_public=False, is_active=True, created_by=request.user
            ).select_related("provider", "created_by")
            personal_data = AiPromptTemplateSerializer(personal_queryset, many=True).data

        return Response({"global": global_data, "personal": personal_data}, status=200)

    def post(self, request):
        data = request.data or {}
        name = (data.get("name") or "").strip()
        provider_id = data.get("provider")
        template = (data.get("template") or "").strip()
        purpose = (data.get("purpose") or "").strip()
        description = (data.get("description") or "").strip()
        is_active = True
        is_public = False

        # required fields
        missing = []
        if not name:
            missing.append("name")
        if not provider_id:
            missing.append("provider")
        if not template:
            missing.append("template")
        if not purpose:
            missing.append("purpose")

        if missing:
            return Response(
                {"detail": "Заполните обязательные поля", "missing": missing},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # provider check
        try:
            provider = AiProvider.objects.get(pk=provider_id)
        except AiProvider.DoesNotExist:
            return Response({"detail": "Провайдер не найден"},
                            status=status.HTTP_400_BAD_REQUEST)

        # name unique
        if AiPromptTemplate.objects.filter(name=name).exists():
            return Response({"detail": "Шаблон с таким названием уже существует"},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                obj = AiPromptTemplate.objects.create(
                    name=name,
                    provider=provider,
                    template=template,
                    purpose=purpose,
                    description=description,
                    created_by=request.user,
                    is_active=is_active,
                    is_public=is_public,
                )
        except IntegrityError:
            return Response({"detail": "Не удалось создать шаблон"},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response(AiPromptTemplateSerializer(obj).data,
                        status=status.HTTP_201_CREATED)
        
@method_decorator(csrf_exempt, name="dispatch")
class AiTemplatesFavoriteApiView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        template_id = request.data.get("templateId")
        favorite = bool(request.data.get("favorite", False))
        # TODO: persist favorite for user
        return Response({"templateId": template_id, "favorite": favorite})

    def get(self, request):
        return Response({"detail": "OK"})


class AiProvidersApiView(APIView):
    authentication_classes = []   # публичный эндпоинт
    permission_classes = []

    def get(self, request):
        qs = AiProvider.objects.all().order_by("id")
        data = AiProviderSerializer(qs, many=True).data
        return Response(data, status=status.HTTP_200_OK)


class AiModelsListAPIView(APIView):
    """Публичный список активных моделей для свитчера в чате (доступен гостям)."""
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        qs = GPTModels.objects.filter(is_active=True).order_by("sort_order", "id")
        data = AiModelSerializer(qs, many=True).data
        return Response(data, status=status.HTTP_200_OK)


class ChatAttachmentUploadAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        files = request.FILES.getlist("files")
        if not files:
            return Response({"detail": "No files provided"}, status=400)

        uploaded = []
        for f in files:
            # sanitize and build path: uploads/chat/{user}/{uuid}/{filename}
            subdir = f"uploads/chat/{request.user.id}/{uuid.uuid4().hex}"
            name = get_valid_filename(f.name or "file")
            path = os.path.join(subdir, name)
            saved_path = default_storage.save(path, f)
            url = default_storage.url(saved_path)
            ctype = getattr(f, "content_type", "application/octet-stream") or "application/octet-stream"
            typ = "image" if ctype.startswith("image/") else "file"
            uploaded.append({
                "type": typ,
                "url": url,
                "name": name,
                "size": getattr(f, "size", None),
                "content_type": ctype,
            })

        return Response({"attachments": uploaded}, status=200)
