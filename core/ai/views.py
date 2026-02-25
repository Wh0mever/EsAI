from django.db import transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from .handlers import OpenAIHandler, OpenAIImageHandler
from .tasks import generate_image_task
from celery.result import AsyncResult
from core.celery import app as celery_app
from .models import AiProvider, AiChatSession, AiChatMessage, AiPromptTemplate, AiPromptTemplateFavorite
from .serializers import (
    AiChatSessionListSerializer,
    AiChatMessageSerializer,
    AiPromptTemplateSerializer,
    AiProviderSerializer,
    AiGeneratedImageSerializer,
)
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction, IntegrityError
from django.utils.translation import gettext as _

from rest_framework import status, permissions, authentication
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
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        response = OpenAIHandler(request)
        return Response(
            response,
            status=200 if isinstance(
                response, dict) and "error" not in response else 400
        )


class DalleImageAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        response = OpenAIImageHandler(request)
        return Response(
            response,
            status=200 if isinstance(response, dict) and "error" not in response else 400,
        )


class DalleImageSubmitAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data or {}
        prompt = (data.get("message") or "").strip()
        if not prompt:
            return Response({"error": "No prompt provided"}, status=400)

        payload = {
            "user_id": request.user.id,
            "prompt": prompt,
            "size": (data.get("size") or "1024x1024").strip(),
            "model": (data.get("model") or "gpt-image-1").strip(),
            "provider_slug": (data.get("provider_slug") or AiProvider.NAME_TO_SLUG[AiProvider.NAME_DALLE]).strip(),
            "session_id": data.get("session_id") or data.get("chat_id"),
            "attachments": data.get("attachments") if isinstance(data.get("attachments"), list) else None,
        }
        async_result = generate_image_task.delay(**payload)
        return Response({
            "job_id": async_result.id,
            "status": "queued",
        }, status=202)


class DalleImageStatusAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        job_id = request.query_params.get("job") or request.query_params.get("id")
        if not job_id:
            return Response({"error": "job is required"}, status=400)
        res = AsyncResult(job_id, app=celery_app)
        state = res.state
        if state in ("PENDING", "RECEIVED", "STARTED", "RETRY"):
            return Response({"status": state}, status=200)
        if state == "FAILURE":
            # Do not expose raw tracebacks to clients
            return Response({"status": state, "error": "Failed to generate image."}, status=200)
        # SUCCESS
        try:
            result = res.get(propagate=False)
        except Exception:
            result = None
        ok = isinstance(result, dict) and ("error" not in result)
        return Response({
            "status": "SUCCESS" if ok else "FAILURE",
            "result": result if ok else None,
            "error": None if ok else (result.get("error") if isinstance(result, dict) else "Failed"),
        }, status=200)


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


class UserImagesListAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import AiGeneratedImage
        qs = AiGeneratedImage.objects.filter(user=request.user).order_by("-created_at")
        data = AiGeneratedImageSerializer(qs, many=True).data
        return Response(data, status=200)


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
