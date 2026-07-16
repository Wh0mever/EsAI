import logging
import random
import json
from django.conf import settings
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
from .serializers import (
    SignUpSerializer,
    SignInSerializer,
    ProfileSerializer,
    NotificationDeliverySerializer,
    UserQuestionSerializer,
    UserFeedbackSerializer,
    CurrencyPreferenceSerializer,
)
from core.format import format_errors
from mails.sender import send_template_email
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from plans.models import UserSubscription
from plans.serializers import UserSubscriptionSerializer
from .models import User, UserQuestions, Notification, NotificationDelivery, UserMemory, WebPushSubscription
from .services import activate_free_plan_for_user, process_free_plan_triggers
from . import memory as memory_helpers
from rest_framework import generics, permissions
from rest_framework.exceptions import NotFound
from django.db.utils import DataError as DBDataError
from django.db import connection

logger = logging.getLogger(__name__)


class TelegramConfigApiView(APIView):
    """Public config for the Telegram Login widget on the frontend."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "bot_username": getattr(settings, "TELEGRAM_BOT_USERNAME", ""),
            "bot_id": getattr(settings, "TELEGRAM_BOT_ID", ""),
        }, status=status.HTTP_200_OK)


class SigninApiView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        # Единый passwordless-вход по email (OTP). Пароль не требуется:
        # на любой корректный email отправляем код; аккаунт создаётся при
        # подтверждении кода (см. VerifyCodeApiView). Отдельной регистрации нет.
        email = (request.data.get("email") or "").strip().lower()
        if not email or "@" not in email or "." not in email.split("@")[-1]:
            return Response(
                {"status": "error", "message": "Введите корректный email"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # === Спец-случай: тестовый аккаунт платёжной системы ===
        # У тестировщиков платёжки нет почтового ящика для этого адреса,
        # поэтому письмо не отправляем (SMTP-ошибка сломала бы флоу), а сразу
        # возвращаем обычный success-ответ. Код входа у них фиксированный и
        # проверяется в VerifyCodeApiView. Отключается через settings:
        # TEST_LOGIN_EMAIL = "".
        _test_email = (getattr(settings, "TEST_LOGIN_EMAIL", "") or "").strip().lower()
        if _test_email and email == _test_email:
            return Response(
                {"status": "success", "message": "Код отправлен на email"},
                status=status.HTTP_200_OK,
            )

        # Анти-спам: per-email cooldown (~60с). Если код уже слался недавно —
        # не шлём повторно, отдаём мягкую ошибку 429.
        if cache.get(f"otp_cooldown:{email}"):
            return Response(
                {"status": "error", "message": "Код уже отправлен, подождите немного"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        code = str(random.randint(100000, 999999))
        cache.set(f"email_code:{email}", code, timeout=600)

        try:
            send_template_email(
                subject="Код входа в EsAI",
                template_name="verify_email.html",
                context={"code": code, "message": "Ваш код для входа в EsAI:"},
                recipient_list=[email],
            )
        except Exception as ex:
            print("send code error:", ex)
            return Response(
                {"status": "error", "message": "Не удалось отправить код, попробуйте позже"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Код отправлен: ставим cooldown ~60с и сбрасываем счётчик неудачных попыток,
        # чтобы новый код начинал проверку «с чистого листа».
        cache.set(f"otp_cooldown:{email}", "1", timeout=60)
        cache.delete(f"otp_attempts:{email}")

        return Response(
            {"status": "success", "message": "Код отправлен на email"},
            status=status.HTTP_200_OK,
        )


class VerifyCodeApiView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        # normalize code: strip spaces and ensure string compare
        raw_code = request.data.get("code")
        code = str(raw_code).strip().replace(" ", "") if raw_code is not None else ""

        if not email or not code:
            return Response({"error": "Email and code are required."}, status=400)

        email = email.lower()

        # Анти-брутфорс: лимит неудачных попыток на один код. После N=5 неудач
        # инвалидируем сам код, чтобы перебор не имел смысла.
        MAX_OTP_ATTEMPTS = 5
        attempts_key = f"otp_attempts:{email}"

        # === Спец-случай: тестовый аккаунт платёжной системы ===
        # У тестировщиков платёжки нет почтового ящика, код с почты они получить
        # не могут, поэтому для этого email действует фиксированный код входа.
        # Срабатывает ТОЛЬКО при точном совпадении ОБОИХ значений (email + код);
        # для всех остальных email поведение полностью прежнее. Отключается через
        # settings: TEST_LOGIN_EMAIL = "".
        _test_email = (getattr(settings, "TEST_LOGIN_EMAIL", "") or "").strip().lower()
        _test_code = str(getattr(settings, "TEST_LOGIN_CODE", "") or "")
        is_test_login = bool(_test_email) and bool(_test_code) and email == _test_email and code == _test_code

        if not is_test_login:
            cached_code = cache.get(f"email_code:{email}")
            if isinstance(cached_code, (bytes, bytearray)):
                cached_code = cached_code.decode()
            if not cached_code or cached_code != code:
                # Инкремент счётчика неудач (живёт столько же, сколько код — 10 минут).
                try:
                    attempts = cache.incr(attempts_key)
                except ValueError:
                    # Ключа ещё нет — создаём с TTL кода.
                    cache.set(attempts_key, 1, timeout=600)
                    attempts = 1
                if attempts >= MAX_OTP_ATTEMPTS:
                    # Слишком много неудач: убиваем код и счётчик.
                    cache.delete(f"email_code:{email}")
                    cache.delete(attempts_key)
                    return Response(
                        {"error": "Слишком много попыток, запросите новый код."},
                        status=429,
                    )
                return Response({"error": "Неверный или просроченный код."}, status=400)

        # Успех: удаляем код и счётчик попыток.
        cache.delete(f"email_code:{email}")
        cache.delete(attempts_key)

        # Авто-создание аккаунта при первом входе (отдельной регистрации нет).
        user = User.objects.filter(email=email).first()
        created = False
        if not user:
            created = True
            user = User(email=email)
            try:
                user.set_unusable_password()
            except Exception:
                pass
            for field, value in (("is_confirmed", True), ("is_active", True), ("tel", "")):
                if hasattr(user, field):
                    try:
                        setattr(user, field, value)
                    except Exception:
                        pass
            user.save()

        if not getattr(user, "is_confirmed", True):
            user.is_confirmed = True
            user.save(update_fields=["is_confirmed"])

        if created:
            try:
                activate_free_plan_for_user(user)
            except Exception:
                pass
            try:
                # Антифрод v1: approve → начислить сразу, delay → в очередь на 24ч.
                from .antifraud import maybe_grant_welcome_bonus
                maybe_grant_welcome_bonus(user, request)  # welcome-бонус новому пользователю
            except Exception:
                pass
            try:
                # Привязка реферера (код в cookie esai_ref). Кредиты НЕ начисляются
                # тут — реферер получает % при каждом пополнении приглашённого.
                from .services import maybe_link_referrer
                maybe_link_referrer(request, user)
            except Exception:
                pass
            try:
                # Промокод при регистрации (cookie esai_promo или поле promo) — тихо.
                from .services import maybe_activate_promo_on_signup
                maybe_activate_promo_on_signup(request, user)
            except Exception:
                pass

        refresh = RefreshToken.for_user(user)

        return Response({
            "status": "authenticated",
            "data": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                # is_new — для приветственного окна на фронте (показать один раз).
                "is_new": bool(created),
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "tel": getattr(user, "tel", ""),
                }
            }
        }, status=200)


class SignUpApiView(APIView):
    authentication_classes = []
    permission_classes = []

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    def post(self, request):
        ip = self.get_client_ip(request)
        serializer = SignUpSerializer(data={**request.data, 'ip': ip})
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                "status": "success",
            }, status=status.HTTP_201_CREATED)
        else:
            return Response({
                "status": "error",
                "errors": format_errors(serializer.errors),
            }, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetRequestView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"message": "Email is required."}, status=400)

        # Generic-ответ при отсутствии аккаунта: не раскрываем существование email
        # (защита от user enumeration). Один и тот же ответ для «есть»/«нет».
        generic_response = Response(
            {"status": "success",
             "message": "Если аккаунт существует, код отправлен."},
            status=200,
        )

        # Анти-спам/анти-брутфорс: per-email cooldown (~60с). Если код уже слался
        # недавно — не шлём повторно, отдаём мягкую ошибку 429.
        if cache.get(f"reset_cooldown:{email}"):
            return Response(
                {"status": "error", "message": "Код уже отправлен, подождите немного"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Аккаунта нет — отдаём тот же generic 200, ничего не отправляя.
            return generic_response

        code = str(random.randint(100000, 999999))
        cache.set(f"reset_code:{email}", code, timeout=600)  # 10 минут

        send_template_email(
            subject="Password Reset Code",
            template_name="verify_email.html",
            context={
                "code": code, "message": "To reset your password, please use the 6-digit code below:"},
            recipient_list=[email],
        )

        # Код отправлен: ставим cooldown ~60с и сбрасываем счётчик неудачных попыток,
        # чтобы новый код начинал проверку «с чистого листа».
        cache.set(f"reset_cooldown:{email}", "1", timeout=60)
        cache.delete(f"reset_attempts:{email}")

        return generic_response


class PasswordResetVerifyView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        raw_code = request.data.get("code")
        code = str(raw_code).strip().replace(" ", "") if raw_code is not None else ""

        if not email or not code:
            return Response({"message": "Email and code are required."}, status=400)

        # Анти-брутфорс: лимит неудачных попыток на один код. После N=5 неудач
        # инвалидируем сам код, чтобы перебор не имел смысла (по образцу OTP).
        MAX_RESET_ATTEMPTS = 5
        attempts_key = f"reset_attempts:{email}"

        cached_code = cache.get(f"reset_code:{email}")
        if isinstance(cached_code, (bytes, bytearray)):
            cached_code = cached_code.decode()
        if not cached_code or cached_code != code:
            # Инкремент счётчика неудач (живёт столько же, сколько код — 10 минут).
            try:
                attempts = cache.incr(attempts_key)
            except ValueError:
                # Ключа ещё нет — создаём с TTL кода.
                cache.set(attempts_key, 1, timeout=600)
                attempts = 1
            if attempts >= MAX_RESET_ATTEMPTS:
                # Слишком много неудач: убиваем код и счётчик.
                cache.delete(f"reset_code:{email}")
                cache.delete(attempts_key)
                return Response(
                    {"message": "Слишком много попыток, запросите новый код."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            return Response({"message": "Invalid or expired code."}, status=400)

        return Response({"status": "success", "message": "Code verified."}, status=200)


class PasswordResetCompleteView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        raw_code = request.data.get("code")
        code = str(raw_code).strip().replace(" ", "") if raw_code is not None else ""
        password = request.data.get("password")

        if not email or not code or not password:
            return Response({"message": "Email, code, and new password are required."}, status=400)

        # Анти-брутфорс: лимит неудачных попыток на один код. После N=5 неудач
        # инвалидируем сам код, чтобы перебор не имел смысла (по образцу OTP).
        MAX_RESET_ATTEMPTS = 5
        attempts_key = f"reset_attempts:{email}"

        cached_code = cache.get(f"reset_code:{email}")
        if isinstance(cached_code, (bytes, bytearray)):
            cached_code = cached_code.decode()
        if not cached_code or cached_code != code:
            try:
                attempts = cache.incr(attempts_key)
            except ValueError:
                cache.set(attempts_key, 1, timeout=600)
                attempts = 1
            if attempts >= MAX_RESET_ATTEMPTS:
                cache.delete(f"reset_code:{email}")
                cache.delete(attempts_key)
                return Response(
                    {"message": "Слишком много попыток, запросите новый код."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            return Response({"message": "Invalid or expired code."}, status=400)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"message": "User not found."}, status=404)

        # Проверка политики паролей (длина/частые/числовые и т.п.) до установки.
        try:
            validate_password(password, user)
        except DjangoValidationError as ex:
            return Response({"message": " ".join(ex.messages)}, status=400)

        user.password = make_password(password)
        user.save()
        cache.delete(f"reset_code:{email}")
        # Успех: сбрасываем счётчик неудачных попыток.
        cache.delete(attempts_key)

        return Response({"status": "success", "message": "Password changed successfully."}, status=200)


class UserProfileView(APIView):
    def get(self, request):
        user_obj = request.user
        user_data = ProfileSerializer(user_obj).data
        subscription = (
            UserSubscription.objects
            .select_related("plan", "usage", "user")
            .filter(user=user_obj)
            .order_by("-start_date")
            .first()
        )

        if not subscription and not getattr(user_obj, "free_plan_activated", False):
            activated, _ = activate_free_plan_for_user(user_obj)
            if activated:
                subscription = (
                    UserSubscription.objects
                    .select_related("plan", "usage", "user")
                    .filter(user=user_obj)
                    .order_by("-start_date")
                    .first()
                )

        subscription_data = UserSubscriptionSerializer(subscription).data if subscription else None
        if subscription and getattr(subscription, "plan", None) and subscription.plan.is_free:
            try:
                process_free_plan_triggers(subscription)
            except Exception:
                pass
        response_data = {
            "user": user_data,
            "subscription": subscription_data,
        }
        return Response(response_data, status=200)

    def put(self, request):

        changed = False
        tel = request.data.get('tel', None)
        first_name = request.data.get('first_name', None)
        _2fa = request.data.get('_2fa', None)

        if tel:
            request.user.tel = tel
            changed = True
        if first_name:
            request.user.first_name = first_name
            changed = True
        if _2fa == False or _2fa == True:
            request.user._2fa = _2fa
            changed = True

        if changed:
            request.user.save()

        if not getattr(request.user, "free_plan_activated", False):
            activate_free_plan_for_user(request.user)

        return Response({}, status=200)


class CurrencyPreferenceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CurrencyPreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.selected_currency = serializer.validated_data["currency"]
        request.user.save(update_fields=["selected_currency"])
        return Response({"currency": request.user.selected_currency}, status=200)


class QuestionAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # accept alias "message" for "question"
        data = request.data.copy()
        if "question" not in data and "message" in data:
            data["question"] = data["message"]

        serializer = UserQuestionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()

        # Уведомление админу на почту (форма /contact-us раньше только сохраняла
        # в БД и НИКУДА не сообщала — жалоба клиента «письмо не приходит»).
        # Получатель: SiteSettings.contact_email (редактируется в /admin-new →
        # Настройки → Контакты) с фолбэком на support@esai.kg, если поле ещё не
        # заполнено. Сбой отправки НЕ должен ронять сохранение вопроса.
        try:
            from content.models import SiteSettings

            site = SiteSettings.objects.first()
            to_email = (getattr(site, "contact_email", "") or "").strip() or settings.DEFAULT_FROM_EMAIL
            text = (
                f"Новое обращение с сайта EsAI (esai.kg/contact-us)\n\n"
                f"Имя: {obj.name or '-'}\n"
                f"Email: {obj.email}\n"
                f"Телефон: {obj.tel or '-'}\n\n"
                f"Сообщение:\n{obj.question}\n"
            )
            send_template_email(
                subject=f"Новое обращение с сайта — {obj.name or obj.email}",
                recipient_list=[to_email],
                raw_html=f"<pre style='font-family:inherit;white-space:pre-wrap'>{text}</pre>",
                raw_text=text,
            )
        except Exception:
            logger.exception("contact_us notification email failed for question id=%s", obj.id)

        return Response({"id": obj.id}, status=status.HTTP_201_CREATED)
    

class NotificationListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationDeliverySerializer

    def get_queryset(self):
        user = self.request.user
        qs = (
            NotificationDelivery.objects
            .filter(recipient=user, notification__created_at__gte=user.date_joined)
            .select_related("notification")
        )
        if self.request.query_params.get("unread") == "1":
            qs = qs.filter(is_read=False)
        return qs.order_by("-assigned_at")


class NotificationMarkReadView(generics.UpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationDeliverySerializer
    lookup_url_kwarg = "pk"

    def get_queryset(self):
        user = self.request.user
        return (
            NotificationDelivery.objects
            .filter(recipient=user, notification__created_at__gte=user.date_joined)
            .select_related("notification")
        )

    def get_object(self):
        qs = self.get_queryset()
        pk = self.kwargs.get(self.lookup_url_kwarg)
        # Accept either delivery id or notification id for convenience
        try:
            return qs.get(pk=pk)
        except NotificationDelivery.DoesNotExist:
            obj = qs.filter(notification_id=pk).order_by('-assigned_at').first()
            if not obj:
                raise NotFound("Notification not found for this user")
            return obj

    def _mark(self, request, *args, **kwargs):
        delivery = self.get_object()
        delivery.mark_read()
        serializer = self.get_serializer(delivery)
        return Response(serializer.data, status=200)

    def patch(self, request, *args, **kwargs):
        return self._mark(request, *args, **kwargs)


class FeedbackView(APIView):
    """POST to submit feedback by authenticated users; GET list for admins."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]

    def post(self, request):
        serializer = UserFeedbackSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            obj = serializer.save()
            return Response({"status": "success", "id": obj.id}, status=201)
        return Response({"status": "error", "errors": serializer.errors}, status=400)

    def get(self, request):
        # Admin-only list
        from .models import UserFeedback
        qs = UserFeedback.objects.all()
        return Response(UserFeedbackSerializer(qs, many=True).data, status=200)


