"""Ошибки программы Creators: стабильный код для фронтенда и русский текст.

Интерфейс на трёх языках переводит по коду, поэтому код — контракт, а текст —
запасной вариант для тех мест, где перевода ещё нет (бот, админка).
"""
from __future__ import annotations

DEFAULT_MESSAGE = "Не удалось выполнить действие"

# code -> русский текст. Здесь каждый код, который сервисы программы отдают наружу.
MESSAGES: dict[str, str] = {
    # 404
    "disabled": "Программа EsAI Creators сейчас недоступна",
    "not_found": "Не найдено",
    # 403
    "not_creator": "Вы не участник программы EsAI Creators",
    "creator_blocked": "Аккаунт креатора заблокирован",
    "superuser_required": "Это действие доступно только главному администратору",
    "apply_blocked": "Подача заявки для этого аккаунта закрыта",
    "payouts_disabled": "Заявки на вывод временно не принимаются",
    # 409
    "already_creator": "Вы уже участник программы EsAI Creators",
    "application_open": "Ваша заявка уже на рассмотрении",
    "code_taken": "Этот промокод уже занят",
    "code_already_set": "Промокод уже создан. Изменить его может только администратор",
    "code_unchanged": "Этот промокод уже установлен",
    "already_bound": "Пользователь уже закреплён за другим креатором",
    "has_referrer": "Пользователь уже зарегистрирован по приглашению",
    "publication_duplicate": "Эта публикация уже добавлена",
    "withdrawal_open": "У вас уже есть заявка на вывод в работе",
    "txid_duplicate": "Этот TXID уже указан в другой выплате",
    "bad_state": "Действие недоступно в текущем статусе",
    "already_marked": "Платёж уже отмечен как возвращённый",
    "payment_refunded": "Платёж возвращён — комиссию по нему начислить нельзя",
    "duplicate_request": "Такой запрос только что выполнен. Подождите несколько секунд",
    "creator_conflict": "Оба аккаунта участвуют в программе Creators — обратитесь в поддержку",
    # 400
    "validation": "Проверьте заполнение полей",
    "links_required": "Укажите хотя бы одну ссылку на соцсеть",
    "code_format": "Промокод: от 4 до 16 символов, латинские буквы и цифры, первой идёт буква",
    "code_reserved": "Этот промокод использовать нельзя",
    "self": "Нельзя использовать собственный промокод",
    "staff": "Сотрудника нельзя закрепить за креатором",
    "creator_unusable": "Этот креатор сейчас не может принимать рефералов",
    "too_late": "Промокод креатора можно ввести только в первые 72 часа после регистрации",
    "already_paid": "Промокод креатора можно ввести только до первой оплаты",
    "link_window": "Ссылка креатора действует только при регистрации",
    "race": "Не удалось выполнить действие, попробуйте ещё раз",
    "no_user": "Пользователь не найден или отключён",
    "already_bound_same": "Пользователь уже закреплён за этим креатором",
    "network_invalid": "Выберите социальную сеть из списка",
    "url_invalid": "Укажите корректную ссылку (http:// или https://)",
    "address_required": "Укажите адрес кошелька USDT TRC20",
    "address_invalid": "Некорректный адрес USDT TRC20",
    "amount_invalid": "Некорректная сумма",
    "amount_below_min": "Минимальная сумма вывода — 10 USDT",
    "insufficient_available": "Недостаточно средств, доступных к выводу",
    "txid_invalid": "Некорректный TXID: нужны 64 шестнадцатеричных символа",
    "reason_required": "Укажите причину",
    "kind_invalid": "Укажите вид отметки: refund или fraud",
    "category_invalid": "Выберите причину начисления из списка",
    "level_unknown": "Такого уровня нет",
    "percent_invalid": "Процент комиссии должен быть больше 0 и не больше 25",
    # База комиссии (creators.commission.compute_base): наружу не уходят,
    # попадают в поле reason аннулированной комиссии.
    "no_base": "Не удалось определить сумму оплаты",
    "unsupported_currency": "Валюта платежа не поддерживается",
    "unsupported_provider": "Платёжная система не поддерживается",
}

# code -> HTTP-статус. Кода нет в таблице — 400.
HTTP: dict[str, int] = {
    "disabled": 404,
    "not_found": 404,
    "not_creator": 403,
    "creator_blocked": 403,
    "superuser_required": 403,
    "apply_blocked": 403,
    "payouts_disabled": 403,
    "already_creator": 409,
    "application_open": 409,
    "code_taken": 409,
    "code_already_set": 409,
    "code_unchanged": 409,
    "already_bound": 409,
    "has_referrer": 409,
    "publication_duplicate": 409,
    "withdrawal_open": 409,
    "txid_duplicate": 409,
    "bad_state": 409,
    "already_marked": 409,
    "payment_refunded": 409,
    "duplicate_request": 409,
    "creator_conflict": 409,
}


class CreatorsError(Exception):
    """Отказ сервиса программы: код + текст + HTTP-статус + доп. поля ответа."""

    def __init__(self, code: str, message: str = "", http: int | None = None, **extra):
        self.code = str(code)
        self.message = str(message or MESSAGES.get(self.code) or DEFAULT_MESSAGE)
        self.http = int(http or HTTP.get(self.code, 400))
        self.extra = extra
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def error_body(exc) -> dict:
    """Тело ответа об ошибке: detail всегда строка и равен message."""
    code = str(getattr(exc, "code", "") or "error")
    message = str(getattr(exc, "message", "") or MESSAGES.get(code) or DEFAULT_MESSAGE)
    # Доп. поля не могут подменить код и текст.
    body = dict(getattr(exc, "extra", None) or {})
    body.update({"code": code, "message": message, "detail": message})
    return body
