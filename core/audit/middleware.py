"""Middleware аудита: ловит необработанные исключения во вьюхах
и пишет их в EventLog как error_server.

Само исключение НЕ подавляется (возвращаем None), Django отдаёт обычный 500.
"""

import traceback

from .services import log_event


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
