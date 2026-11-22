"""Ошибки API Creative Studio: тело {"error", "error_code", …} — как у видеостудии.

Фронт переводит по error_code (пространство creative), русский текст — запасной.
Тексты нейтральные: имя поставщика и его ответы в них не попадают никогда.
Собственные отказы DRF (401, 429, кривой JSON) приводит к тому же виду
обработчик видеостудии (vstudio.errors.exception_handler).
"""
from __future__ import annotations

from rest_framework import exceptions as drf_exc
from rest_framework import status as http
from rest_framework.response import Response
from rest_framework.views import set_rollback

from vstudio.errors import exception_handler as _studio_handler

MESSAGES: dict[str, str] = {
    "bad_request": "Некорректный запрос. Обновите страницу и попробуйте снова.",
    "unauthorized": "Войдите, чтобы продолжить.",
    "creative_disabled": "Creative Studio скоро откроется.",
    "tool_disabled": "Этот инструмент временно недоступен.",
    "tool_not_found": "Инструмент не найден.",
    "job_not_found": "Работа не найдена.",
    "character_not_found": "Персонаж не найден.",
    "catalog_not_found": "Каталог не найден.",
    "not_found": "Не найдено.",
    "bad_params": "Проверьте поля формы — часть из них заполнена неверно.",
    "price_changed": "Цена изменилась: теперь {credits} кр. Проверьте и нажмите «Создать» ещё раз.",
    "price_unavailable": "Цена сейчас недоступна, попробуйте позже.",
    "already_submitted": "Работа уже отправлена в генерацию — отменить её нельзя.",
    "provider_unavailable": "Генерация временно недоступна. Попробуйте через несколько минут — кредиты не списаны.",
    "storage_unavailable": "Сохранение результатов временно недоступно. Попробуйте позже — кредиты не списаны.",
    "catalog_unavailable": "Список вариантов сейчас недоступен, попробуйте через минуту.",
    "throttled": "Слишком много запросов. Подождите немного и попробуйте снова.",
    # Загрузки
    "bad_type": "Этот формат не подходит.",
    "too_big": "Файл слишком большой.",
    "too_short": "Видео слишком короткое.",
    "too_long": "Видео слишком длинное.",
    "too_small_frame": "Разрешение видео слишком маленькое.",
    "unreadable": "Файл не читается — возможно, он повреждён.",
    "upload_busy": "Сейчас обрабатывается много файлов — попробуйте через несколько секунд.",
    "upload_quota": "Загружено слишком много файлов. Старые загрузки удаляются через неделю — "
                    "используйте уже загруженные или попробуйте позже.",
    "too_heavy": "Видео не успело обработаться. Укоротите его или уменьшите разрешение и загрузите снова.",
    "server_error": "Что-то пошло не так. Попробуйте ещё раз.",
}

DEFAULT_STATUS: dict[str, int] = {
    "bad_request": http.HTTP_400_BAD_REQUEST,
    "unauthorized": http.HTTP_401_UNAUTHORIZED,
    "creative_disabled": http.HTTP_403_FORBIDDEN,
    "tool_disabled": http.HTTP_403_FORBIDDEN,
    "tool_not_found": http.HTTP_404_NOT_FOUND,
    "job_not_found": http.HTTP_404_NOT_FOUND,
    "character_not_found": http.HTTP_404_NOT_FOUND,
    "catalog_not_found": http.HTTP_404_NOT_FOUND,
    "not_found": http.HTTP_404_NOT_FOUND,
    "bad_params": http.HTTP_422_UNPROCESSABLE_ENTITY,
    "price_changed": http.HTTP_409_CONFLICT,
    "already_submitted": http.HTTP_409_CONFLICT,
    "price_unavailable": http.HTTP_503_SERVICE_UNAVAILABLE,
    "provider_unavailable": http.HTTP_503_SERVICE_UNAVAILABLE,
    "storage_unavailable": http.HTTP_503_SERVICE_UNAVAILABLE,
    "catalog_unavailable": http.HTTP_503_SERVICE_UNAVAILABLE,
    "throttled": http.HTTP_429_TOO_MANY_REQUESTS,
    "bad_type": http.HTTP_422_UNPROCESSABLE_ENTITY,
    "too_big": http.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    "too_short": http.HTTP_422_UNPROCESSABLE_ENTITY,
    "too_long": http.HTTP_422_UNPROCESSABLE_ENTITY,
    "too_small_frame": http.HTTP_422_UNPROCESSABLE_ENTITY,
    "unreadable": http.HTTP_422_UNPROCESSABLE_ENTITY,
    "upload_busy": http.HTTP_429_TOO_MANY_REQUESTS,
    "upload_quota": http.HTTP_409_CONFLICT,
    "too_heavy": http.HTTP_422_UNPROCESSABLE_ENTITY,
}


class _Blank(dict):
    def __missing__(self, key):
        return ""


class CreativeError(drf_exc.APIException):
    """Отказ в форме Creative Studio.

        raise CreativeError("job_not_found")
        raise CreativeError("price_changed", credits=12)
        raise CreativeError("bad_params", errors=[{"field": "prompt", "code": "required"}])
    """

    def __init__(self, code: str, *, status: int | None = None, message: str | None = None, **extra):
        self.code = code
        self.status_code = int(status or DEFAULT_STATUS.get(code, http.HTTP_400_BAD_REQUEST))
        template = message if message is not None else MESSAGES.get(code, MESSAGES["bad_request"])
        self.message = template.format_map(_Blank(extra)) if "{" in template else template
        self.extra = extra
        super().__init__(detail=self.message, code=code)

    def payload(self) -> dict:
        return error_body(self.code, self.message, **self.extra)


def error_body(code: str, message: str | None = None, **extra) -> dict:
    return {"error": message if message is not None else MESSAGES.get(code, MESSAGES["bad_request"]),
            "error_code": code, **extra}


def error_response(code: str, *, status: int | None = None, message: str | None = None,
                   **extra) -> Response:
    """Отказ без исключения: транзакцию запроса не откатывает."""
    return Response(error_body(code, message, **extra),
                    status=int(status or DEFAULT_STATUS.get(code, http.HTTP_400_BAD_REQUEST)))


def exception_handler(exc, context):
    if isinstance(exc, CreativeError):
        set_rollback()
        return Response(exc.payload(), status=exc.status_code)
    return _studio_handler(exc, context)


__all__ = ["MESSAGES", "DEFAULT_STATUS", "CreativeError", "error_body", "error_response",
           "exception_handler"]
