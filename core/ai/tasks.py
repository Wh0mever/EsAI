from __future__ import annotations

# Music and image generation Celery tasks were removed for the text-only ESAI build.
# This module is intentionally kept so existing imports of `core.celery.app` and
# Celery autodiscovery remain valid.

import logging
import math

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from core.celery import app  # noqa: F401

logger = logging.getLogger(__name__)


# === Rolling-резюме контекста диалога ====================================
#
# Цель: пользователь может вести очень длинные чаты (сотни/тысячи сообщений),
# а модель не теряет важные факты, принятые решения и общий контекст — при этом
# без заметного роста стоимости и времени ответа.
#
# Как: в модель уходит [system] + [резюме старой части] + [свежие сообщения по
# токен-бюджету] (см. ai.handlers._build_openai_messages). Эта фоновая задача
# инкрементально сворачивает в резюме то, что вышло за «свежее окно». Запускается
# ПОСЛЕ ответа (как extract_user_memory) → на скорость ответа не влияет; считает
# дешёвой моделью (CONTEXT_SUMMARY_MODEL) → стоимость незаметна, а на длинных
# чатах запрос даже дешевле (вместо сотни сообщений — компактное резюме).

_SUMMARY_SYSTEM = (
    "Ты — модуль сжатия контекста диалога. Тебе дают ТЕКУЩЕЕ резюме (может быть "
    "пустым) и НОВЫЕ сообщения, которые выходят из активного окна диалога. "
    "Верни ОБНОВЛЁННОЕ резюме, в котором СОХРАНЕНЫ все важные ФАКТЫ, ПРИНЯТЫЕ "
    "РЕШЕНИЯ, договорённости, имена, числа, требования, термины и общий контекст. "
    "Опускай болтовню, приветствия, повторы и сиюминутные детали. Пиши кратко и "
    "по делу, тезисами, НА ЯЗЫКЕ ДИАЛОГА. Ничего не выдумывай. Не добавляй "
    "пояснений о том, что это резюме. Верни ТОЛЬКО текст обновлённого резюме, "
    "уложись примерно в {limit} символов."
)

_SUMMARY_LOCK = "ai:summary:lock:{sid}"
# Каждое сообщение в payload суммаризации обрезаем, чтобы вход оставался дешёвым.
_PER_MESSAGE_CHARS = 1500


def _select_recent_window_rows(rows, budget):
    """Свежие сообщения, влезающие в token-бюджет (от новых к старым). Всегда ≥1.

    Должна совпадать по логике с ai.handlers._select_recent_window, чтобы задача и
    сборщик контекста одинаково определяли границу «свежего окна».
    """
    kept = []
    used = 0
    for m in reversed(rows):
        t = max(1, math.ceil(len((m.content or "")) / 3))
        if kept and used + t > budget:
            break
        kept.append(m)
        used += t
    kept.reverse()
    return kept


def _render_messages(rows) -> str:
    lines = []
    for m in rows:
        role = "Пользователь" if m.role == "user" else ("Ассистент" if m.role == "assistant" else m.role)
        text = (m.content or "").strip()
        if not text:
            continue
        lines.append(f"{role}: {text[:_PER_MESSAGE_CHARS]}")
    return "\n".join(lines)


