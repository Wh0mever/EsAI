from django.db import transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from .handlers import OpenAIHandler, OpenAIImageHandler
from .tasks import generate_image_task, generate_music_task
from celery.result import AsyncResult
from core.celery import app as celery_app
from .models import (
    AiProvider,
    AiChatSession,
    AiChatMessage,
    AiPromptTemplate,
    AiPromptTemplateFavorite,
    TopMediaModels,
    AiGeneratedImage,
    AiGeneratedMusic,
)
from .serializers import (
    AiChatSessionListSerializer,
    AiChatMessageSerializer,
    AiPromptTemplateSerializer,
    AiProviderSerializer,
    TopMediaModelSerializer,
    AiGeneratedImageSerializer,
    AiGeneratedMusicSerializer,
)
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction, IntegrityError
from django.utils.translation import gettext as _

from rest_framework import status, permissions, authentication
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename
from django.conf import settings
from django.http import HttpResponse
import uuid
import os
import imghdr
import mimetypes
import tempfile
import subprocess
import shutil
from urllib.parse import urlparse
import requests
from plans.models import UserSubscription
from plans.services import get_chat_access_state


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


def _request_locale(request) -> str:
    raw = (request.data or {}).get("lang")
    if isinstance(raw, str) and raw.strip():
        code = raw.strip().lower().split("-")[0]
    else:
        header = (request.META.get("HTTP_ACCEPT_LANGUAGE") or "").split(",")[0].strip().lower()
        code = (header or "ru").split("-")[0]
    if code in {"kg", "ky"}:
        return "kg"
    if code == "en":
        return "en"
    return "ru"


def _guess_image_mime(raw_name: str, data: bytes) -> str | None:
    guessed, _ = mimetypes.guess_type(raw_name or "")
    if guessed in {"image/jpeg", "image/jpg"}:
        return "image/jpeg"
    if guessed == "image/png":
        return "image/png"
    kind = imghdr.what(None, h=data)
    if kind in ("jpeg", "jpg"):
        return "image/jpeg"
    if kind == "png":
        return "image/png"
    return None


def _cover_bytes_from_url(raw_url: str, request) -> tuple[bytes | None, str | None, str | None]:
    src = (raw_url or "").strip()
    if not src:
        return None, None, "cover_url_required"

    # Prefer local storage read for media URLs to avoid network/auth issues
    media_url = (getattr(settings, "MEDIA_URL", "/media/") or "/media/").rstrip("/") + "/"
    if src.startswith(media_url):
        rel_path = src[len(media_url):].lstrip("/")
        if not rel_path:
            return None, None, "cover_media_path_invalid"
        try:
            with default_storage.open(rel_path, "rb") as f:
                data = f.read()
        except Exception:
            return None, None, "cover_open_failed"
        if not data:
            return None, None, "cover_empty_payload"
        mime = _guess_image_mime(rel_path, data)
        if not mime:
            return None, None, "cover_format_unsupported"
        return data, mime, None

    # support relative media URLs
    if src.startswith("/"):
        src = request.build_absolute_uri(src)

    try:
        resp = requests.get(src, timeout=(10, 45))
    except requests.RequestException:
        return None, None, "cover_download_failed"

    if resp.status_code >= 400:
        return None, None, "cover_download_failed"

    data = resp.content or b""
    if not data:
        return None, None, "cover_empty_payload"

    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "image/jpeg" in ctype or "image/jpg" in ctype:
        return data, "image/jpeg", None
    if "image/png" in ctype:
        return data, "image/png", None

    # fallback sniff by bytes
    kind = imghdr.what(None, h=data)
    if kind in ("jpeg", "jpg"):
        return data, "image/jpeg", None
    if kind == "png":
        return data, "image/png", None
    return None, None, "cover_format_unsupported"


