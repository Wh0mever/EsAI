"""Ошибки API видеостудии (спецификация §8.1, §8.4).

Любой отказ /api/vstudio/ — тело одного вида:

    {"error": "<русский текст>", "error_code": "<код>", …доп. поля}

Фронт (lib/vstudio/errors.ts) переводит по error_code, а русский текст
бэкенда — defaultValue. Поэтому и собственные отказы DRF (401 без входа, 429
троттлинга, 405, кривой JSON) приводятся к тому же виду: иначе у них был бы
только {"detail": …}, и фронт не знал бы, что показать. Поле detail оставляем:
по нему старый fetchData поднимает текст ошибки.
"""
from __future__ import annotations

from rest_framework import exceptions as drf_exc
from rest_framework import status as http
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.views import set_rollback

# Тексты по коду (§8.4). Совпадают с HTTP_RU фронта — там они defaultValue.
MESSAGES: dict[str, str] = {
    "bad_request": "Некорректный запрос. Обновите страницу и попробуйте снова.",
    "unauthorized": "Войдите, чтобы продолжить.",
    "forbidden": "Нет доступа.",
    "premium_locked": "Эта модель доступна только на платном тарифе.",
    "vstudio_disabled": "Видеостудия скоро откроется.",
    "project_not_found": "Проект не найден.",
    "take_not_found": "Генерация не найдена.",
    "asset_not_found": "Материал не найден — возможно, он удалён.",
    "shot_not_found": "Запрос не найден.",
    "not_found": "Не найдено.",
    "method_not_allowed": "Такой запрос здесь не поддерживается.",
    "price_changed": "Цена изменилась: теперь {credits} кр. Проверьте и нажмите «Создать» ещё раз.",
    "already_submitted": "Генерация уже отправлена модели — отменить её нельзя.",
    "blocked": "Запрос нельзя запустить — исправьте отмеченное.",
    "prompt_doc_invalid": "Не удалось прочитать текст запроса. Обновите страницу и попробуйте снова.",
    "throttled": "Слишком много запросов. Подождите немного и попробуйте снова.",
    "service_misconfigured": "Студия временно недоступна. Мы уже чиним.",
    "server_error": "Что-то пошло не так. Попробуйте ещё раз.",
}

DEFAULT_STATUS: dict[str, int] = {
    "bad_request": http.HTTP_400_BAD_REQUEST,
    "unauthorized": http.HTTP_401_UNAUTHORIZED,
    "forbidden": http.HTTP_403_FORBIDDEN,
    "premium_locked": http.HTTP_403_FORBIDDEN,
    "vstudio_disabled": http.HTTP_403_FORBIDDEN,
    "project_not_found": http.HTTP_404_NOT_FOUND,
    "take_not_found": http.HTTP_404_NOT_FOUND,
    "asset_not_found": http.HTTP_404_NOT_FOUND,
    "shot_not_found": http.HTTP_404_NOT_FOUND,
    "not_found": http.HTTP_404_NOT_FOUND,
    "method_not_allowed": http.HTTP_405_METHOD_NOT_ALLOWED,
    "price_changed": http.HTTP_409_CONFLICT,
    "already_submitted": http.HTTP_409_CONFLICT,
    "blocked": http.HTTP_422_UNPROCESSABLE_ENTITY,
    "prompt_doc_invalid": http.HTTP_422_UNPROCESSABLE_ENTITY,
    "throttled": http.HTTP_429_TOO_MANY_REQUESTS,
    "service_misconfigured": http.HTTP_503_SERVICE_UNAVAILABLE,
}


class _Blank(dict):
    def __missing__(self, key):
        return ""


class StudioError(drf_exc.APIException):
    """Отказ в форме студии. Бросается из вьюх и проверок доступа.

        raise StudioError("project_not_found")
        raise StudioError("price_changed", credits=164, breakdown=[…])

    Статус по умолчанию — из DEFAULT_STATUS; message — свой текст вместо
    стандартного; остальные именованные аргументы уходят в тело как есть.
    Как любое APIException, откатывает транзакцию запроса (ATOMIC_REQUESTS).
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
    """{"error", "error_code", …} — единая форма тела отказа."""
    return {"error": message if message is not None else MESSAGES.get(code, MESSAGES["bad_request"]),
            "error_code": code, **extra}


def error_response(code: str, *, status: int | None = None, message: str | None = None,
                   **extra) -> Response:
    """Ответ-отказ без исключения: транзакцию запроса не откатывает.

    Нужен там, где в базе ничего не менялось, а откат лишний (402/409 гейта).
    """
    return Response(error_body(code, message, **extra),
                    status=int(status or DEFAULT_STATUS.get(code, http.HTTP_400_BAD_REQUEST)))


def _code_for(exc, status_code: int) -> str:
    if isinstance(exc, (drf_exc.NotAuthenticated, drf_exc.AuthenticationFailed)):
        return "unauthorized"
    if isinstance(exc, drf_exc.Throttled):
        return "throttled"
    if isinstance(exc, drf_exc.PermissionDenied):
        return "forbidden"
    if isinstance(exc, drf_exc.MethodNotAllowed):
        return "method_not_allowed"
    if isinstance(exc, (drf_exc.ParseError, drf_exc.ValidationError, drf_exc.UnsupportedMediaType)):
        return "bad_request"
    if status_code == http.HTTP_404_NOT_FOUND:
        return "not_found"
    if status_code == http.HTTP_401_UNAUTHORIZED:
        return "unauthorized"
    if status_code >= 500:
        return "server_error"
    return "bad_request"


def exception_handler(exc, context):
    """Обработчик исключений только для вьюх студии (APIView.get_exception_handler)."""
    if isinstance(exc, StudioError):
        set_rollback()
        return Response(exc.payload(), status=exc.status_code)
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    code = _code_for(exc, response.status_code)
    data = error_body(code)
    original = response.data
    if isinstance(original, dict) and "detail" in original:
        data["detail"] = original["detail"]
    elif original:
        data["detail"] = original
    if isinstance(exc, drf_exc.Throttled) and exc.wait is not None:
        # Сколько секунд подождать — фронт может показать обратный отсчёт.
        data["wait"] = int(exc.wait + 0.999)
    response.data = data
    return response


__all__ = ["MESSAGES", "DEFAULT_STATUS", "StudioError", "error_body", "error_response",
           "exception_handler"]