@shared_task(name="ai.tasks.summarize_session_context")
def summarize_session_context(session_id: int) -> dict:
    """Инкрементально свернуть «состарившуюся» часть диалога в context_summary.

    Полностью в try/except: задача никогда не должна ронять воркер или влиять на
    чат. Идемпотентна и защищена per-session локом от гонок.
    """
    try:
        if not getattr(settings, "CONTEXT_SUMMARY_ENABLED", True):
            return {"status": "disabled"}

        from .models import AiChatSession

        lock_key = _SUMMARY_LOCK.format(sid=session_id)
        if not cache.add(lock_key, "1", timeout=120):
            return {"status": "busy"}
        try:
            session = AiChatSession.objects.filter(id=session_id).first()
            if not session:
                return {"status": "no_session"}

            budget = int(getattr(settings, "CONTEXT_HISTORY_TOKEN_BUDGET", 8000) or 8000)
            max_chars = int(getattr(settings, "CONTEXT_SUMMARY_MAX_CHARS", 4000) or 4000)

            upto = session.summary_upto_message_id or 0
            # Несвёрнутый «хвост» (id > upto). Сворачиваем, только когда он перерос
            # бюджет окна: самые старые сообщения хвоста уходят в резюме, а в
            # дословном окне остаётся ровно бюджет (см. _build_openai_messages).
            # Хвост ограничен CONTEXT_SUMMARY_MAX_TAIL_ROWS (берём самые СТАРЫЕ —
            # ascending order + срез), иначе при отставании задачи он мог бы расти
            # без предела и разово выжечь контекстное окно модели суммаризации;
            # при большом backlog он рассасывается за несколько прогонов подряд.
            max_tail_rows = int(getattr(settings, "CONTEXT_SUMMARY_MAX_TAIL_ROWS", 500) or 500)
            tail = list(
                session.messages.only("id", "role", "content", "created_at")
                .filter(id__gt=upto).order_by("created_at")[:max_tail_rows]
            )
            kept = _select_recent_window_rows(tail, budget)
            new_old = tail[: len(tail) - len(kept)]
            if not new_old:
                return {"status": "nothing_new", "tail": len(tail)}

            from ai.handlers import _make_openai_client

            model_name = getattr(settings, "CONTEXT_SUMMARY_MODEL", "google/gemini-2.5-flash")
            client = _make_openai_client()

            existing = (session.context_summary or "").strip()
            payload = (
                f"ТЕКУЩЕЕ РЕЗЮМЕ (может быть пустым):\n{existing or '(пусто)'}\n\n"
                f"НОВЫЕ СООБЩЕНИЯ, которые нужно влить в резюме:\n{_render_messages(new_old)}"
            )

            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM.format(limit=max_chars)},
                    {"role": "user", "content": payload},
                ],
                temperature=0,
                max_tokens=1200,
            )
            try:
                updated = (completion.choices[0].message.content or "").strip()
            except Exception:
                updated = ""

            if not updated:
                return {"status": "empty_result"}

            # Граница берётся как max(id), а не new_old[-1].id: устойчиво к
            # совпадающим created_at (порядок по времени мог бы не совпасть с id).
            boundary = max(m.id for m in new_old)
            session.context_summary = updated[:max_chars]
            session.summary_upto_message_id = boundary
            session.save(update_fields=["context_summary", "summary_upto_message_id", "updated_at"])

            logger.info(
                "summarize_session_context session=%s folded=%s upto=%s len=%s",
                session_id, len(new_old), boundary, len(session.context_summary),
            )
            return {"status": "ok", "folded": len(new_old), "summary_len": len(session.context_summary)}
        finally:
            cache.delete(lock_key)
    except Exception as exc:  # noqa: BLE001 — суммаризация не должна падать
        logger.warning("summarize_session_context failed session=%s: %s", session_id, exc)
        return {"status": "error", "error": str(exc)}


@shared_task(name="ai.tasks.openrouter_autoswitch")
def openrouter_autoswitch() -> dict:
    """Обновить балансы аккаунтов OpenRouter и включить запасной, если пора.

    Зачем. На единственном ключе кончались деньги, и сайт вставал целиком, пока
    человек не заметит и не пополнит. Теперь, если у рабочего аккаунта остаток
    упал ниже порога, а запасной с деньгами есть, система переключается сама.

    Переключаемся только на аккаунты, помеченные запасными: молча увести
    расходы на чужой ключ, который завели «на потом», нельзя. Ручной выбор
    рабочего аккаунта это не отменяет — он просто станет отправной точкой для
    следующего автопереключения.
    """
    from django.utils import timezone as _tz

    from adminapi.openrouter import refresh
    from adminapi.runtime import get_runtime

    from .models import OpenRouterAccount

    accounts = list(OpenRouterAccount.objects.all())
    if not accounts:
        return {"status": "no_accounts"}
    for a in accounts:
        refresh(a)

    try:
        floor = float(get_runtime("openrouter_auto_switch_below", 2) or 0)
    except (TypeError, ValueError):
        floor = 2.0

    active = next((a for a in accounts if a.is_active), None)
    if not active:
        return {"status": "no_active"}
    # Ошибка ключа — тоже повод уйти на запасной: аккаунт мог быть отключён.
    drained = active.last_error or (active.balance_usd is not None
                                    and active.balance_usd <= floor)
    if not drained:
        return {"status": "ok", "active": active.title, "balance": active.balance_usd}

    spare = [a for a in accounts
             if a.auto_switch and not a.is_active and not a.last_error
             and (a.balance_usd or 0) > floor]
    if not spare:
        logger.warning("OpenRouter: на «%s» осталось %s, запасного нет",
                       active.title, active.balance_usd)
        return {"status": "no_spare", "active": active.title,
                "balance": active.balance_usd}

    # Берём самый полный: переключаться дважды за час незачем.
    spare.sort(key=lambda a: a.balance_usd or 0, reverse=True)
    winner = spare[0]
    winner.is_active = True
    winner.auto_switched_at = _tz.now()
    winner.save(update_fields=["is_active", "auto_switched_at"])
    logger.warning("OpenRouter: переключился с «%s» ($%s) на «%s» ($%s)",
                   active.title, active.balance_usd, winner.title, winner.balance_usd)
    return {"status": "switched", "from": active.title, "to": winner.title,
            "balance": winner.balance_usd}