def _embed_cover_into_audio(track: AiGeneratedMusic, cover_bytes: bytes, cover_mime: str) -> tuple[bool, str | None]:
    if not track.audio:
        return False, "music_audio_missing"
    if not getattr(track.audio, "path", None):
        return False, "music_audio_path_unavailable"

    audio_path = track.audio.path
    ext = (os.path.splitext(audio_path)[1] or "").lower()

    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3, APIC, ID3NoHeaderError
            from mutagen.mp3 import MP3

            try:
                tags = ID3(audio_path)
            except ID3NoHeaderError:
                tags = ID3()
            tags.delall("APIC")
            # Save as ID3v2.3 for better compatibility with desktop/mobile players.
            tags.add(APIC(encoding=1, mime=cover_mime, type=3, desc="Cover", data=cover_bytes))
            tags.save(audio_path, v2_version=3)
            # Ensure file is still readable as MP3 after writing tags
            MP3(audio_path)
            return True, None

        if ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4, MP4Cover

            audio = MP4(audio_path)
            fmt = MP4Cover.FORMAT_JPEG if cover_mime == "image/jpeg" else MP4Cover.FORMAT_PNG
            audio["covr"] = [MP4Cover(cover_bytes, imageformat=fmt)]
            audio.save()
            return True, None

        return False, "music_audio_format_unsupported"
    except Exception:
        return False, "cover_embed_failed"


def _embed_title_into_audio(track: AiGeneratedMusic, title: str) -> tuple[bool, str | None]:
    if not track.audio:
        return False, "music_audio_missing"
    if not getattr(track.audio, "path", None):
        return False, "music_audio_path_unavailable"

    audio_path = track.audio.path
    ext = (os.path.splitext(audio_path)[1] or "").lower()
    safe_title = (title or "").strip()
    if not safe_title:
        return False, "music_title_required"

    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3, TIT2, ID3NoHeaderError
            from mutagen.mp3 import MP3

            try:
                tags = ID3(audio_path)
            except ID3NoHeaderError:
                tags = ID3()
            tags.delall("TIT2")
            # Save as ID3v2.3 for compatibility.
            tags.add(TIT2(encoding=1, text=safe_title))
            tags.save(audio_path, v2_version=3)
            MP3(audio_path)
            return True, None

        if ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4

            audio = MP4(audio_path)
            audio["\xa9nam"] = [safe_title]
            audio.save()
            return True, None

        return False, "music_audio_format_unsupported"
    except Exception:
        return False, "music_title_embed_failed"


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
        access = get_chat_access_state(request.user, _request_locale(request), kind="image")
        if access.get("blocked"):
            return Response(
                {"error": access.get("error"), "error_code": access.get("error_code"), "grace_until": access.get("grace_until")},
                status=400,
            )

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
            "warning": access.get("warning"),
            "warning_code": access.get("warning_code"),
            "grace_until": access.get("grace_until"),
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


class TopMediaMusicSubmitAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        access = get_chat_access_state(request.user, _request_locale(request), kind="music")
        if access.get("blocked"):
            return Response(
                {"error": access.get("error"), "error_code": access.get("error_code"), "grace_until": access.get("grace_until")},
                status=400,
            )

        data = request.data or {}
        prompt = (data.get("message") or data.get("prompt") or "").strip()
        if not prompt:
            return Response({"error": "No prompt provided"}, status=400)

        sub = (
            UserSubscription.objects
            .filter(user=request.user, status="active")
            .select_related("plan", "plan__topmedia_engine")
            .order_by("-start_date")
            .first()
        )
        plan_model = getattr(getattr(sub, "plan", None), "topmedia_engine", None)
        default_model = getattr(plan_model, "name", None) or "v4.5"

        payload = {
            "user_id": request.user.id,
            "prompt": prompt,
            "lyrics": (data.get("lyrics") or "").strip(),
            "title": ((data.get("title") or "").strip() or "Track"),
            "language": (data.get("language") or data.get("lang") or "").strip(),
            "genre": (data.get("genre") or "").strip(),
            "gender": (data.get("gender") or "").strip(),
            "is_auto": int(data.get("is_auto") or 1),
            "model_version": (data.get("model_version") or default_model).strip(),
            "instrumental": int(data.get("instrumental") if data.get("instrumental") is not None else 1),
            "continue_at": int(data.get("continue_at") or 0),
            "continue_song_id": (data.get("continue_song_id") or "").strip(),
            "provider_slug": (data.get("provider_slug") or AiProvider.NAME_TO_SLUG[AiProvider.NAME_TOPMEDIA]).strip(),
            "session_id": data.get("session_id") or data.get("chat_id"),
        }

        async_result = generate_music_task.delay(**payload)
        return Response({
            "job_id": async_result.id,
            "status": "queued",
            "warning": access.get("warning"),
            "warning_code": access.get("warning_code"),
            "grace_until": access.get("grace_until"),
        }, status=202)


