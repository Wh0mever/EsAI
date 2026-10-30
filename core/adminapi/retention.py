"""GET /api/manage/retention/?days=30|90 — «Возвраты»: возвращаются ли люди (F29).

Всё считается по audit.UserActivityDay (одна строка = человек был на сайте в
этот местный день Бишкека) одним проходом в Python: людей ~2.5 тыс., строк —
десятки тысяч, а окна, «вернулись за N дней» и когорты в SQL вылились бы в
десяток тяжёлых запросов с той же логикой, только хуже читаемой.

Кого не считаем: сотрудников и тестовый аккаунт платёжки — их заходы есть в
таблице, но к возвратам живых людей отношения не имеют.

Блок «По направлениям» (F30) — тем же проходом в Python, источник — журнал
кредитов plans.TokenTransaction: списание = успешная генерация, а журнал генераций
ai.GenerationLog есть только с сентября.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Count, Min, Q
from django.utils import timezone
from rest_framework.response import Response

from ai.handlers import _is_any_image_model
from ai.models import AiChatMessage
from audit.activity import day_start, local_day, local_tz, sync_recent
from audit.models import ActivitySource, UserActivityDay
from payments.models import Payment
from plans.models import TokenTransaction

from .views import StaffAPIView

User = get_user_model()

ALLOWED_DAYS = (30, 90)
DEFAULT_DAYS = 30
CACHE_TTL = 300
CACHE_KEY = "adminapi:retention:{days}"
RETURNED_WITHIN = (1, 7, 30)
COHORT_WEEKS = 12
COHORT_K = 8
STICKINESS_DAYS = 30

# С этого дня журнал кредитов = успешные генерации. Подпись на странице говорит
# то же самое (retention.ts, DIRECTIONS_NOTE).
DIRECTIONS_SINCE = date(2026, 6, 28)
# Строки отчёта «По направлениям» в порядке показа: (группа, подпись, сценарии).
DIRECTIONS = (
    ("video", "Видео", (("cartoon_scene", "Мультстудия"), ("vstudio_video", "Видеостудия"),
                        ("chat_video", "Чат"))),
    ("image", "Изображения", (("cartoon_image", "Мультстудия"), ("vstudio_image", "Видеостудия"),
                              ("chat_image", "Чат"))),
    # Сценарий один: подстрока только повторила бы строку группы.
    ("text", "Текст", (("text", "Чат"),)),
)
# Причины списания, у которых сценарий ясен сразу. Чат разбирается отдельно (_chat_scenario).
SCENARIO_BY_REASON = {
    "cartoon_scene": "cartoon_scene",
    "cartoon_keyframe": "cartoon_image",
    "cartoon_character": "cartoon_image",
    "vstudio_video": "vstudio_video",
    "vstudio_image": "vstudio_image",
}
CHAT_REASON = "chat"
MESSAGES_CHUNK = 2000


def _now():
    """Текущий момент. Отдельной функцией, чтобы тесты могли зафиксировать «сегодня»."""
    return timezone.now()


def _one_decimal(value: Fraction) -> float:
    """Один знак после запятой «как в таблице» (81,25 → 81,3).

    round() у float округляет к чётному, и плитка расходилась бы с пересчётом руками.
    """
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return float(exact.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _share(part, whole):
    """Доля в процентах с одним знаком; None, когда считать не из чего."""
    if not whole:
        return None
    return _one_decimal(Fraction(part) * 100 / Fraction(whole))


def _has_day(days: list[date], start: date, end: date) -> bool:
    """Есть ли в отсортированном списке дней хоть один в [start, end]."""
    i = bisect_left(days, start)
    return i < len(days) and days[i] <= end


def _counted_users() -> dict[int, date]:
    """{id: местный день регистрации} — без сотрудников, тестового аккаунта и отключённых.

    is_active=False — заблокированные фермы одноразовых почт и заглушки Telegram,
    слитые с аккаунтом сайта (человек тогда считался бы дважды). Удалить аккаунт
    сам человек не может, так что живых людей этот фильтр не теряет.
    """
    qs = User.objects.filter(is_staff=False, is_superuser=False, is_active=True)
    test_email = (getattr(settings, "TEST_LOGIN_EMAIL", "") or "").strip()
    if test_email:
        qs = qs.exclude(email__iexact=test_email)
    tz = local_tz()
    return {uid: timezone.localtime(joined, tz).date()
            for uid, joined in qs.order_by().values_list("id", "date_joined")}


def _activity_by_user(joined: dict[int, date]) -> dict[int, list[date]]:
    """{id: отсортированные дни активности} только для учитываемых людей.

    Дни раньше регистрации отбрасываем: такая строка может взяться лишь из
    кривых данных, а с ней человек оказался бы «активным, но не новым и не
    вернувшимся» и разошлись бы плитки и график.
    """
    by_user: dict[int, list[date]] = defaultdict(list)
    rows = UserActivityDay.objects.order_by().values_list("user_id", "day")
    for uid, day in rows.iterator(chunk_size=5000):
        joined_day = joined.get(uid)
        if joined_day is None or day < joined_day:
            continue
        by_user[uid].append(day)
    for days in by_user.values():
        days.sort()
    return by_user


def _cohorts(joined, by_user, today):
    """Недельные когорты регистрации: доля вернувшихся в k-ю неделю после регистрации.

    Неделя k считается от дня регистрации каждого человека, а не по календарю:
    иначе пришедший в воскресенье «отработал бы» первую неделю за один день.
    """
    current_week = today - timedelta(days=today.weekday())
    oldest_week = current_week - timedelta(weeks=COHORT_WEEKS - 1)
    members: dict[date, list[int]] = defaultdict(list)
    for uid, joined_day in joined.items():
        week = joined_day - timedelta(days=joined_day.weekday())
        if oldest_week <= week <= current_week:
            members[week].append(uid)

    cohorts = []
    for i in range(COHORT_WEEKS):
        week = current_week - timedelta(weeks=i)
        ids = members.get(week, [])
        weeks = []
        for k in range(1, COHORT_K + 1):
            eligible = returned = 0
            for uid in ids:
                end = joined[uid] + timedelta(days=7 * k)
                # Ячейку считаем только по тем, у кого k-я неделя уже целиком
                # прошла: недоигранная неделя занизила бы долю.
                if end > today:
                    continue
                eligible += 1
                if _has_day(by_user.get(uid, []), end - timedelta(days=6), end):
                    returned += 1
            weeks.append({"k": k, "share": _share(returned, eligible),
                          "eligible": eligible, "returned": returned})
        cohorts.append({"week_start": week.isoformat(), "size": len(ids), "weeks": weeks})
    return cohorts


def _paid_by_user(joined) -> dict[int, int]:
    """{id: сколько раз заплатил} — успешные не тестовые оплаты учитываемых людей."""
    # order_by() обязателен: сортировка модели попала бы в GROUP BY и разбила
    # бы одного плательщика на несколько строк.
    rows = (Payment.objects.filter(success=True, is_test=False, user__isnull=False)
            .order_by().values_list("user_id").annotate(n=Count("id")))
    return {uid: n for uid, n in rows if uid in joined}


def _payers(paid: dict[int, int]) -> dict:
    """Платившие хоть раз и платившие 2+ раза (без тестовых оплат)."""
    repeat = sum(1 for n in paid.values() if n >= 2)
    return {"paying": len(paid), "repeat": repeat, "repeat_share": _share(repeat, len(paid))}


def _chat_scenario(meta: dict) -> str | None:
    """Сценарий списания чата; None — по строке журнала не понять, смотреть сообщение.

    Флаги image и video есть в журнале не всегда. Nano Banana и другие модели,
    рисующие через обычный чат, списываются той же веткой, что и текст, без флага
    (ai.handlers, «Списание + сохранение»), поэтому «нет флага = текст» отдало бы все
    их картинки тексту. Главный признак здесь — модель: без готовой картинки такая
    модель с 25.08.2026 не списывает ничего (_image_expected_missed; раньше списывала,
    и подпись на странице это оговаривает), а id модели лежит в самой строке журнала.
    Флаг у сообщения не подошёл бы: он появился только этой осенью,
    а сообщения исчезают, когда человек чистит историю.

    У частичного списания (не хватило баланса) нет ни флага, ни модели — только
    message_id, отсюда None.
    """
    if meta.get("video"):
        return "chat_video"
    if meta.get("image"):
        return "chat_image"
    model = meta.get("openrouter_id") or meta.get("model")
    if not model:
        return None
    return "chat_image" if _is_any_image_model(model) else "text"


def _message_media(ids: set[int]) -> dict[int, str]:
    """{id сообщения: сценарий} для тех из ids, где чат выдал картинку или ролик.

    Кроме флагов смотрим вложения: у старых картинок флага в сообщении нет.
    """
    found: dict[int, str] = {}
    ordered = sorted(ids)
    for start in range(0, len(ordered), MESSAGES_CHUNK):
        rows = (AiChatMessage.objects.filter(pk__in=ordered[start:start + MESSAGES_CHUNK])
                .order_by().values_list("id", "meta", "attachments"))
        for pk, meta, attachments in rows:
            flags = meta if isinstance(meta, dict) else {}
            files = attachments if isinstance(attachments, list) else []
            kinds = {item.get("type") for item in files if isinstance(item, dict)}
            if flags.get("video") or "video" in kinds:
                found[pk] = "chat_video"
            elif flags.get("image") or "image" in kinds:
                found[pk] = "chat_image"
    return found


def _generations(joined) -> dict[str, dict[int, Counter]]:
    """{сценарий: {id: {местный день: сколько генераций}}} из журнала кредитов.

    Одна строка со списанием — одна генерация: частичная строка пишется вместо
    полной, а не вместе с ней. Нулевые строки (модель не отдала картинку) сюда
    не попадают: delta < 0.
    """
    spent: dict[str, dict[int, Counter]] = defaultdict(lambda: defaultdict(Counter))
    undecided = []
    tz = local_tz()
    rows = (TokenTransaction.objects
            .filter(delta__lt=0, reason__in=(CHAT_REASON, *SCENARIO_BY_REASON),
                    created_at__gte=day_start(DIRECTIONS_SINCE))
            .order_by().values_list("user_id", "reason", "created_at", "meta"))
    for uid, reason, created_at, meta in rows.iterator(chunk_size=5000):
        if uid not in joined:
            continue
        day = timezone.localtime(created_at, tz).date()
        meta = meta if isinstance(meta, dict) else {}
        scenario = SCENARIO_BY_REASON.get(reason) or _chat_scenario(meta)
        if scenario:
            spent[scenario][uid][day] += 1
        else:
            undecided.append((uid, day, meta.get("message_id")))

    # Таких строк единицы, поэтому сообщения поднимаем только для них, а не весь чат.
    # Сообщения нет (чат удалён) — считаем текстом: больше о строке ничего не известно.
    media = _message_media({mid for _, _, mid in undecided if mid})
    for uid, day, mid in undecided:
        spent[media.get(mid, "text")][uid][day] += 1
    return spent


def _direction_stats(people, by_user, paid, today, window_start) -> dict:
    """Цифры одной строки «По направлениям»; people — {id: {день: сколько генераций}}."""
    generations = generations_period = active_period = repeat = paying = 0
    # По окну N: [база, вернулись к направлению, вернулись на сайт].
    windows = {n: [0, 0, 0] for n in RETURNED_WITHIN}
    for uid, per_day in people.items():
        days = sorted(per_day)
        in_period = sum(n for day, n in per_day.items() if window_start <= day <= today)
        generations += sum(per_day.values())
        generations_period += in_period
        active_period += 1 if in_period else 0
        # Два раза за один день — один заход, а не привычка: считаем разные дни.
        repeat += 1 if len(days) >= 2 else 0
        paying += 1 if uid in paid else 0
        activity = by_user.get(uid, [])
        for n, tally in windows.items():
            # База — только те, у кого все N дней после первой генерации уже прошли.
            if days[0] > today - timedelta(days=n):
                continue
            start, end = days[0] + timedelta(days=1), days[0] + timedelta(days=n)
            tally[0] += 1
            tally[1] += 1 if _has_day(days, start, end) else 0
            tally[2] += 1 if _has_day(activity, start, end) else 0

    def returned(column: int) -> list[dict]:
        return [{"days": n, "base": tally[0], "returned": tally[column],
                 "share": _share(tally[column], tally[0])} for n, tally in windows.items()]

    users = len(people)
    return {
        "users": users,
        "generations": generations,
        "per_user": _one_decimal(Fraction(generations, users)) if users else None,
        "repeat": repeat,
        "repeat_share": _share(repeat, users),
        "returned_direction": returned(1),
        "returned_site": returned(2),
        "paid": paying,
        "paid_share": _share(paying, users),
        "active_period": active_period,
        "generations_period": generations_period,
    }


def _directions(joined, by_user, paid, today, window_start) -> list[dict]:
    """Строки блока «По направлениям»: группа, под ней её сценарии.

    Группа — объединение дней сценариев, а не сумма строк: мультфильм в понедельник
    и ролик в студии во вторник — повтор «Видео», хотя в каждом сценарии это один день.
    """
    spent = _generations(joined)

    def stats(people) -> dict:
        return _direction_stats(people, by_user, paid, today, window_start)

    rows = []
    for group, group_label, scenarios in DIRECTIONS:
        merged: dict[int, Counter] = defaultdict(Counter)
        for key, _ in scenarios:
            for uid, per_day in spent[key].items():
                merged[uid].update(per_day)
        rows.append({"key": group, "group": group, "label": group_label, "parent": None,
                     **stats(merged)})
        if len(scenarios) > 1:
            rows.extend({"key": key, "group": group, "label": label, "parent": group,
                         **stats(spent[key])} for key, label in scenarios)
    return rows


def retention_report(days: int = DEFAULT_DAYS, now=None) -> dict:
    """Отчёт «Возвраты» за окно days (30 или 90) по состоянию на now."""
    now = now or _now()
    today = local_day(now)
    joined = _counted_users()
    by_user = _activity_by_user(joined)

    def active_between(start: date, end: date) -> int:
        return sum(1 for ds in by_user.values() if _has_day(ds, start, end))

    window_start = today - timedelta(days=days - 1)

    # По дням: и для графика (окно days), и для среднего DAU стикинесса (30 дней).
    per_day_from = min(window_start, today - timedelta(days=STICKINESS_DAYS - 1))
    per_day_active: Counter = Counter()
    per_day_new: Counter = Counter()
    returning = returned_ever = 0
    for uid, ds in by_user.items():
        joined_day = joined[uid]
        if ds[-1] > joined_day:
            returned_ever += 1
        # Вернувшийся за период: был в окне в день ПОЗЖЕ дня своей регистрации.
        if _has_day(ds, max(window_start, joined_day + timedelta(days=1)), today):
            returning += 1
        for d in ds[bisect_left(ds, per_day_from):]:
            if d > today:
                break
            per_day_active[d] += 1
            if d == joined_day:
                per_day_new[d] += 1

    daily = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        active_d, new_d = per_day_active[d], per_day_new[d]
        daily.append({"date": d.isoformat(), "active": active_d, "new": new_d,
                      "returning": active_d - new_d})

    mau = active_between(today - timedelta(days=29), today)
    avg_dau = Fraction(sum(per_day_active[today - timedelta(days=i)] for i in range(STICKINESS_DAYS)),
                       STICKINESS_DAYS)
    active = active_between(window_start, today)

    returned_within = []
    for n in RETURNED_WITHIN:
        # База — только те, у кого все N дней после регистрации уже прошли.
        base = [uid for uid, j in joined.items() if j <= today - timedelta(days=n)]
        returned = sum(1 for uid in base
                       if _has_day(by_user.get(uid, []), joined[uid] + timedelta(days=1),
                                   joined[uid] + timedelta(days=n)))
        returned_within.append({"days": n, "base": len(base), "returned": returned,
                                "share": _share(returned, len(base))})

    bounds = UserActivityDay.objects.aggregate(
        first=Min("day"), first_live=Min("day", filter=Q(source=ActivitySource.LIVE)))
    users_total = len(joined)
    paid = _paid_by_user(joined)

    return {
        "generated_at": timezone.localtime(now, local_tz()).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "days": days,
        "exact_since": bounds["first_live"].isoformat() if bounds["first_live"] else None,
        "history_since": bounds["first"].isoformat() if bounds["first"] else None,
        "users_total": users_total,
        "kpi": {
            "dau": active_between(today, today),
            "wau": active_between(today - timedelta(days=6), today),
            "mau": mau,
            "stickiness": _share(avg_dau, mau),
            "new": sum(1 for j in joined.values() if window_start <= j <= today),
            "active": active,
            "returning": returning,
            "returning_share": _share(returning, active),
            "returned_ever_share": _share(returned_ever, users_total),
            "returned_ever": returned_ever,
        },
        "returned_within": returned_within,
        "daily": daily,
        "cohorts": _cohorts(joined, by_user, today),
        "payers": _payers(paid),
        "directions": _directions(joined, by_user, paid, today, window_start),
    }


class RetentionView(StaffAPIView):
    """GET /api/manage/retention/?days=30|90 — метрики возвращающихся пользователей."""

    def get(self, request):
        try:
            days = int(request.query_params.get("days") or DEFAULT_DAYS)
        except (TypeError, ValueError):
            days = DEFAULT_DAYS
        if days not in ALLOWED_DAYS:
            days = DEFAULT_DAYS

        key = CACHE_KEY.format(days=days)
        data = cache.get(key)
        if data is None:
            # Дотягиваем последние дни из истории: так в отчёт попадает и то,
            # что человек делал мимо сайта (Telegram-бот), — middleware этого не видит.
            sync_recent()
            data = retention_report(days)
            cache.set(key, data, CACHE_TTL)
        return Response(data)