# === Долгие генерации из очереди (видео для бота) =========================

def _notify_job_result(job) -> None:
    """Прислать ролик в Telegram, если человек об этом просил.

    Шлём прямо отсюда, а не через очередь уведомлений: так мы точно знаем,
    дошло ли сообщение, и можем отметить это в задаче — бот по этой отметке
    понимает, что дублировать ролик не нужно.

    Отметка означает НАМЕРЕНИЕ отправить, а не факт доставки. Раньше она
    ставилась после ответа Telegram, а статус задачи становился done до вызова:
    бот, опросив задачу в этом промежутке, видел «ядро ничего не слало» и
    отправлял ролик сам — человек получал видео дважды. Теперь помечаем перед
    обращением к Telegram.

    Плата за это — бот больше не подстрахует: он возвращается, как только
    увидит отметку, то есть почти сразу, и снятая позже отметка его уже не
    догонит. Поэтому запасной путь у отправки ролика свой (ссылка сообщением),
    а отметка снимается только когда не прошло вообще ничего: тогда доставит
    бот, если ещё ждёт, и в логе останется след.
    """
    from django.utils import timezone

    if job.notify != "telegram":
        return
    marked = False
    try:
        from botapi.models import TelegramChat
        from botapi.tasks import _enabled
        from botapi.telegram import TelegramError, tg_api

        if not _enabled():
            return
        chat = TelegramChat.objects.filter(user_id=job.user_id, is_blocked=False).first()
        if not chat:
            return
        # С этой секунды доставка — наша ответственность, и бот про это знает.
        type(job).objects.filter(pk=job.pk).update(notified_at=timezone.now())
        marked = True
        result = job.result or {}
        lang = (job.params or {}).get("lang") or chat.lang or "ru"
        if job.status == job.STATUS_DONE:
            attachments = ((result.get("message") or {}).get("attachments") or [])
            video = next((a for a in attachments if a.get("type") == "video"), None)
            url = (video or {}).get("url") or ""
            base = (getattr(settings, "SITE_BASE_URL", "") or "https://esai.kg").rstrip("/")
            if url and not url.startswith("http"):
                url = base + url
            caption = {
                "en": "🎬 Your video is ready · −{c} cr · balance {b}",
                "kg": "🎬 Видеоңуз даяр · −{c} кр · баланс {b}",
            }.get(lang, "🎬 Видео готово · −{c} кр · баланс {b}").format(
                c=result.get("tokens_charged", 0), b=result.get("balance_tokens", "—"))
            markup = {"inline_keyboard": [[
                {"text": {"en": "⏩ Extend", "kg": "⏩ Узартуу"}.get(lang, "⏩ Продлить"),
                 "callback_data": f"v:ext:{job.uid}"},
                {"text": {"en": "🔁 Another", "kg": "🔁 Дагы"}.get(lang, "🔁 Ещё вариант"),
                 "callback_data": f"v:re:{job.uid}"},
            ], [
                {"text": {"en": "🔗 Share", "kg": "🔗 Бөлүшүү"}.get(lang, "🔗 Поделиться"),
                 "callback_data": f"v:sh:{job.uid}"},
            ]]}
            if url:
                try:
                    tg_api("sendVideo", chat_id=chat.chat_id, video=url, caption=caption,
                           supports_streaming=True, reply_markup=markup)
                except TelegramError as exc:
                    if exc.blocked:
                        raise  # писать больше некому — снимаем отметку выше
                    # Ролик Telegram не взял: по ссылке он тянет не больше
                    # 20 МБ и рвёт долгую закачку (наш таймаут — 30 секунд).
                    # Раньше подстраховкой был бот, но теперь он уходит, едва
                    # увидев отметку, а она стоит с начала отправки — снятая
                    # позже, она его уже не догонит. Поэтому запасной путь
                    # делаем сами и тем же способом, что бот в deliver():
                    # отдаём ссылку сообщением. Если ролик всё-таки дошёл
                    # (обрыв по таймауту), человек увидит лишнюю ссылку — это
                    # дешевле, чем оплаченное видео, которое не пришло совсем.
                    logger.warning("job %s: sendVideo отказал (%s) — шлём ссылку",
                                   job.uid, exc.description)
                    tg_api("sendMessage", chat_id=chat.chat_id,
                           text=f"{caption}\n{url}", reply_markup=markup)
            else:
                tg_api("sendMessage", chat_id=chat.chat_id, text=caption, reply_markup=markup)
        else:
            text = {
                "en": "😕 The video did not come out. No credits were charged.",
                "kg": "😕 Видео чыккан жок. Кредиттер алынган жок.",
            }.get(lang, "😕 Видео не получилось. Кредиты не списаны.")
            tg_api("sendMessage", chat_id=chat.chat_id, text=text, reply_markup={
                "inline_keyboard": [[{"text": {"en": "🔁 Retry", "kg": "🔁 Кайра"}.get(lang, "🔁 Повторить"),
                                      "callback_data": f"v:re:{job.uid}"}]]})
    except TelegramError as exc:
        if marked:
            type(job).objects.filter(pk=job.pk).update(notified_at=None)
        logger.warning("job %s: telegram отказал: %s", job.uid, exc.description)
    except Exception:
        if marked:
            type(job).objects.filter(pk=job.pk).update(notified_at=None)
        logger.exception("job %s: уведомление не ушло", job.uid)


