"""Серверный отчёт видеостудии (§11): что запускали, что выдали, сколько заработали.

Отдаётся админке через GET /api/manage/vstudio/report/?days=30 (adminapi.vstudio).
Интерфейс в admin-new — Фаза 1.5, поэтому ответ самодостаточный: цифры по
дням, по моделям и на пересечении «день × модель», плюс подписи статусов и
режимов, чтобы странице не пришлось их дублировать.

Источники:
- таблица дублей (Take) — правда об исходах и деньгах: статусы, коды ошибок,
  резерв и списание, время, режим, промпт, ушедший модели;
- журнал генераций (GenerationLog) — needs_review и себестоимость, если на
  дубле её нет, а также сверка «журнал ↔ дубль» (зачистка sweep §6.5 п. 7);
- клиентская воронка — только «Сжать с ИИ»: сервер это бесплатное действие
  нигде не записывает, и шаг vstudio_condense {accepted} — единственный след.

День — это день СОЗДАНИЯ дубля по времени сайта (TIME_ZONE): так видно, чем
кончились запуски конкретного дня, даже если ролик доехал после полуночи.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import re
from collections import Counter
from decimal import Decimal

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from .models import TAKE_CLOSED, TAKE_OPEN, Take

logger = logging.getLogger("vstudio")

DEFAULT_DAYS = 30
MAX_DAYS = 365
KINDS = (Take.KIND_VIDEO, Take.KIND_IMAGE)

# Режимы, в которых модели ушли фото-референсы / кадры (§4.4 п. 2). r2v_pin —
# и то и другое: первый кадр уходит последним референсом.
REF_MODES = frozenset({Take.MODE_R2V, Take.MODE_R2V_PIN, Take.MODE_I2I})
FRAME_MODES = frozenset({Take.MODE_I2V, Take.MODE_FLF2V, Take.MODE_R2V_PIN})

# Слова считаем тем же выражением, что компилятор (meter.words), иначе «выше
# мягкого лимита» в отчёте разошлось бы с жёлтым счётчиком у человека.
_WORD = re.compile(r"\S+")

_NO_CODE = "unknown"


def parse_days(raw, default: int = DEFAULT_DAYS) -> int:
    """?days= → 1…365. Мусор — значение по умолчанию, как у отчёта воронки."""
    try:
        return max(1, min(MAX_DAYS, int(raw)))
    except (TypeError, ValueError):
        return default


def percentile(values, q: float) -> float | None:
    """Процентиль с линейной интерполяцией (как numpy по умолчанию). Пусто → None."""
    data = sorted(values)
    if not data:
        return None
    pos = (len(data) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return float(data[lo] + (data[hi] - data[lo]) * (pos - lo))


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _usd(value) -> float:
    return round(float(value or 0), 4)


def _seconds(values) -> dict:
    med, p90 = percentile(values, 0.5), percentile(values, 0.9)
    return {"n": len(values),
            "median": round(med, 1) if med is not None else None,
            "p90": round(p90, 1) if p90 is not None else None}


def _credit_usd() -> float | None:
    """Цена самого дешёвого кредита в $ — нижняя граница выручки (как в §5.1).

    Отчёт не должен падать из-за курса валют или пустого прайса: тогда деньги
    в долларах не считаем (None), а кредиты и себестоимость всё равно видны.
    """
    try:
        from ai import pricing as ai_pricing

        # В режиме наценки кредит считается так же, как цены (закреплённый курс),
        # иначе отчёт и check_margin расходились бы в «низкой марже».
        if ai_pricing.is_markup():
            value = ai_pricing.credit_usd()
            return float(value) if value else None
        from ai.video_cost import cheapest_credit_usd

        value = cheapest_credit_usd()
        return float(value) if value else None
    except Exception:
        logger.exception("vstudio report: цена кредита не посчиталась")
        return None


def _min_margin() -> float:
    try:
        from ai import pricing as ai_pricing

        cfg = ai_pricing.current_config()
        if cfg.markup:
            # Порог наценки f% в терминах маржи: выручка ≥ cost×(1+f/100) ⇔ маржа ≥ f/(100+f).
            return float(cfg.floor_pct / (100 + cfg.floor_pct))
        from ai.video_cost import min_margin

        return float(min_margin())
    except Exception:
        logger.exception("vstudio report: минимальная маржа не прочиталась")
        return float(getattr(settings, "VIDEO_MIN_MARGIN", 0.4))


def _soft_words(model_ref: str) -> int | None:
    """Мягкий лимит слов модели из реестра (у картинок его нет)."""
    try:
        from .caps import family_of

        fam = family_of(model_ref)
        return fam.prompt_soft_words if fam else None
    except Exception:
        return None


def _model_kind(model_ref: str) -> str:
    try:
        from .caps import family_of

        fam = family_of(model_ref)
        return fam.kind if fam else ""
    except Exception:
        return ""


def _warning_codes(raw) -> set[str]:
    if not isinstance(raw, list):
        return set()
    return {str(w.get("code")) for w in raw if isinstance(w, dict) and w.get("code")}


def _local_date(value) -> dt.date:
    return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()


class _Row:
    """Один дубль, приведённый к тому, что нужно отчёту (считается один раз)."""

    __slots__ = ("day", "model", "kind", "mode", "status", "code", "charge_state",
                 "quoted", "reserved", "charged", "cost", "needs_review", "chars", "words",
                 "soft", "over_soft", "script_like", "wait_s", "render_s")

    def __init__(self, r: dict, soft: int | None):
        self.day = _local_date(r["created_at"]).isoformat()
        self.model = r["model_ref"] or ""
        self.kind = r["kind"]
        self.mode = r["mode"] or ""
        self.status = r["status"]
        self.code = r["error_code"] or _NO_CODE
        self.charge_state = r["charge_state"]
        self.quoted = int(r["credits_quoted"] or 0)
        self.reserved = int(r["credits_reserved"] or 0)
        self.charged = int(r["credits_charged"] or 0)
        # Себестоимость пишет выдача в дубль; если её нет (потерян, не
        # получилось), берём из журнала — довоз или разбор мог её записать.
        cost = r["provider_cost_usd"]
        if cost is None:
            cost = r["genlog__provider_cost_usd"]
        self.cost = Decimal(str(cost)) if cost is not None else None
        self.needs_review = bool(r["genlog__needs_review"])
        text = r["serialized_prompt"] or ""
        self.chars = len(text)
        self.words = len(_WORD.findall(text))
        codes = _warning_codes(r["warnings"])
        self.soft = soft
        # Предупреждение — то, что человек видел; слова — страховка, если
        # предупреждения не сохранились (оба считаются одинаково, §4.4 п. 6).
        self.over_soft = bool(soft) and ("prompt_long" in codes or self.words > soft)
        self.script_like = "looks_like_script" in codes
        self.wait_s = self.render_s = None
        # Время до результата — только у обычной выдачи. Довоз из lost идёт
        # часами позже и испортил бы p90 (его видно отдельно, как redelivered).
        if self.status == Take.STATUS_DONE and self.charge_state == Take.CHARGE_CHARGED \
                and r["finished_at"]:
            self.wait_s = max(0.0, (r["finished_at"] - r["created_at"]).total_seconds())
            if r["submitted_at"]:
                self.render_s = max(0.0, (r["finished_at"] - r["submitted_at"]).total_seconds())


class _Bucket:
    """Сумматор по группе дублей (весь период, день, модель, день × модель)."""

    def __init__(self):
        self.created = 0
        self.status = Counter()
        self.failed_codes = Counter()
        self.lost_codes = Counter()
        self.modes = Counter()
        self.redelivered = 0
        self.needs_review = 0
        self.with_refs = 0
        self.with_frames = 0
        self.chars_sum = 0
        self.words_sum = 0
        self.chars_max = 0
        self.with_soft = 0
        self.over_soft = 0
        self.script_like = 0
        self.wait = []
        self.render = []
        self.quoted = 0
        self.charged = 0
        self.partial = 0
        self.partial_shortfall = 0
        self.cost = Decimal("0")
        self.cost_known = 0
        self.cost_unpaid = Decimal("0")
        self.done_without_cost = 0
        self.revenue_credits_costed = 0
        self.cost_costed = Decimal("0")
        self.low_margin = 0
        self.condense = 0
        self.condense_accepted = 0

    def add(self, row: _Row, credit_usd: float | None, min_margin: float) -> None:
        self.created += 1
        self.status[row.status] += 1
        self.modes[row.mode] += 1
        if row.status == Take.STATUS_FAILED:
            self.failed_codes[row.code] += 1
        elif row.status == Take.STATUS_LOST:
            self.lost_codes[row.code] += 1
        paid = row.status == Take.STATUS_DONE and row.charge_state == Take.CHARGE_CHARGED
        if row.status == Take.STATUS_DONE and not paid:
            # lost → done действием «Довезти»: выдано бесплатно, за наш счёт.
            self.redelivered += 1
        if row.needs_review:
            self.needs_review += 1
        if row.mode in REF_MODES:
            self.with_refs += 1
        if row.mode in FRAME_MODES:
            self.with_frames += 1

        self.chars_sum += row.chars
        self.words_sum += row.words
        self.chars_max = max(self.chars_max, row.chars)
        if row.soft:
            self.with_soft += 1
            self.over_soft += int(row.over_soft)
        self.script_like += int(row.script_like)
        if row.wait_s is not None:
            self.wait.append(row.wait_s)
        if row.render_s is not None:
            self.render.append(row.render_s)

        self.quoted += row.quoted
        self.charged += row.charged
        if paid and row.charged < row.reserved:
            # §5.3: денег не хватило (возврат платежа, ручная правка, гонка с
            # чатом) — списали «сколько было», разница за наш счёт.
            self.partial += 1
            self.partial_shortfall += row.reserved - row.charged

        if row.cost is not None:
            self.cost += row.cost
            self.cost_known += 1
            if not paid:
                # Провайдер взял деньги, а человек не заплатил: не получилось,
                # потеряно или довезено бесплатно.
                self.cost_unpaid += row.cost
            else:
                self.revenue_credits_costed += row.charged
                self.cost_costed += row.cost
                # То же правило, что проверка маржи при выдаче (§5.1).
                if credit_usd and row.charged * credit_usd * (1 - min_margin) < float(row.cost):
                    self.low_margin += 1
        elif paid:
            self.done_without_cost += 1

    def to_dict(self, credit_usd: float | None) -> dict:
        st = self.status
        done, failed, lost = st[Take.STATUS_DONE], st[Take.STATUS_FAILED], st[Take.STATUS_LOST]
        canceled = st[Take.STATUS_CANCELED]
        open_n = sum(st[s] for s in TAKE_OPEN)
        finished = done + failed + lost   # отмена в очереди — не исход генерации

        revenue_usd = margin_usd = margin_share = None
        if credit_usd:
            revenue_usd = self.charged * credit_usd
            margin_usd = revenue_usd - float(self.cost)
            margin_share = round(margin_usd / revenue_usd, 4) if revenue_usd > 0 else None
        # Маржа только по выдачам с известной себестоимостью: без неё «маржа»
        # у свежих дублей выглядела бы как 100%.
        costed_margin = None
        if credit_usd and self.revenue_credits_costed:
            rev = self.revenue_credits_costed * credit_usd
            costed_margin = round((rev - float(self.cost_costed)) / rev, 4) if rev > 0 else None

        return {
            "created": self.created,
            "done": done,
            "failed": failed,
            "canceled": canceled,
            "lost": lost,
            "open": open_n,
            "redelivered": self.redelivered,
            "statuses": {key: st[key] for key, _ in Take.STATUS_CHOICES},
            "failed_by_code": dict(self.failed_codes.most_common()),
            "lost_by_code": dict(self.lost_codes.most_common()),
            "needs_review": self.needs_review,
            "success_rate": _share(done, finished),
            "with_refs": self.with_refs,
            "with_frames": self.with_frames,
            "share_refs": _share(self.with_refs, self.created),
            "share_frames": _share(self.with_frames, self.created),
            "modes": {k: v for k, v in self.modes.most_common() if k},
            "prompt": {
                "chars_avg": round(self.chars_sum / self.created, 1) if self.created else None,
                "words_avg": round(self.words_sum / self.created, 1) if self.created else None,
                "chars_max": self.chars_max,
                "with_soft_limit": self.with_soft,
                "over_soft": self.over_soft,
                "share_over_soft": _share(self.over_soft, self.with_soft),
                "script_like": self.script_like,
            },
            "condense": self.condense,
            "condense_accepted": self.condense_accepted,
            "wait_s": _seconds(self.wait),
            "render_s": _seconds(self.render),
            "credits": {"quoted": self.quoted, "charged": self.charged},
            "partial": self.partial,
            "partial_shortfall": self.partial_shortfall,
            "cost_usd": _usd(self.cost),
            "cost_known": self.cost_known,
            "cost_unpaid_usd": _usd(self.cost_unpaid),
            "done_without_cost": self.done_without_cost,
            "revenue_usd": _usd(revenue_usd) if revenue_usd is not None else None,
            "margin_usd": _usd(margin_usd) if margin_usd is not None else None,
            "margin_share": margin_share,
            "margin_share_costed": costed_margin,
            "low_margin": self.low_margin if credit_usd else None,
        }


def _period(days: int, now) -> tuple[dt.datetime, list[str]]:
    """Начало периода (полночь по времени сайта) и все даты периода по порядку."""
    today = timezone.localdate(now)
    first = today - dt.timedelta(days=days - 1)
    since = timezone.make_aware(dt.datetime.combine(first, dt.time.min))
    return since, [(first + dt.timedelta(days=i)).isoformat() for i in range(days)]


def _take_rows(since, model: str, kind: str):
    qs = Take.objects.filter(created_at__gte=since)
    if model:
        qs = qs.filter(model_ref=model)
    if kind:
        qs = qs.filter(kind=kind)
    # Промпт нужен целиком (слова), но по одному чанку за раз: за год это
    # тысячи текстов до 20 000 символов, держать их все в памяти незачем.
    return qs.order_by().values(
        "created_at", "kind", "model_ref", "mode", "status", "error_code", "charge_state",
        "credits_quoted", "credits_reserved", "credits_charged", "provider_cost_usd",
        "submitted_at", "finished_at", "warnings", "serialized_prompt",
        "genlog__needs_review", "genlog__provider_cost_usd",
    ).iterator(chunk_size=500)


def _condense_events(since, model: str, kind: str = ""):
    """Шаги vstudio_condense: {accepted} (+ model, если фронт его пришлёт).

    С фильтром по модели или виду берём только шаги с известной моделью: шаг
    без model отнести некуда, и лучше недосчитать, чем приписать чужое.
    """
    try:
        from payments.models import FunnelEvent
    except Exception:  # воронки нет — отчёт всё равно нужен
        return []
    rows = (FunnelEvent.objects.filter(name="vstudio_condense", created_at__gte=since)
            .order_by().values("created_at", "meta", "user_id", "device_key"))
    out = []
    for r in rows.iterator(chunk_size=1000):
        meta = r["meta"] if isinstance(r["meta"], dict) else {}
        ev_model = str(meta.get("model") or "")
        if model and ev_model != model:
            continue
        if kind and _model_kind(ev_model) != kind:
            continue
        out.append({"day": _local_date(r["created_at"]).isoformat(), "model": ev_model,
                    "accepted": meta.get("accepted") is True,
                    "who": f"u{r['user_id']}" if r["user_id"] else f"d{r['device_key']}"})
    return out


def _journal(since, model: str, kind: str) -> dict:
    """Сверка журнала с дублями: всё ли, что ушло провайдеру, привязано к дублю.

    orphans — записи без дубля (сбой между журналом и UPDATE дубля);
    open_but_take_closed — журнал ещё «в работе», а дубль закрыт: sweep (§6.5
    п. 7) должен был их привести к исходу, ненулевое число — повод смотреть.
    """
    from ai.models import GenerationLog

    qs = GenerationLog.objects.filter(source=GenerationLog.SOURCE_VSTUDIO, created_at__gte=since)
    if model:
        qs = qs.filter(model=model)
    if kind:
        qs = qs.filter(kind=kind)
    by_status = Counter({r["status"]: r["n"] for r in
                         qs.order_by().values("status").annotate(n=Count("id"))})
    return {
        "rows": sum(by_status.values()),
        "by_status": {key: by_status[key] for key, _ in GenerationLog.STATUS_CHOICES},
        "needs_review": qs.filter(needs_review=True).count(),
        "orphans": qs.filter(vstudio_take__isnull=True).count(),
        "open_but_take_closed": qs.filter(status__in=GenerationLog.OPEN_STATES,
                                          vstudio_take__status__in=TAKE_CLOSED).count(),
    }


def _model_names(refs) -> dict[str, str]:
    from ai.models import GPTModels

    names = {}
    for ref, name in GPTModels.objects.filter(openrouter_id__in=list(refs)).values_list(
            "openrouter_id", "name"):
        names.setdefault(ref, name)
    return names


def build_report(days: int = DEFAULT_DAYS, *, model: str = "", kind: str = "", now=None) -> dict:
    """Отчёт за последние days дней (включая сегодня) по дням и моделям.

    model — точный openrouter_id, kind — video|image; пусто — все.
    """
    days = parse_days(days)
    model = (model or "").strip()
    kind = (kind or "").strip()
    if kind and kind not in KINDS:
        raise ValueError(f"kind: {kind}")
    now = now or timezone.now()
    since, dates = _period(days, now)
    credit_usd = _credit_usd()
    min_margin = _min_margin()

    total = _Bucket()
    by_day = {d: _Bucket() for d in dates}
    by_model: dict[str, _Bucket] = {}
    model_kind: dict[str, str] = {}
    by_cell: dict[tuple[str, str], _Bucket] = {}
    soft_cache: dict[str, int | None] = {}

    for raw in _take_rows(since, model, kind):
        ref = raw["model_ref"] or ""
        if ref not in soft_cache:
            soft_cache[ref] = _soft_words(ref)
        row = _Row(raw, soft_cache[ref])
        model_kind.setdefault(ref, row.kind)
        for bucket in (total,
                       by_day.setdefault(row.day, _Bucket()),
                       by_model.setdefault(ref, _Bucket()),
                       by_cell.setdefault((row.day, ref), _Bucket())):
            bucket.add(row, credit_usd, min_margin)

    # «Сжать с ИИ»: по дням всегда; по моделям — только если шаг несёт model.
    condense = _condense_events(since, model, kind)
    condense_users = set()
    condense_models = Counter()
    for ev in condense:
        condense_users.add(ev["who"])
        targets = [total, by_day.setdefault(ev["day"], _Bucket())]
        if ev["model"]:
            condense_models[ev["model"]] += 1
            if ev["model"] in by_model:
                targets.append(by_model[ev["model"]])
        for bucket in targets:
            bucket.condense += 1
            bucket.condense_accepted += int(ev["accepted"])

    names = _model_names(by_model.keys())

    def model_meta(ref: str) -> dict:
        return {"model": ref, "name": names.get(ref, ref), "kind": model_kind.get(ref, ""),
                "soft_words": soft_cache.get(ref)}

    models_sorted = sorted(by_model, key=lambda ref: (-by_model[ref].created, ref))
    totals = total.to_dict(credit_usd)
    totals["condense_users"] = len(condense_users)
    totals["condense_without_model"] = sum(1 for ev in condense if not ev["model"])
    return {
        "days": days,
        "since": since.isoformat(),
        "until": now.isoformat(),
        "timezone": settings.TIME_ZONE,
        "filters": {"model": model, "kind": kind},
        "credit_usd": round(credit_usd, 6) if credit_usd else None,
        "min_margin": round(min_margin, 4),
        "totals": totals,
        "by_day": [{"date": d, **by_day[d].to_dict(credit_usd)} for d in sorted(by_day)],
        "by_model": [{**model_meta(ref), **by_model[ref].to_dict(credit_usd)}
                     for ref in models_sorted],
        "by_day_model": [{"date": day, **model_meta(ref), **by_cell[(day, ref)].to_dict(credit_usd)}
                         for day, ref in sorted(by_cell)],
        "condense_by_model": dict(condense_models.most_common()),
        "journal": _journal(since, model, kind),
        "labels": {
            "status": {key: str(label) for key, label in Take.STATUS_CHOICES},
            "mode": {key: str(label) for key, label in Take.MODE_CHOICES},
            "kind": {key: str(label) for key, label in Take.KIND_CHOICES},
        },
    }