# === Память пользователя (как у ChatGPT/Anthropic) ===

def _serialize_memory(obj: UserMemory) -> dict:
    """Компактная сериализация факта памяти для API."""
    return {
        "id": obj.id,
        "content": obj.content,
        "category": obj.category,
        "source": obj.source,
        "importance": obj.importance,
        "updated_at": obj.updated_at,
    }


class UserMemoryListView(APIView):
    """GET — список фактов пользователя + флаг memory_enabled."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = UserMemory.objects.filter(user=request.user)
        return Response({
            "memory_enabled": bool(getattr(request.user, "memory_enabled", True)),
            "items": [_serialize_memory(m) for m in qs],
        }, status=200)


class UserMemoryDeleteView(APIView):
    """DELETE /<pk>/ — удалить один свой факт."""
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk: int):
        obj = UserMemory.objects.filter(user=request.user, pk=pk).first()
        if not obj:
            return Response({"status": "error", "message": "Факт не найден"}, status=404)
        obj.delete()
        return Response({"status": "success"}, status=200)


class UserMemoryClearView(APIView):
    """POST /clear/ — удалить все свои факты."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        deleted = memory_helpers.clear(request.user)
        return Response({"status": "success", "deleted": deleted}, status=200)


class UserMemoryToggleView(APIView):
    """PATCH /toggle/ body {enabled: bool} — переключить память пользователя."""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        enabled = request.data.get("enabled")
        if not isinstance(enabled, bool):
            return Response(
                {"status": "error", "message": "Поле 'enabled' должно быть boolean"},
                status=400,
            )
        request.user.memory_enabled = enabled
        request.user.save(update_fields=["memory_enabled"])
        return Response({"status": "success", "memory_enabled": enabled}, status=200)


