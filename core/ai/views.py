from django.db import transaction
from django.http import StreamingHttpResponse
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from .handlers import OpenAIHandler, stream_chat
from .models import (
    AiProvider,
    AiChatSession,
    AiChatMessage,
    AiMessageFeedback,
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
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename
import uuid
import os


# Максимальная длина извлечённого из документа текста (символы), чтобы не
# раздувать контекст модели и не упираться в лимит токенов OpenRouter.
DOCUMENT_TEXT_MAX_CHARS = 200_000

# Расширения документов, из которых мы умеем извлекать текст.
_DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt",
}


def _truncate_text(text: str, limit: int = DOCUMENT_TEXT_MAX_CHARS) -> str:
    """Обрезать текст до limit символов (best-effort, не падать на None)."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit]


def extract_text_from_file(file, filename: str) -> str:
    """Извлечь текст из загруженного файла по его расширению.

    Поддержка:
      - .pdf            → pypdf
      - .docx           → python-docx
      - .xlsx           → openpyxl
      - .pptx           → python-pptx
      - .txt            → decode (utf-8 с фолбэком)
      - .doc/.xls/.ppt  → старые бинарные форматы НЕ поддержаны (best-effort:
                          пробуем декодировать как текст, иначе пустая строка)

    Возвращает строку, обрезанную до DOCUMENT_TEXT_MAX_CHARS символов. Никогда не
    бросает исключение — при ошибке возвращает "" (загрузка файла не должна
    падать из-за проблем извлечения текста).
    """
    name = (filename or "").lower()
    ext = os.path.splitext(name)[1]

    def _read_bytes() -> bytes:
        try:
            file.seek(0)
        except Exception:
            pass
        try:
            return file.read() or b""
        except Exception:
            return b""

    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(_read_bytes()))
            parts = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
            return _truncate_text("\n".join(parts).strip())

        if ext == ".docx":
            from docx import Document
            import io
            doc = Document(io.BytesIO(_read_bytes()))
            parts = [p.text for p in doc.paragraphs if p.text]
            # Таблицы тоже несут текст.
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text for c in row.cells if c.text]
                    if cells:
                        parts.append("\t".join(cells))
            return _truncate_text("\n".join(parts).strip())

        if ext == ".xlsx":
            from openpyxl import load_workbook
            import io
            wb = load_workbook(io.BytesIO(_read_bytes()), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets:
                parts.append(f"# {ws.title}")
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) for c in row if c is not None]
                    if cells:
                        parts.append("\t".join(cells))
                    if sum(len(p) for p in parts) > DOCUMENT_TEXT_MAX_CHARS:
                        break
                if sum(len(p) for p in parts) > DOCUMENT_TEXT_MAX_CHARS:
                    break
            try:
                wb.close()
            except Exception:
                pass
            return _truncate_text("\n".join(parts).strip())

        if ext == ".pptx":
            from pptx import Presentation
            import io
            prs = Presentation(io.BytesIO(_read_bytes()))
            parts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if getattr(shape, "has_text_frame", False):
                        for para in shape.text_frame.paragraphs:
                            line = "".join(run.text for run in para.runs)
                            if line:
                                parts.append(line)
            return _truncate_text("\n".join(parts).strip())

        if ext == ".txt":
            raw = _read_bytes()
            for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
                try:
                    return _truncate_text(raw.decode(enc).strip())
                except Exception:
                    continue
            return _truncate_text(raw.decode("utf-8", errors="ignore").strip())

        # Старые бинарные форматы .doc/.xls/.ppt — best-effort попытка декода.
        if ext in (".doc", ".xls", ".ppt"):
            raw = _read_bytes()
            try:
                decoded = raw.decode("utf-8", errors="ignore")
                # Грубая эвристика: если осмысленного текста мало — не возвращаем мусор.
                printable = sum(1 for ch in decoded if ch.isprintable() or ch in "\n\t")
                if decoded and printable / max(1, len(decoded)) > 0.6:
                    return _truncate_text(decoded.strip())
            except Exception:
                pass
            return ""
    except Exception:
        # Извлечение текста не должно ломать загрузку файла.
        return ""

    return ""


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


def _normalize_feedback_value(raw):
    """Привести значение фидбека к 1 / -1. None — если значение не распознано.

    Поддерживаются формы фронта: 'up'/'down', '1'/'-1', 1/-1, True/False,
    'like'/'dislike'.
    """
    if isinstance(raw, bool):
        return AiMessageFeedback.VALUE_UP if raw else AiMessageFeedback.VALUE_DOWN
    if isinstance(raw, (int, float)):
        if raw > 0:
            return AiMessageFeedback.VALUE_UP
        if raw < 0:
            return AiMessageFeedback.VALUE_DOWN
        return None
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("up", "like", "1", "+1", "true", "yes"):
            return AiMessageFeedback.VALUE_UP
        if s in ("down", "dislike", "-1", "false", "no"):
            return AiMessageFeedback.VALUE_DOWN
    return None


def _is_stream_request(request) -> bool:
    """True, если клиент попросил потоковый ответ (body.stream truthy)."""
    val = (getattr(request, "data", {}) or {}).get("stream")
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return val != 0
    return str(val).strip().lower() in ("1", "true", "yes", "on")


class ChatGptAPIView(APIView):
    # AllowAny: authenticated users keep the full flow (wallet/sessions/billing);
    # anonymous visitors get a limited free-quota guest flow inside OpenAIHandler.
    authentication_classes = [JWTAuthentication]
    permission_classes = [AllowAny]
    # Защита от abuse: anon/user rate-limit (ТЗ 8). Ставки в settings (anon/user).
    throttle_classes = [AnonRateThrottle, UserRateThrottle]

    def post(self, request):
        # --- Streaming path (SSE) -------------------------------------------
        # Не держим transaction.atomic вокруг всего стрима (поток долгий):
        # сохранение/списание оборачиваются в короткую транзакцию внутри
        # генератора (см. handlers.stream_chat). Пред-проверки (нет токенов →
        # 402, гость сверх лимита → 401) возвращаются обычным JSON.
        if _is_stream_request(request):
            kind, payload = stream_chat(request)
            if kind == "stream":
                resp = StreamingHttpResponse(payload, content_type="text/event-stream")
                resp["Cache-Control"] = "no-cache"
                resp["X-Accel-Buffering"] = "no"
                return resp
            # kind == "error": обычный JSON с опциональным http_status.
            http_status = 400
            if isinstance(payload, dict) and isinstance(payload.get("http_status"), int):
                http_status = payload.pop("http_status")
            return Response(payload, status=http_status)

        # --- Non-streaming path (unchanged behaviour) -----------------------
        # Сохраняем прежнюю атомарность вокруг всего обработчика, которая раньше
        # давалась декоратором @transaction.atomic на post().
        with transaction.atomic():
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

    def patch(self, request, session_ref: str):
        session = _get_session_for_user(session_ref, request.user)
        if not session:
            return Response({"error": "Session not found"}, status=404)

        data = request.data or {}
        if "title" not in data:
            return Response({"detail": "Nothing to update"}, status=400)
        title = (data.get("title") or "").strip()
        if not title:
            return Response({"detail": "Title is required"}, status=400)

        session.title = title[:255]
        session.save(update_fields=["title", "updated_at"])
        return Response(
            {
                "id": session.id,
                "uid": session.uid,
                "title": session.title,
                "provider_id": session.provider_id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "is_active": session.is_active,
            },
            status=200,
        )

    def delete(self, request, session_ref: str):
        session = _get_session_for_user(session_ref, request.user)
        if not session:
            return Response({"error": "Session not found"}, status=404)
        session.delete()
        return Response(status=204)


class ChatMessageFeedbackAPIView(APIView):
    """POST /api/ai/chat/feedback/ — лайк/дизлайк ответа ассистента (upsert)."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data or {}
        message_id = data.get("message_id")
        value = _normalize_feedback_value(data.get("value"))

        if message_id is None:
            return Response({"detail": "message_id is required"}, status=400)
        if value is None:
            return Response({"detail": "Invalid value"}, status=400)

        message = AiChatMessage.objects.filter(pk=message_id).first()
        if not message:
            return Response({"error": "Message not found"}, status=404)

        # Оценивать можно только ответы в собственных сессиях пользователя.
        if message.session.user_id != request.user.id:
            return Response({"error": "Message not found"}, status=404)

        obj, _created = AiMessageFeedback.objects.update_or_create(
            message=message,
            user=request.user,
            defaults={"value": value},
        )
        return Response({"message_id": message.id, "value": obj.value}, status=200)


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
    # Загрузка/парсинг документов — ресурсоёмкая операция: лимитируем (ТЗ 8).
    throttle_classes = [UserRateThrottle]

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

            ext = os.path.splitext((f.name or "").lower())[1]
            if ctype.startswith("image/"):
                typ = "image"
            elif ext in _DOCUMENT_EXTENSIONS:
                typ = "document"
            else:
                typ = "file"

            item = {
                "type": typ,
                "url": url,
                "name": name,
                "size": getattr(f, "size", None),
                "content_type": ctype,
            }

            # Документы: извлекаем текст для RAG-подмешивания в контекст чата.
            if typ == "document":
                # Извлекаем из исходного UploadedFile (saved-файл уже на диске,
                # но in-memory объект ещё доступен для чтения).
                item["text"] = extract_text_from_file(f, f.name or name)

            uploaded.append(item)

        return Response({"attachments": uploaded}, status=200)