class TopMediaMusicStatusAPIView(APIView):
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
            err = str(getattr(res, "result", "") or "Failed to generate music.")
            return Response({"status": state, "error": err[:500]}, status=200)

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


class TopMediaModelsApiView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        kind = (request.query_params.get("kind") or "").strip()
        qs = TopMediaModels.objects.filter(is_active=True)
        if kind:
            qs = qs.filter(kind=kind)
        qs = qs.order_by("kind", "name")
        data = TopMediaModelSerializer(qs, many=True).data
        return Response(data, status=status.HTTP_200_OK)


class UserImagesListAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import AiGeneratedImage
        qs = AiGeneratedImage.objects.filter(user=request.user).order_by("-created_at")
        data = AiGeneratedImageSerializer(qs, many=True).data
        return Response(data, status=200)


class UserMusicListAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = AiGeneratedMusic.objects.filter(user=request.user).order_by("-created_at")
        data = AiGeneratedMusicSerializer(qs, many=True).data
        return Response(data, status=200)


class UserMusicDownloadAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, music_id: int):
        track = AiGeneratedMusic.objects.filter(id=music_id, user=request.user).first()
        source_url_q = (request.query_params.get("source_url") or "").strip()
        title_q = (request.query_params.get("title") or "").strip()
        if not track and not source_url_q:
            return Response({"error": "music_not_found"}, status=404)

        safe_title = get_valid_filename(((getattr(track, "title", "") or title_q or "Track").strip() or "Track"))
        if track and track.audio:
            try:
                with track.audio.open("rb") as fp:
                    payload = fp.read()
            except Exception:
                return Response({"error": "music_audio_missing"}, status=400)
            resp = HttpResponse(payload, content_type="audio/mpeg")
            resp["Content-Disposition"] = f'attachment; filename="{safe_title}.mp3"'
            return resp

        effective_source_url = (getattr(track, "source_url", "") or source_url_q).strip()
        if effective_source_url:
            try:
                upstream = requests.get(effective_source_url, timeout=(10, 60))
            except requests.RequestException:
                return Response({"error": "music_download_failed"}, status=400)
            if upstream.status_code >= 400 or not upstream.content:
                return Response({"error": "music_download_failed"}, status=400)
            resp = HttpResponse(upstream.content, content_type=(upstream.headers.get("Content-Type") or "audio/mpeg"))
            resp["Content-Disposition"] = f'attachment; filename="{safe_title}.mp3"'
            return resp
        return Response({"error": "music_audio_missing"}, status=400)


