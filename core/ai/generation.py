"""Генерация видео — общий код для чата и фоновой очереди.

Раньше эта ветка жила внутри SSE-генератора чата и держала gunicorn-воркер
до восьми минут: три ролика одновременно — и сайт стоит. Теперь тот же код
работает и из потока (сайт), и из Celery-задачи (бот): списание, meta и
сообщения ассистента остаются ровно теми же, поэтому деньги считаются в одном
месте.

Генератор отдаёт словари-кадры: video_pending, video_progress, error, done.
Поток чата оборачивает их в SSE, задача — пишет в GenerationJob.
"""
from __future__ import annotations

import logging
import math
from typing import Callable, Iterator

from django.conf import settings
from django.db import transaction

from plans.wallet import InsufficientTokens, charge_tokens

from .models import AiChatMessage
from .serializers import AiChatMessageSerializer

logger = logging.getLogger(__name__)

# Сколько ждём ответа на отправку. Провайдер до ответа сам скачивает
# приложенные картинки, и с тяжёлым фото это заметно дольше полуминуты.
SUBMIT_READ_TIMEOUT = 150


def run_video_generation(*, user, model_obj, selected_model_name: str, message: str,
                         attachments, origin_base: str | None, session,
                         want_duration: int | None = None,
                         want_resolution: str | None = None,
                         aspect_ratio: str | None = None,
                         first_frame: str | None = None,
                         last_frame: str | None = None,
                         extend_video: str | None = None,
                         cancel_check: Callable[[], bool] | None = None,
                         source: str = "chat", client_ip: str | None = None) -> Iterator[dict]:
    """Сгенерировать ролик и сохранить его как ответ ассистента.

    Списание — только за готовый файл: любая ошибка по пути возвращает слот
    дневного лимита и ничего не берёт с баланса.
    """
    from .handlers import (
        _openrouter_config,
        _openrouter_video_catalog,
        _read_own_media,
        _release_daily_request,
        _video_model_params,
    )

    import time as _time
    import uuid as _uuid
    import requests as _requests
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    cfg = _openrouter_config()
    # Подгоняем duration/resolution под КОНКРЕТНУЮ модель (иначе Veo/Hailuo
    # отбивают submit: 5с/720p им не подходят). need считаем по факту.
    # Длительность: что попросил пользователь, иначе дефолт из настроек.
    # _video_model_params всё равно примагнитит к поддерживаемому
    # моделью значению, поэтому произвольное число с фронта безопасно.
    _want_dur = want_duration or int(getattr(settings, "VIDEO_GEN_DURATION", 5) or 5)
    _want_res = want_resolution or str(
        getattr(settings, "VIDEO_GEN_RESOLUTION", "720p") or "720p"
    )
    _vp = _video_model_params(selected_model_name, cfg, _want_dur, _want_res)
    duration = int(_vp["duration"])
    resolution = str(_vp["resolution"])
    coeff = float(getattr(model_obj, "markup_coefficient", 1) or 1)
    need = max(1, math.ceil(duration * coeff))

    # a) Пред-чек баланса ТОЧНОЙ стоимостью (цена видео известна заранее).
    try:
        user.refresh_from_db(fields=["token_balance"])
    except Exception:
        pass
    bal = int(getattr(user, "token_balance", 0) or 0)
    if bal < need:
        _release_daily_request(user)
        yield ({
            "error": "Недостаточно кредитов для генерации видео.",
            "error_code": "insufficient_balance",
            "balance_tokens": bal,
            "required_estimate": need,
            "done": True,
        })
        return

    # Журнал генераций: с этой строки видно, кто, чем и что запустил — даже
    # если дальше всё оборвётся. Без неё оплаченный ролик терялся бесследно.
    from . import genlog

    entry = genlog.start(
        user=user, kind="video", model=selected_model_name, source=source,
        prompt=message, credits_planned=need, session=session, ip=client_ip,
        params={"duration": duration, "resolution": resolution,
                "aspect_ratio": aspect_ratio or "", "images": len(attachments or []),
                "extend": bool(extend_video)})

    # b) Фронт рисует видео-плейсхолдер (аналог image_pending).
    yield ({"video_pending": True, "duration": duration})

    # b.1) IMAGE-TO-VIDEO: если во вложениях есть картинка — берём ПЕРВУЮ
    #      и передаём её в submit как first_frame. URL картинки должен быть
    #      АБСОЛЮТНЫМ https (OpenRouter качает его сам). Форма строго:
    #      frame_images=[{type:"image_url", image_url:{url}, frame_type:"first_frame"}]
    #      (строка/input_references → 400 ZodError). Если абсолютный URL
    #      собрать не из чего (origin_base пуст) — тихо откатываемся на
    #      обычный text-to-video, не падаем.
    first_img = None
    first_img_abs_url = None
    try:
        for a in (attachments or []):
            if isinstance(a, dict) and a.get("type") == "image" and a.get("url"):
                first_img = a
                break
    except Exception:
        first_img = None
    if first_img:
        _u = str(first_img.get("url") or "")
        if _u.startswith("http"):
            first_img_abs_url = _u
        elif origin_base:
            first_img_abs_url = origin_base.rstrip("/") + _u
        # origin_base пуст и url относительный → abs_url остаётся None,
        # image-to-video пропускаем (обычный text-to-video).

    # b.1.1) Кадры, выбранные в панели параметров, важнее случайной
    #        картинки из вложений: пользователь указал их явно.
    last_img_abs_url = None
    def _abs(u: str | None) -> str | None:
        if not u:
            return None
        if u.startswith("http"):
            return u
        return (origin_base.rstrip("/") + u) if origin_base else None

    if first_frame:
        first_img_abs_url = _abs(first_frame) or first_img_abs_url
    if last_frame:
        last_img_abs_url = _abs(last_frame)

    # b.2) ПРОДЛЕНИЕ: исходный ролик → его последний кадр становится
    #      first_frame нового сегмента. Кадр перебивает картинку из
    #      вложений: при продлении важна именно склейка «встык».
    #      Если что-то пошло не так — не падаем, генерируем обычный
    #      ролик (пользователь получит видео, просто без стыковки).
    source_video_bytes = None
    if extend_video:
        try:
            from .video_edit import extract_last_frame

            source_video_bytes = _read_own_media(extend_video)
            if source_video_bytes:
                frame = extract_last_frame(source_video_bytes)
                if frame:
                    fpath = default_storage.save(
                        f"ai_frames/{_uuid.uuid4().hex}.jpg", ContentFile(frame)
                    )
                    furl = default_storage.url(fpath)
                    if furl.startswith("http"):
                        first_img_abs_url = furl
                    elif origin_base:
                        first_img_abs_url = origin_base.rstrip("/") + furl
                    else:
                        # Без абсолютного URL OpenRouter кадр не заберёт —
                        # склейка «встык» не получится, но сегмент снимем.
                        source_video_bytes = None
                else:
                    source_video_bytes = None
            else:
                logger.warning("extend: исходное видео не прочитано: %s", extend_video[:120])
        except Exception:
            logger.exception("extend: подготовка последнего кадра не удалась")
            source_video_bytes = None

    # c) Submit: POST /api/v1/videos → 202 {id, polling_url, status}.
    auth_headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    _submit_body = {
        "model": selected_model_name,
        "prompt": message,
        "duration": duration,
        "resolution": resolution,
    }
    # Пропорции: выбранные в панели либо названные словами в самом
    # запросе («вертикальное видео»). Сверяем с каталогом модели —
    # 21:9 умеет Seedance, но не умеет Veo, и неверное значение
    # отвергло бы весь запрос.
    try:
        from .aspect import resolve as _resolve_aspect

        _spec = _openrouter_video_catalog(selected_model_name) or {}
        _ar = _resolve_aspect(
            aspect_ratio, message, _spec.get("supported_aspect_ratios") or []
        )
        if _ar:
            _submit_body["aspect_ratio"] = _ar
    except Exception:
        logger.exception("video: пропорции не применились")
    _frames = []
    if first_img_abs_url:
        _frames.append({
            "type": "image_url",
            "image_url": {"url": first_img_abs_url},
            "frame_type": "first_frame",
        })
    if last_img_abs_url:
        _frames.append({
            "type": "image_url",
            "image_url": {"url": last_img_abs_url},
            "frame_type": "last_frame",
        })
    if _frames:
        _submit_body["frame_images"] = _frames
    # Отправка идёт в отдельном потоке, а человеку всё это время уходят кадры
    # «отправляем»: провайдер сперва сам скачивает приложенную картинку, и с
    # тяжёлым фото с телефона это занимает больше полуминуты. Раньше мы ждали
    # 30 секунд, сдавались и писали «не удалось запустить» — а провайдер тем
    # временем запрос принимал, снимал ролик и брал за него деньги. Так
    # потерялся оплаченный ролик 21.09.2026 (gen-vid-1789973061…).
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _FutureTimeout

    entry.stage("submitting", f"картинок: {1 if first_img_abs_url else 0}")
    _pool = ThreadPoolExecutor(max_workers=1)
    _future = _pool.submit(
        _requests.post, f"{cfg['base_url'].rstrip('/')}/videos",
        json=_submit_body, headers=auth_headers, timeout=(10, SUBMIT_READ_TIMEOUT))
    resp = None
    submit_error: Exception | None = None
    while True:
        try:
            resp = _future.result(timeout=5)
            break
        except _FutureTimeout:
            # Кадр — чтобы nginx и Cloudflare не оборвали молчащее соединение.
            yield ({"video_progress": "submitting"})
        except Exception as exc:  # noqa: BLE001 — сеть, таймаут, DNS
            submit_error = exc
            break
    _pool.shutdown(wait=False)

    polling_url = ""
    if submit_error is not None:
        # Ответа нет — значит исход НЕИЗВЕСТЕН: провайдер мог принять запрос и
        # взять деньги. Это не «не удалось», это «потеряли» — в разбор.
        logger.error("video submit: ответа нет (model=%s dur=%s res=%s i2v=%s): %s",
                     selected_model_name, duration, resolution, bool(first_img_abs_url),
                     submit_error)
        entry.lost(f"нет ответа на отправку: {submit_error}")
        _release_daily_request(user)
        yield ({"error": "Не удалось запустить генерацию видео. Попробуйте ещё раз.", "done": True})
        return
    if not (200 <= resp.status_code < 300):
        # Провайдер отказал сам — денег он за это не берёт.
        logger.error("video submit http %s (model=%s dur=%s res=%s i2v=%s): %s",
                     resp.status_code, selected_model_name, duration, resolution,
                     bool(first_img_abs_url), resp.text[:300])
        entry.failed(f"http {resp.status_code}: {resp.text[:500]}")
        _release_daily_request(user)
        yield ({"error": "Не удалось запустить генерацию видео. Попробуйте ещё раз.", "done": True})
        return
    try:
        job = resp.json() or {}
    except ValueError:
        job = {}
    job_id = str(job.get("id") or job.get("generation_id") or "").strip()
    polling_url = str(job.get("polling_url") or "").strip()
    if not polling_url and job_id:
        # Адрес опроса не пришёл, но задача принята: строим его сами, иначе
        # потеряли бы уже оплаченный ролик.
        polling_url = f"{cfg['base_url'].rstrip('/')}/videos/{job_id}"
    if not polling_url:
        logger.error("video submit: принято, но нет ни id, ни polling_url: %s", str(job)[:300])
        entry.lost(f"принято без id: {str(job)[:300]}")
        _release_daily_request(user)
        yield ({"error": "Не удалось запустить генерацию видео. Попробуйте ещё раз.", "done": True})
        return
    entry.submitted(job_id, polling_url)

    # d) Poll каждые 5 с до VIDEO_GEN_TIMEOUT_S. Кадр video_progress на
    #    КАЖДОЙ итерации ОБЯЗАТЕЛЕН — это keepalive против обрыва прокси
    #    (nginx proxy_read_timeout 60s), генерация идёт 30–180 секунд.
    timeout_s = int(getattr(settings, "VIDEO_GEN_TIMEOUT_S", 480) or 480)
    deadline = _time.monotonic() + timeout_s
    poll = {}
    status = "pending"
    completed = False
    _beats = 0
    while _time.monotonic() < deadline:
        _time.sleep(5)
        if cancel_check and cancel_check():
            logger.info("video generation canceled by user %s", getattr(user, 'pk', None))
            entry.failed("отменено пользователем (провайдер мог успеть взять деньги)")
            _release_daily_request(user)
            yield ({"error": "Генерация отменена. Кредиты не списаны.",
                    "error_code": "canceled", "done": True})
            return
        try:
            # (connect, read): худший кадр-гэп = 5с sleep + 10 + 20 = 35с < 60с nginx.
            pr = _requests.get(polling_url, headers=auth_headers, timeout=(10, 20))
            data = pr.json() or {}
            if isinstance(data, dict):
                poll = data
                status = str(poll.get("status") or status or "pending")
        except Exception:
            # Транзиентная ошибка поллинга — не роняем, ждём следующую итерацию.
            pass
        _beats += 1
        if _beats % 6 == 0:
            entry.touch()
        yield ({"video_progress": status})
        if status == "completed":
            completed = True
            break
        if status == "failed":
            break
    if not completed:
        # failed ИЛИ вышли по таймауту — кредиты не тронуты.
        logger.warning(
            "video generation not completed: status=%s error=%s poll=%s",
            status, (poll or {}).get("error"), str(poll)[:300],
        )
        _release_daily_request(user)
        if status == "failed":
            entry.failed(str((poll or {}).get("error") or "провайдер вернул failed")[:500])
            yield ({"error": "Видео не получилось сгенерировать. Кредиты не списаны.", "done": True})
            return
        # Не дождались, но провайдер ещё снимает (и возьмёт за это деньги).
        # Запись остаётся открытой: фоновая задача довезёт ролик в этот чат.
        entry.stage("timeout", f"ждали {timeout_s} с, статус {status}")
        yield ({"error": "Видео снимается дольше обычного. Оно появится в этом чате, "
                         "как только будет готово — кредиты спишутся только тогда.",
                "error_code": "video_delayed", "done": True})
        return

    # e) Скачать mp4 (URL временный — качаем сразу) → default_storage,
    #    тем же механизмом, что _save_generated_images (nginx отдаёт /media/).
    try:
        urls = poll.get("unsigned_urls") or []
        video_url = str(urls[0])
        chunks = []
        # Отдельный конечный дедлайн на скачивание: timeout у requests —
        # ПО-ЧАНКОВЫЙ (между чтениями), сам по себе общий не ограничивает.
        dl_deadline = _time.monotonic() + 180
        last_beat = _time.monotonic()
        # ВАЖНО: content-endpoint OpenRouter требует Bearer (unsigned_urls без
        # подписи) — без заголовка отдаёт 401.
        with _requests.get(video_url, headers=auth_headers, stream=True, timeout=(10, 60)) as dl:
            if not (200 <= dl.status_code < 300):
                raise RuntimeError(f"video download http {dl.status_code}")
            for chunk in dl.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    chunks.append(chunk)
                now = _time.monotonic()
                if now > dl_deadline:
                    raise RuntimeError("video download timeout")
                # Keepalive: длинное скачивание не должно молчать >60с
                # (nginx proxy_read_timeout оборвёт SSE).
                if now - last_beat >= 5:
                    last_beat = now
                    entry.touch()
                    yield ({"video_progress": "downloading"})
        new_bytes = b"".join(chunks)

        # ПРОДЛЕНИЕ: приклеиваем свежий сегмент к исходному ролику,
        # чтобы пользователь получил ОДИН цельный файл, а не два.
        # Склейка не удалась — отдаём хотя бы новый сегмент: он
        # оплачен и сгенерирован, терять его нельзя.
        if source_video_bytes:
            yield ({"video_progress": "joining"})
            try:
                from .video_edit import concat_videos

                joined = concat_videos([source_video_bytes, new_bytes])
                if joined:
                    new_bytes = joined
                else:
                    logger.warning("extend: склейка не удалась, отдаём только новый сегмент")
            except Exception:
                logger.exception("extend: склейка упала")

        path = default_storage.save(
            f"ai_videos/{_uuid.uuid4().hex}.mp4", ContentFile(new_bytes)
        )
        # prompt/model едут вместе с вложением: из них потом
        # собирается заголовок публичной страницы ролика (/v/<код>),
        # когда пользователь нажимает «Поделиться».
        atts = [{
            "type": "video",
            "url": default_storage.url(path),
            "name": "esai-video.mp4",
            "prompt": (message or "")[:2000],
            "model": selected_model_name,
        }]
    except Exception as exc:
        logger.exception("video download/save failed")
        # Ролик у провайдера готов и оплачен — запись остаётся открытой, его
        # заберёт фоновая задача.
        entry.stage("download_failed", str(exc)[:200])
        _release_daily_request(user)
        yield ({"error": "Видео готово, но не успело загрузиться. Оно появится в этом чате "
                         "через несколько минут — кредиты спишутся только тогда.",
                "error_code": "video_delayed", "done": True})
        return

    # f) Ответ ассистента + meta (usage.cost из poll может отсутствовать).
    _is_i2v = bool(first_img_abs_url)
    answer = "Готово — видео из вашего фото 🎬" if _is_i2v else "Готово — видео сгенерировано 🎬"
    provider_cost = None
    try:
        provider_cost = (poll.get("usage") or {}).get("cost")
    except Exception:
        provider_cost = None
    usage_meta = {
        "model": selected_model_name,
        "endpoint": "video",
        "video": True,
        "image_to_video": _is_i2v,
        "duration": duration,
        "markup_coefficient": coeff,
    }
    if provider_cost is not None:
        usage_meta["provider_cost_usd"] = provider_cost

    # Пока мы скачивали, ролик могла выдать фоновая задача довоза (если поток
    # надолго замолкал). Второй раз не выдаём и второй раз не списываем.
    if not entry.is_open():
        logger.warning("video: ролик уже выдан фоном, повторно не списываю")
        yield ({"error": "Видео уже в этом чате — обновите страницу.",
                "error_code": "video_delayed", "done": True})
        return

    # g) Сохранение + списание — ТЕМ ЖЕ паттерном, что текстовый путь ниже.
    with transaction.atomic():
        assistant_msg = AiChatMessage.objects.create(
            session=session,
            role="assistant",
            content=answer,
            attachments=atts,
            meta=usage_meta,
        )
        try:
            new_balance = charge_tokens(
                user,
                need,
                "chat",
                meta={
                    "session_id": session.id,
                    "message_id": assistant_msg.id,
                    "model": selected_model_name,
                    "video": True,
                    "duration": duration,
                    "provider_cost_usd": provider_cost,
                },
            )
        except InsufficientTokens as exc:
            new_balance = exc.balance
            if exc.balance > 0:
                try:
                    new_balance = charge_tokens(user, exc.balance, "chat", meta={
                        "session_id": session.id,
                        "message_id": assistant_msg.id,
                        "partial": True,
                        "required": need,
                    })
                except InsufficientTokens as exc2:
                    new_balance = exc2.balance

    entry.stage("saved", atts[0]["url"])
    entry.delivered(credits=need, cost=provider_cost, result_url=atts[0]["url"],
                    message=assistant_msg)

    # extract_user_memory / summarize_session_context для видео НЕ
    # запускаем — из «сгенерируй видео» нечего извлекать, не сжигаем
    # лишние LLM-вызовы.
    yield ({
        "done": True,
        # session ОБЯЗАТЕЛЕН: по нему фронт привязывает чат (setSessionId)
        # и шлёт chat_id в следующих сообщениях. Без него каждое сообщение
        # уходило новой сессией → терялся контекст диалога (баг клиента).
        "session": {
            "id": session.id,
            "uid": session.uid,
            "title": session.title,
            "chat_mode": session.chat_mode,
        },
        "message": AiChatMessageSerializer(assistant_msg).data,
        "tokens_charged": need,
        "balance_tokens": new_balance,
    })
    return
