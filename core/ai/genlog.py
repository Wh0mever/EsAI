"""Запись в журнал генераций. Никогда не роняет саму генерацию.

Журнал — вспомогательная вещь: если база моргнула в момент записи, человек всё
равно должен получить свой ролик. Поэтому каждая операция обёрнута, а вместо
записи при сбое возвращается пустышка с тем же интерфейсом.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.utils import timezone

logger = logging.getLogger(__name__)


class _Null:
    """Журнал недоступен: вызовы проходят молча."""

    pk = None

    def stage(self, *args, **kwargs):
        return self

    def touch(self):
        return self

    def is_open(self) -> bool:
        return True

    def claim_delivery(self, *args, **kwargs) -> bool:
        return True

    def attach_message(self, *args, **kwargs):
        return None

    def submitted(self, *args, **kwargs):
        return self

    def delivered(self, *args, **kwargs):
        return self

    def failed(self, *args, **kwargs):
        return self

    def lost(self, *args, **kwargs):
        return self


class Entry:
    """Одна генерация в журнале."""

    def __init__(self, row):
        self.row = row

    @property
    def pk(self):
        return self.row.pk

    def touch(self) -> "Entry":
        """Отметить, что генерация жива: довозить её пока не надо."""
        try:
            type(self.row).objects.filter(pk=self.row.pk).update(updated_at=timezone.now())
        except Exception:
            logger.debug("журнал генераций: пульс не записался", exc_info=True)
        return self

    def is_open(self) -> bool:
        """Не выдал ли уже этот ролик кто-то другой (фоновая задача)."""
        try:
            self.row.refresh_from_db(fields=["status"])
            return self.row.status in type(self.row).OPEN_STATES
        except Exception:
            return True

    def claim_delivery(self, *, recovered: bool = False) -> bool:
        """Атомарно забрать выдачу ролика себе: открытая запись → выдана.

        Живой поток и фоновый довоз (recovery) могли выдать один и тот же ролик
        оба: каждый проверял «ещё не выдан?» отдельным чтением, а потом сохранял
        сообщение и списывал кредиты — человек получал два сообщения и два
        списания. Теперь выдачу забирает условный UPDATE по статусу: вторая
        сторона ждёт на блокировке строки и получает 0 строк. Вызывать ВНУТРИ
        той же транзакции, что создаёт сообщение и списывает: если она
        откатится, запись снова станет открытой и её довезут.
        """
        from django.db import transaction

        from .models import GenerationLog

        status = GenerationLog.STATUS_RECOVERED if recovered else GenerationLog.STATUS_DELIVERED
        try:
            with transaction.atomic():
                taken = GenerationLog.objects.filter(
                    pk=self.row.pk, status__in=GenerationLog.OPEN_STATES,
                ).update(status=status, updated_at=timezone.now())
        except Exception:
            # Журнал не отвечает — не лишаем человека оплаченного ролика.
            logger.exception("журнал генераций: выдачу %s забрать не удалось", self.row.pk)
            return True
        if taken:
            self.row.status = status
        return bool(taken)

    def attach_message(self, message, *, credits: int = 0, result_url: str = "") -> None:
        """Записать сообщение с результатом сразу, в транзакции выдачи.

        Проигравшая сторона (см. claim_delivery) по нему находит уже выданный
        ролик и показывает его человеку, а не «обновите страницу».
        """
        from .models import GenerationLog

        GenerationLog.objects.filter(pk=self.row.pk).update(
            message=message, credits_charged=max(0, int(credits or 0)),
            result_url=str(result_url or "")[:512])

    def _save(self, fields: list) -> None:
        try:
            self.row.save(update_fields=list(dict.fromkeys(fields + ["updated_at"])))
        except Exception:
            logger.exception("журнал генераций: запись %s не сохранилась", self.row.pk)

    def stage(self, stage: str, note: str = "") -> "Entry":
        """Отметить шаг: отправили, приняли, скачали, сохранили, списали."""
        try:
            steps = list(self.row.stages or [])
            steps.append({"at": timezone.now().isoformat(timespec="seconds"),
                          "stage": stage, "note": str(note or "")[:300]})
            self.row.stages = steps[-40:]
            self._save(["stages"])
        except Exception:
            logger.exception("журнал генераций: шаг не записался")
        return self

    def submitted(self, provider_id: str = "", polling_url: str = "") -> "Entry":
        """Провайдер принял запрос. С этой секунды он берёт за него деньги."""
        from .models import GenerationLog

        self.row.status = GenerationLog.STATUS_SUBMITTED
        self.row.provider_id = str(provider_id or "")[:160]
        self.row.polling_url = str(polling_url or "")[:512]
        self._save(["status", "provider_id", "polling_url"])
        return self.stage("submitted", self.row.provider_id)

    def delivered(self, *, credits: int = 0, cost=None, result_url: str = "", message=None,
                  recovered: bool = False) -> "Entry":
        from .models import GenerationLog

        self.row.status = (GenerationLog.STATUS_RECOVERED if recovered
                           else GenerationLog.STATUS_DELIVERED)
        self.row.credits_charged = max(0, int(credits or 0))
        self.row.result_url = str(result_url or "")[:512]
        self.row.needs_review = False
        fields = ["status", "credits_charged", "result_url", "needs_review"]
        if message is not None:
            self.row.message = message
            fields.append("message")
        amount = _money(cost)
        if amount is not None:
            self.row.provider_cost_usd = amount
            fields.append("provider_cost_usd")
        self._save(fields)
        return self.stage("recovered" if recovered else "delivered",
                          f"списано {self.row.credits_charged} кр")

    def failed(self, error: str = "", *, review: bool = False) -> "Entry":
        from .models import GenerationLog

        self.row.status = GenerationLog.STATUS_FAILED
        self.row.error = str(error or "")[:2000]
        self.row.needs_review = bool(review)
        self._save(["status", "error", "needs_review"])
        return self.stage("failed", self.row.error[:200])

    def lost(self, error: str = "") -> "Entry":
        """Провайдер деньги взял (или мог взять), а результата у человека нет."""
        from .models import GenerationLog

        self.row.status = GenerationLog.STATUS_LOST
        self.row.error = str(error or "")[:2000]
        self.row.needs_review = True
        self._save(["status", "error", "needs_review"])
        return self.stage("lost", self.row.error[:200])


def _money(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError, TypeError):
        return None


def start(*, user, kind: str, model: str = "", source: str = "chat", provider: str = "openrouter",
          prompt: str = "", params: dict | None = None, credits_planned: int = 0,
          session=None, scene_id: int | None = None, ip: str | None = None):
    """Начать запись о генерации. Возвращает Entry или пустышку."""
    try:
        from .models import GenerationLog

        row = GenerationLog.objects.create(
            user=user if getattr(user, "pk", None) else None,
            kind=kind, source=source, provider=provider, model=str(model or "")[:120],
            prompt=str(prompt or "")[:2000], params=_plain(params or {}),
            credits_planned=max(0, int(credits_planned or 0)),
            session=session, scene_id=scene_id, ip=_valid_ip(ip),
            stages=[{"at": timezone.now().isoformat(timespec="seconds"),
                     "stage": "started", "note": ""}],
        )
        return Entry(row)
    except Exception:
        logger.exception("журнал генераций: запись не создалась")
        return _Null()


def _valid_ip(value):
    """IP из заголовка — только если это правда IP.

    X-Forwarded-For задаёт клиент: мусор вроде «unknown» или «1.2.3.4:5678» в
    GenericIPAddressField ронял на Postgres всю вставку, и генерация шла без
    строки в журнале (её потом не находил довоз).
    """
    import ipaddress

    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def _plain(params: dict) -> dict:
    """Только то, что ляжет в JSON: без файлов, байтов и объектов."""
    out = {}
    for key, value in (params or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[str(key)] = value if not isinstance(value, str) else value[:500]
        elif isinstance(value, (list, tuple)):
            out[str(key)] = [str(v)[:300] for v in list(value)[:10]]
        else:
            out[str(key)] = str(value)[:300]
    return out