# === Web Push подписки (Push API / VAPID) ===

class WebPushSubscribeView(APIView):
    """Управление web-push подпиской текущего пользователя.

    POST — upsert подписки по endpoint (привязка к request.user).
      Тело: {endpoint, keys:{p256dh, auth}} ИЛИ {subscription:{endpoint, keys}}.
    DELETE — удалить свою подписку по endpoint. Тело: {endpoint}.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        data = request.data or {}
        # Поддерживаем оба формата: «плоский» и обёрнутый в subscription.
        payload = data.get("subscription") if isinstance(data.get("subscription"), dict) else data
        endpoint = (payload.get("endpoint") or "").strip()
        keys = payload.get("keys") or {}
        p256dh = (keys.get("p256dh") or "").strip()
        auth = (keys.get("auth") or "").strip()

        if not endpoint or not p256dh or not auth:
            return Response(
                {"status": "error", "message": "endpoint и keys(p256dh, auth) обязательны"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:300]

        WebPushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "user": request.user,
                "p256dh": p256dh,
                "auth": auth,
                "user_agent": user_agent,
            },
        )
        return Response({"ok": True}, status=status.HTTP_200_OK)

    def delete(self, request):
        endpoint = (request.data.get("endpoint") or "").strip() if request.data else ""
        if not endpoint:
            return Response(
                {"status": "error", "message": "endpoint обязателен"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        WebPushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
        return Response({"ok": True}, status=status.HTTP_200_OK)


class WebPushVapidKeyView(APIView):
    """GET — публичный VAPID-ключ для подписки в браузере."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"public_key": settings.VAPID_PUBLIC_KEY}, status=status.HTTP_200_OK)