class UserMusicDownloadMp4APIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, music_id: int):
        track = AiGeneratedMusic.objects.filter(id=music_id, user=request.user).first()
        source_url_q = (request.query_params.get("source_url") or "").strip()
        title_q = (request.query_params.get("title") or "").strip()
        safe_title = get_valid_filename(((getattr(track, "title", "") or title_q or "Track").strip() or "Track"))

        if shutil.which("ffmpeg") is None:
            return Response({"error": "music_mp4_unavailable"}, status=400)

        input_bytes = None
        if track and track.audio:
            try:
                with track.audio.open("rb") as fp:
                    input_bytes = fp.read()
            except Exception:
                input_bytes = None
        effective_source_url = (getattr(track, "source_url", "") or source_url_q).strip()
        if not input_bytes and effective_source_url:
            try:
                upstream = requests.get(effective_source_url, timeout=(10, 60))
                if upstream.status_code < 400 and upstream.content:
                    input_bytes = upstream.content
            except requests.RequestException:
                input_bytes = None
        if not input_bytes:
            return Response({"error": "music_audio_missing"}, status=400)

        with tempfile.TemporaryDirectory(prefix="music-mp4-") as td:
            input_path = os.path.join(td, "input.audio")
            output_path = os.path.join(td, "output.mp4")
            with open(input_path, "wb") as f:
                f.write(input_bytes)

            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-vn",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                output_path,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0 or not os.path.exists(output_path):
                return Response({"error": "music_mp4_convert_failed"}, status=400)

            try:
                with open(output_path, "rb") as f:
                    payload = f.read()
            except Exception:
                return Response({"error": "music_mp4_convert_failed"}, status=400)

        resp = HttpResponse(payload, content_type="video/mp4")
        resp["Content-Disposition"] = f'attachment; filename="{safe_title}.mp4"'
        return resp


class UserMusicCoverAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, music_id: int):
        track = AiGeneratedMusic.objects.filter(id=music_id, user=request.user).first()
        if not track:
            return Response({"error": "music_not_found"}, status=404)

        data = request.data or {}
        image_id = data.get("image_id")
        cover_url = (data.get("cover_url") or "").strip()

        if image_id:
            img = AiGeneratedImage.objects.filter(id=image_id, user=request.user).first()
            if not img:
                return Response({"error": "image_not_found"}, status=404)
            try:
                with img.image.open("rb") as f:
                    cover_bytes = f.read()
                cover_mime = _guess_image_mime(getattr(img.image, "name", "") or "", cover_bytes)
                if not cover_mime:
                    return Response({"error": "cover_format_unsupported"}, status=400)
                cover_url = img.image.url
                cover_err = None
            except Exception:
                cover_bytes, cover_mime, cover_err = None, None, "image_open_failed"
        else:
            cover_bytes, cover_mime, cover_err = None, None, None

        if not cover_url:
            return Response({"error": "cover_source_required"}, status=400)

        if cover_bytes is None:
            cover_bytes, cover_mime, cover_err = _cover_bytes_from_url(cover_url, request)
        if cover_err:
            return Response({"error": cover_err}, status=400)

        embedded, embed_err = _embed_cover_into_audio(track, cover_bytes, cover_mime or "image/jpeg")

        meta = track.meta if isinstance(track.meta, dict) else {}
        meta["cover_url"] = cover_url
        meta["cover_embedded"] = bool(embedded)
        if embed_err:
            meta["cover_embed_error"] = str(embed_err)
        else:
            meta.pop("cover_embed_error", None)
        track.meta = meta
        track.save(update_fields=["meta"])

        payload = AiGeneratedMusicSerializer(track).data
        payload["cover_embedded"] = bool(embedded)
        payload["cover_embed_error"] = embed_err
        return Response(payload, status=200)


class UserMusicTitleAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, music_id: int):
        track = AiGeneratedMusic.objects.filter(id=music_id, user=request.user).first()
        if not track:
            return Response({"error": "music_not_found"}, status=404)

        new_title = (request.data.get("title") or "").strip() or "Track"
        if len(new_title) > 255:
            return Response({"error": "music_title_too_long"}, status=400)

        track.title = new_title
        embedded, embed_err = _embed_title_into_audio(track, new_title)

        meta = track.meta if isinstance(track.meta, dict) else {}
        meta["title_embedded"] = bool(embedded)
        if embed_err:
            meta["title_embed_error"] = str(embed_err)
        else:
            meta.pop("title_embed_error", None)
        track.meta = meta
        track.save(update_fields=["title", "meta"])

        payload = AiGeneratedMusicSerializer(track).data
        payload["title_embedded"] = bool(embedded)
        payload["title_embed_error"] = embed_err
        return Response(payload, status=200)


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
