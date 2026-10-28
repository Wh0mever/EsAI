"""Middleware аудита.

- AuditExceptionMiddleware ловит необработанные исключения во вьюхах и пишет
  их в EventLog как error_server. Само исключение НЕ подавляется (возвращаем
  None), Django отдаёт обычный 500.
- ActivityDayMiddleware отмечает «человек был на сайте сегодня» для отчёта
  «Возвраты» (audit.activity.touch).
"""

import logging
import traceback

from django.db import connection
from django.utils.functional import SimpleLazyObject, empty

from .activity import touch
from .services import log_event

logger = logging.getLogger("audit")


class AuditExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        try:
            user = getattr(request, "user", None)
            if user is not None and not getattr(user, "is_authenticated", False):
                user = None
            meta = {
                "path": getattr(request, "path", ""),
                "method": getattr(request, "method", ""),
                "exc_type": type(exception).__name__,
                # ограничиваем размер трейсбэка, чтобы не раздувать JSON
                "traceback": traceback.format_exc()[-4000:],
            }
            log_event(
                "error_server",
                message=f"{type(exception).__name__}: {exception}"[:1000],
                user=user,
                meta=meta,
                level="error",
            )
        except Exception:
            # middleware не должен ломать обработку ошибки
            pass
        # Возвращаем None => Django продолжает штатную обработку исключения.
        return None


class ActivityDayMiddleware:
    """Живой учёт дней активности: авторизованный запрос = человек был на сайте.

    Пользователя смотрим ПОСЛЕ ответа вью: JWT разбирает DRF уже внутри вью и
    сам кладёт пользователя в django-request (сеттер Request.user пишет и
    self._request.user), а до вью там лишь аноним из сессии. Поэтому место в
    списке MIDDLEWARE для учёта не важно.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._record(request, response)
        except Exception as exc:
            # Учёт не должен ломать ответ, который уже готов.
            logger.warning("activity middleware failed: %s", exc)
        return response

    @staticmethod
    def _record(request, response):
        # Ответ 5xx — сайт подвёл человека, такой заход в «вернулся» не пишем.
        if getattr(response, "status_code", 500) >= 500:
            return
        user = getattr(request, "user", None)
        if user is None:
            return
        # Ленивый пользователь сессии, которого вью так и не спросила (не-DRF
        # вью, статика, проверки живости): раскрывать его ради учёта — лишний
        # запрос к сессиям на каждый такой ответ, а вход на сайт идёт через DRF.
        if isinstance(user, SimpleLazyObject) and user._wrapped is empty:
            return
        if not getattr(user, "is_authenticated", False):
            return
        # Внутри чужой транзакции не пишем. В бою её здесь нет: ATOMIC_REQUESTS
        # оборачивает только саму вью, и до этой строки транзакция вью уже
        # закрыта. Внешняя транзакция бывает у тестов на TestCase: там запись
        # дня откатилась бы вместе с тестом, а лишний запрос сбил бы чужие
        # проверки числа запросов и колбэков on_commit. Свой тест middleware
        # поэтому на TransactionTestCase.
        if connection.in_atomic_block:
            return
        touch(user)