# === Реферальная программа / переводы кредитов / промокоды ===

def _mask_user_label(user) -> str:
    """Публичная маска пользователя для истории: @username или маска email."""
    if not user:
        return "—"
    uname = (getattr(user, "username", "") or "").strip()
    email = (getattr(user, "email", "") or "").strip()
    # username считаем «настоящим», только если он не совпадает с email
    # (в модели пустой username фолбэчится на email).
    if uname and uname.lower() != email.lower() and "@" not in uname:
        return f"@{uname}"
    if email and "@" in email:
        local, _, domain = email.partition("@")
        if len(local) <= 2:
            masked_local = local[:1] + "*"
        else:
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain}"
    return "—"


class ReferralStatsView(APIView):
    """GET — статистика реферальной программы текущего пользователя."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum
        from plans.models import TokenTransaction

        user = request.user
        uid = getattr(user, "referral_uid", "") or ""
        link = f"https://esai.kg/auth/signup?ref={uid}" if uid else ""

        invited_count = user.referrals.count()

        earned_qs = TokenTransaction.objects.filter(user=user, reason="referral")
        total_earned = int(earned_qs.aggregate(s=Sum("delta")).get("s") or 0)

        history = []
        for tx in earned_qs.order_by("-created_at")[:50]:
            meta = tx.meta if isinstance(tx.meta, dict) else {}
            from_user = None
            ruid = meta.get("referred_user_id") or meta.get("from_user_id")
            if ruid:
                from_user = User.objects.filter(pk=ruid).first()
            history.append({
                "date": tx.created_at,
                "amount": int(tx.delta or 0),
                "from_user": _mask_user_label(from_user) if from_user else (meta.get("from_label") or "—"),
            })

        return Response({
            "referral_uid": uid,
            "link": link,
            "invited_count": invited_count,
            "total_earned": total_earned,
            "history": history,
        }, status=200)


class TransferView(APIView):
    """POST — перевод кредитов другому пользователю (без комиссии)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from django.db import transaction as _tx
        from plans.wallet import charge_tokens, credit_tokens, InsufficientTokens

        sender = request.user
        data = request.data or {}

        recipient_raw = (str(data.get("recipient") or "")).strip()
        comment = (str(data.get("comment") or "")).strip()[:200]

        # amount: целое >= 1
        amount_raw = data.get("amount")
        try:
            amount = int(amount_raw)
        except (TypeError, ValueError):
            return Response(
                {"status": "error", "message": "Некорректная сумма перевода"},
                status=400,
            )
        if amount < 1:
            return Response(
                {"status": "error", "message": "Минимальная сумма перевода — 1 кредит"},
                status=400,
            )

        if not recipient_raw:
            return Response(
                {"status": "error", "message": "Укажите получателя"},
                status=400,
            )

        # Резолв получателя: email(iexact) | username(iexact) | pk(если digit).
        recipient = (
            User.objects.filter(email__iexact=recipient_raw).first()
            or User.objects.filter(username__iexact=recipient_raw).first()
        )
        if not recipient and recipient_raw.isdigit():
            recipient = User.objects.filter(pk=int(recipient_raw)).first()

        if not recipient:
            return Response(
                {"status": "error", "message": "Получатель не найден"},
                status=400,
            )
        if not getattr(recipient, "is_active", True):
            return Response(
                {"status": "error", "message": "Аккаунт получателя неактивен"},
                status=400,
            )
        if recipient.pk == sender.pk:
            return Response(
                {"status": "error", "message": "Нельзя переводить кредиты самому себе"},
                status=400,
            )

        from_label = _mask_user_label(sender)
        to_label = _mask_user_label(recipient)

        try:
            with _tx.atomic():
                new_sender_balance = charge_tokens(
                    sender, amount, "transfer_out",
                    meta={"to_user_id": recipient.pk, "to_label": to_label, "comment": comment},
                )
                credit_tokens(
                    recipient, amount, "transfer_in",
                    meta={"from_user_id": sender.pk, "from_label": from_label, "comment": comment},
                )
        except InsufficientTokens:
            return Response(
                {"status": "error", "message": "Недостаточно кредитов"},
                status=400,
            )

        return Response({"ok": True, "balance": new_sender_balance}, status=200)