@shared_task(bind=True, name="ai.tasks.run_generation_job", max_retries=0,
             soft_time_limit=840, time_limit=900)
def run_generation_job(self, job_id: int) -> dict:
    """Выполнить задачу генерации тем же кодом, что и чат.

    Слот дневного лимита зарезервирован при постановке; при любой неудаче
    generation.py возвращает его сам, как и в потоке чата.
    """
    from django.utils import timezone

    from .generation import run_video_generation
    from .handlers import _release_daily_request, _resolve_gpt_model
    from .models import GenerationJob
    from .views_media import _cancel_key

    job = GenerationJob.objects.filter(pk=job_id).select_related("user", "session").first()
    if not job:
        return {"status": "no_job"}
    if job.status != GenerationJob.STATUS_QUEUED:
        return {"status": job.status}

    job.status = GenerationJob.STATUS_RUNNING
    job.started_at = timezone.now()
    job.progress = "starting"
    job.progress_at = job.started_at
    job.save(update_fields=["status", "started_at", "progress", "progress_at"])

    params = job.params or {}
    user = job.user
    model_obj = _resolve_gpt_model(params.get("model"))
    if not model_obj:
        model_obj = _resolve_gpt_model(params.get("model_pk"))
    if not model_obj or not job.session:
        _release_daily_request(user)
        job.status = GenerationJob.STATUS_FAILED
        job.error = "model_or_session_missing"
        job.error_code = "bad_model"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "error_code", "finished_at"])
        return {"status": "failed"}

    def canceled() -> bool:
        return bool(cache.get(_cancel_key(job.uid)))

    final: dict = {}
    error: dict = {}
    try:
        frames = run_video_generation(
            user=user, model_obj=model_obj,
            selected_model_name=str(params.get("model") or model_obj.openrouter_id or model_obj.name),
            message=str(params.get("message") or ""),
            attachments=params.get("attachments"),
            origin_base=params.get("origin_base"),
            session=job.session,
            want_duration=params.get("video_duration"),
            want_resolution=params.get("video_resolution"),
            aspect_ratio=params.get("aspect_ratio"),
            first_frame=params.get("video_first_frame"),
            last_frame=params.get("video_last_frame"),
            extend_video=params.get("extend_video_url"),
            cancel_check=canceled,
        )
        for frame in frames:
            if frame.get("error"):
                error = frame
                break
            if frame.get("done"):
                final = frame
                break
            progress = frame.get("video_progress") or ("pending" if frame.get("video_pending") else "")
            if progress and progress != job.progress:
                job.progress = str(progress)[:32]
                GenerationJob.objects.filter(pk=job.pk).update(
                    progress=job.progress, progress_at=timezone.now())
    except Exception as exc:  # noqa: BLE001 — задача не должна падать молча
        logger.exception("job %s: генерация упала", job.uid)
        _release_daily_request(user)
        error = {"error": "internal_error", "error_code": "internal_error", "detail": str(exc)[:200]}

    job.finished_at = timezone.now()
    if final:
        job.status = GenerationJob.STATUS_DONE
        job.progress = "done"
        job.tokens_charged = int(final.get("tokens_charged") or 0)
        job.result = {
            "message": final.get("message"),
            "tokens_charged": final.get("tokens_charged"),
            "balance_tokens": final.get("balance_tokens"),
            "session": final.get("session"),
        }
        message_id = (final.get("message") or {}).get("id")
        if message_id:
            job.result_message_id = message_id
        job.save(update_fields=["status", "progress", "tokens_charged", "result",
                                "result_message", "finished_at"])
    else:
        code = str(error.get("error_code") or "failed")
        job.status = (GenerationJob.STATUS_CANCELED if code == "canceled"
                      else GenerationJob.STATUS_FAILED)
        job.error = str(error.get("error") or "failed")[:500]
        job.error_code = code[:40]
        job.result = {k: v for k, v in error.items() if k in ("balance_tokens", "required_estimate")}
        job.save(update_fields=["status", "error", "error_code", "result", "finished_at"])

    if job.status != GenerationJob.STATUS_CANCELED:
        _notify_job_result(job)
    return {"status": job.status}