class TransferHistoryView(APIView):
    """GET — история переводов кредитов текущего пользователя (последние 100)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from plans.models import TokenTransaction

        qs = (
            TokenTransaction.objects
            .filter(user=request.user, reason__in=["transfer_in", "transfer_out"])
            .order_by("-created_at")[:100]
        )
        items = []
        for tx in qs:
            meta = tx.meta if isinstance(tx.meta, dict) else {}
            direction = "in" if tx.reason == "transfer_in" else "out"
            counterparty = meta.get("from_label") if direction == "in" else meta.get("to_label")
            items.append({
                "date": tx.created_at,
                "direction": direction,
                "amount": abs(int(tx.delta or 0)),
                "counterparty": counterparty or "—",
                "comment": (meta.get("comment") or ""),
            })
        return Response(items, status=200)


class PromoActivateView(APIView):
    """POST — активация промокода (фиксированные кредиты). Тело {code}."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from .services import activate_promo

        code = (str((request.data or {}).get("code") or "")).strip()
        if not code:
            return Response(
                {"status": "error", "message": "Введите промокод"},
                status=400,
            )
        ok, msg, credited = activate_promo(request.user, code)
        if not ok:
            return Response({"status": "error", "message": msg}, status=400)
        balance = int(getattr(request.user, "token_balance", 0) or 0)
        return Response(
            {"ok": True, "credited": credited, "balance": balance, "message": msg},
            status=200,
        )
