"""API студии мультфильмов.

Путь пользователя, который эти эндпоинты обслуживают:
  1. GET  presets/           — что можно снять (с видео-превью и ценой)
  2. GET  characters/        — библиотека + свои персонажи
     POST characters/        — загрузить своего или сохранить сгенерированного
     POST characters/generate/ — нарисовать персонажа по описанию
  3. POST projects/          — начать мультфильм с выбранным персонажем
  4. POST projects/<id>/scenes/ — добавить сцену (уходит в фон)
     PATCH scenes/<id>/      — переставить или пересобрать
     DELETE scenes/<id>/     — удалить из таймлайна
  5. POST projects/<id>/assemble/ — склеить готовые сцены в ролик
  6. GET  projects/<id>/     — состояние всего проекта (фронт опрашивает)

Генерация идёт в Celery, поэтому запросы возвращаются мгновенно, а фронт
следит за состоянием по последнему эндпоинту.
"""
from __future__ import annotations

import base64
import io
import logging
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from adminapi.permissions import IsStaff
from core.langutils import request_lang as _lang, tr as _tr

from .models import (CartoonCategory, CartoonCharacter, CartoonPreset, CartoonProject,
                     CartoonScene)
from .tasks import assemble_movie, render_scene

logger = logging.getLogger(__name__)


def _free_balance(user) -> int:
    """Свободный остаток для мгновенных трат (персонаж, примерка, кадр своей сцены):
    баланс минус резервы идущих генераций — сцен, видео чата, дублей видеостудии.
    Иначе кредиты, обещанные снимающемуся ролику, уходили на кадры, и за готовый
    ролик списывать было бы нечего."""
    from plans.wallet import available_tokens

    return available_tokens(user, int(getattr(user, "token_balance", 0) or 0))


class StudioAPIView(APIView):
    """База для действий, которые тратят кредиты — только для вошедших."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]


class StudioPublicAPIView(APIView):
    """База для ВИТРИНЫ: пресеты и библиотека героев открыты всем.

    Ради этого превью и снимались: человек должен увидеть, что получит, ДО
    регистрации. Раньше гость получал пустую страницу с ошибкой — то есть
    десять роликов показывались только тем, кто уже вошёл, а именно их и
    нужно было показать первыми.

    Ничего приватного здесь нет: пресеты — витрина (промпты и модели наружу
    не отдаются), библиотека — общая. Личные персонажи гостю не видны,
    потому что фильтр по пользователю для анонима отдаёт только публичные.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [AllowAny]


def _attach_thumb(char) -> None:
    """Лёгкая копия портрета для сетки библиотеки.

    Без неё в витрину уезжает оригинал под мегабайт, и на телефоне картинки
    не доезжают вовсе. Осечка не критична: витрина откатится на оригинал.
    """
    from django.core.files.base import ContentFile as _CF

    from .thumbs import CHARACTER_BOX, make_thumb

    try:
        with char.image.open("rb") as fh:
            blob = fh.read()
        thumb = make_thumb(blob, CHARACTER_BOX)
        if thumb:
            char.image_thumb.save(f"char-{char.pk}.jpg", _CF(thumb), save=True)
    except Exception:
        logger.exception("миниатюра персонажа %s не сделалась", char.pk)


# Герой с телефона: фото бывает большим, но не бесконечным.
CHARACTER_UPLOAD_MAX_BYTES = 15 * 1024 * 1024


def _clean_character_image(upload):
    """Проверить, что загружена именно картинка, и пересохранить её в JPEG.

    Раньше файл ложился как есть, с именем и расширением от клиента: .html или
    .svg из «загрузки героя» раздавался с нашего домена и мог исполнить скрипт.
    Пересохранение через Pillow оставляет только пиксели. Возвращает
    ContentFile или None, если это не картинка.
    """
    from PIL import Image, ImageOps

    if getattr(upload, "size", 0) and upload.size > CHARACTER_UPLOAD_MAX_BYTES:
        return None
    try:
        raw = upload.read()
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "P"):
            # Прозрачный фон делаем белым: у JPEG альфы нет, а чёрный фон
            # модель приняла бы за часть героя.
            img = img.convert("RGBA")
            back = Image.new("RGB", img.size, (255, 255, 255))
            back.paste(img, mask=img.split()[-1])
            img = back
        else:
            img = img.convert("RGB")
        img.thumbnail((2048, 2048))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=90)
    except Exception:
        return None
    return ContentFile(out.getvalue(), name=f"{uuid.uuid4().hex}.jpg")


def _media(path: str) -> str:
    return default_storage.url(path) if path else ""


def preset_json(p: CartoonPreset, lang: str = "ru", aspect: str | None = None,
                settings: dict | None = None, memo: dict | None = None) -> dict:
    """Пользователю — только витрина: название, превью, длительность и цена.
    Промпты и модели наружу не отдаём: это внутренняя кухня студии.

    aspect — формат мультфильма человека: в режиме цен markup квадрат дешевле
    16:9. Цены нет (себестоимость неизвестна) — credits None и price_unavailable.
    settings — настройки дока {model, resolution, duration} (serializers.feed_settings):
    цена и длительность карточки — такие, какими снимется сцена. Без них — по
    пресету, как раньше (бот, страница цен).
    """
    from .pricing import price_or_none, resolve_config, scene_credits_or_none

    duration = p.duration
    if settings is None:
        credits = scene_credits_or_none(p, aspect=aspect)
    else:
        cfg = resolve_config(p, model=settings.get("model"), resolution=settings.get("resolution"),
                             duration=settings.get("duration"), aspect=aspect, memo=memo)
        price = price_or_none(p, cfg, memo=memo)
        credits = price.total if price is not None else None
        duration = cfg.duration
    row = {
        "id": p.id,
        "slug": p.slug,
        "title": _tr(p, "title", lang),
        "subtitle": _tr(p, "subtitle", lang),
        # В ленту уходит облегчённая копия: там превью играют сами, и полный
        # ролик на 3.5 МБ съел бы мобильный трафик за пару экранов.
        "preview_video": (p.preview_clip.url if p.preview_clip
                          else (p.preview_video.url if p.preview_video else "")),
        # В сетку отдаём лёгкую копию: оригинального кадра на мегабайт хватило
        # бы, чтобы страница не догрузилась вовсе.
        "preview_poster": (p.preview_thumb.url if p.preview_thumb
                           else (p.preview_poster.url if p.preview_poster else "")),
        "duration": duration,
        "aspect_ratio": p.aspect_ratio,
        "credits": credits,
        # Цена примерки героя — её показываем на кнопке ДО запуска (просьба
        # клиента): тот же расчёт, что и списание в PresetTryOnView.
        "tryon_credits": _tryon_price(p),
        "category": p.category.slug if p.category_id else "",
        "audience": p.audience,
        "is_pick": p.is_pick,
    }
    if credits is None:
        row["price_unavailable"] = True
    return row


def _tryon_price(preset) -> int:
    """Во сколько обходится кадр «герой в сцене». Одна формула на витрину и списание."""
    from .pricing import frame_credits

    return frame_credits(preset.image_model) if preset.image_model_id else 1


def _price_unavailable(exc) -> Response:
    """Режим цен markup, себестоимости нет: не снимаем и ничего не списываем.

    detail — для студии и бота (они показывают его как есть), error/error_code —
    общая форма отказа, как у видео в чате и видеостудии.
    """
    return Response({"detail": exc.message, **exc.payload()},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE)


def category_json(c, lang: str = "ru") -> dict:
    return {"slug": c.slug, "title": _tr(c, "title", lang), "emoji": c.emoji}


def character_json(c: CartoonCharacter, lang: str = "ru") -> dict:
    return {
        "id": c.id,
        "name": _tr(c, "name", lang),
        "image": (c.image_thumb.url if c.image_thumb
                  else (c.image.url if c.image else "")),
        "source": c.source,
        "is_mine": c.user_id is not None,
        "category": c.category.slug if c.category_id else "",
        "audience": c.audience,
    }


def _pair_video_url(row) -> str:
    return _media(row.clip or row.video) if row else ""


def _pair_videos_for(scenes) -> dict:
    """Ролики пар для сцен проекта одним запросом: {(сцена, герой): url}.

    Только в формате мультфильма: вертикальный ролик горизонтальному не показываем."""
    from .models import CartoonPairVideo

    keys = set()
    for s in scenes:
        if s.custom_text:
            continue
        hero_id = s.character_id or (s.project.character_id if s.project_id else None)
        if s.preset_id and hero_id:
            keys.add((s.preset_id, hero_id, (s.project.aspect_ratio if s.project_id else "") or "16:9"))
    if not keys:
        return {}
    rows = CartoonPairVideo.objects.filter(
        preset_id__in={k[0] for k in keys}, character_id__in={k[1] for k in keys},
        aspect_ratio__in={k[2] for k in keys})
    return {(r.preset_id, r.character_id): _pair_video_url(r)
            for r in rows if (r.preset_id, r.character_id, r.aspect_ratio) in keys}


def _scene_config(s: CartoonScene, memo: dict | None = None):
    """Чем снимется сцена: идущая съёмка — по снимку, иначе по текущему доку
    (готовую сцену переснимут уже с новыми настройками и по новой цене)."""
    from .pricing import scene_config, shot_config

    if s.status in WORKING_STATUSES:
        return shot_config(s, memo)
    return scene_config(s, memo)


def _shot_json(s: CartoonScene, memo: dict | None = None) -> dict | None:
    """Снимок последнего «Снять»: чем сцена снимается или снята (значок «Mini · 480p · 5 с»).

    Сцена снята или снимается без снимка (до дока) — по пресету в формате
    мультфильма, как её и снимали (pricing.shot_config); цены снимка у неё нет.
    Иначе длина ролика бралась бы из нынешнего дока, а не из самого ролика.
    """
    from .pricing import has_snapshot, shot_config

    if has_snapshot(s):
        return {**shot_config(s, memo).to_json(), "credits_planned": s.credits_planned}
    if s.preset_id and (s.status in WORKING_STATUSES or s.status == CartoonScene.STATUS_READY):
        return {**shot_config(s, memo).to_json(), "credits_planned": None}
    return None


def shot_token(s: CartoonScene) -> str:
    """Метка снятого ролика: меняется ровно тогда, когда сцену пересняли.

    Бот кладёт её в кнопки пересъёмки готовой сцены (expect_shot): старая кнопка
    после пересъёмки не снимает второй раз. Берётся исходный ролик, а не сведённый
    со звуком — звук пересъёмкой не считается.
    """
    import hashlib

    name = str(s.video or "")
    return hashlib.blake2s(name.encode("utf-8"), digest_size=4).hexdigest() if name else ""


def scene_json(s: CartoonScene, lang: str = "ru", pair_videos: dict | None = None,
               memo: dict | None = None) -> dict:
    from .pricing import price_or_none

    hero_id = s.character_id or s.project.character_id
    if pair_videos is None:
        pair_videos = _pair_videos_for([s])
    from .pricing import has_snapshot

    custom = bool(s.custom_text)
    # Та же формула, что у проверки баланса и списания (pricing.config_price), с
    # настройками дока и в формате мультфильма. Цены нет (markup без себестоимости) — None.
    config = _scene_config(s, memo) if s.preset_id else None
    # Идёт съёмка по снимку: спишется ровно цена с кнопки (credits_planned), а не
    # нынешняя цена дока или наценки — её и показываем (бот, лента сайта).
    planned = (s.credits_planned if s.preset_id and s.status in WORKING_STATUSES and has_snapshot(s)
               else None)
    price = (price_or_none(s.preset, config, memo=memo)
             if config is not None and planned is None else None)
    if not s.preset_id:
        video_price, frame_price = 0, 0
    elif planned is not None:
        video_price, frame_price = planned, 0
    else:
        video_price = price.video if price is not None else None
        frame_price = price.frame if price is not None else 0
    row = {
        "id": s.id,
        "order": s.order,
        # Своя сцена: название — из описания человека, превью у неё нет.
        "custom_text": s.custom_text,
        "dialogue": s.dialogue,
        "preset": {"id": s.preset_id,
                   "title": ((s.custom_title or s.custom_text[:60]) if custom
                             else (_tr(s.preset, "title", lang) if s.preset_id else "")),
                   # Ролик самой сцены (с героем библиотеки): движение в ленте,
                   # пока своего ролика и кадра пары ещё нет.
                   "clip": "" if custom or not s.preset_id else (
                       s.preset.preview_clip.url if s.preset.preview_clip
                       else (s.preset.preview_video.url if s.preset.preview_video else "")),
                   # Цена нужна прямо в ленте: снимают оттуда, и человек должен
                   # видеть, во что обойдётся кнопка, до нажатия.
                   "credits": None if video_price is None else frame_price + video_price,
                   # Длительность, с которой сцена снимется (или снимается): своя,
                   # мультфильма или пресета, в пределах модели.
                   "duration": config.duration if config is not None else 0,
                   # Обложка нужна черновику: своего кадра у него ещё нет, а
                   # пустой прямоугольник с крутилкой выглядит так, будто
                   # что-то грузится и зависло.
                   "poster": (s.preset.preview_thumb.url if s.preset.preview_thumb
                              else (s.preset.preview_poster.url
                                    if s.preset.preview_poster else ""))
                   if s.preset_id and not custom else ""},
        # Герой именно этой сцены: свой, если задан, иначе герой мультфильма.
        # Фронту нужно показать, кем сцена снимется, ещё до съёмки.
        "character": character_json(s.character or s.project.character, lang)
                     if (s.character_id or s.project.character_id) else None,
        "keyframe": _media(s.keyframe),
        # Движущееся превью пары, если такого героя в этой сцене уже снимали:
        # человек видит сцену в движении ещё до своей съёмки.
        "preview_video": "" if (s.video or custom) else pair_videos.get((s.preset_id, hero_id), ""),
        # Со звуком, если его свели; исходное видео — для пересведения.
        "video": _media(s.mixed_video or s.video),
        "audio_count": getattr(s, "audio_n", None) if getattr(s, "audio_n", None) is not None
                       else s.audio_tracks.count(),
        "status": s.status,
        "error": s.error,
        "credits_spent": s.credits_spent,
        # Сколько спишет съёмка прямо сейчас: с готовым кадром — только видео.
        # По этой цифре лента спрашивает подтверждение перед пересъёмкой.
        "render_credits": (None if video_price is None
                           else video_price if s.keyframe or planned is not None
                           else frame_price + video_price),
        # Своя длительность сцены (null — как у мультфильма или пресета).
        "duration": s.duration,
        # Чем сцена снимется при «Снять» сейчас (идёт съёмка — чем снимается).
        "config": config.to_json() if config is not None else None,
        # Чем снята или снимается; null — не снималась.
        "shot": _shot_json(s, memo),
        # Метка снятого ролика: кнопка пересъёмки из старого меню бота её сверяет.
        "shot_token": shot_token(s),
    }
    if video_price is None:
        row["price_unavailable"] = True
    return row


def _effective_json(p: CartoonProject, memo: dict | None = None) -> dict | None:
    """Настройки дока, как их видит человек: свои мультфильма, а пустые — по
    «типичной сцене». model_available=False — выбранную модель выключили."""
    from .pricing import reference_preset, resolve_config

    ref = reference_preset(memo)
    if ref is None:
        return None
    cfg = resolve_config(ref, model=p.video_model if p.video_model_id else None,
                         resolution=p.resolution or None, duration=p.duration or None,
                         aspect=p.aspect_ratio or "16:9", memo=memo)
    return {**cfg.to_json(), "model_available": cfg.model_available}


def project_json(p: CartoonProject, lang: str = "ru", memo: dict | None = None) -> dict:
    """memo — кэш каталога и цен на один запрос (список мультфильмов делит его на всех)."""
    from django.db.models import Count, Sum

    scenes = list(p.scenes.select_related(
        "preset", "preset__image_model", "preset__video_model", "character",
        "project__character", "project__video_model", "shot_model").annotate(
        audio_n=Count("audio_tracks"),
        audio_credits=Sum("audio_tracks__credits_spent")).order_by("order", "id"))
    pairs = _pair_videos_for(scenes)
    memo = {} if memo is None else memo
    return {
        "id": p.id,
        "title": p.title,
        "status": p.status,
        "aspect_ratio": p.aspect_ratio,
        # Док: свои настройки мультфильма (null — как в пресете сцены) и то,
        # что из них выходит для «типичной сцены».
        "video_model": p.video_model.openrouter_id if p.video_model_id else None,
        "resolution": p.resolution or None,
        "duration": p.duration,
        "effective": _effective_json(p, memo),
        "character": character_json(p.character, lang) if p.character else None,
        "result_video": _media(p.result_video),
        "error": p.error,
        "scenes": [scene_json(s, lang, pairs, memo) for s in scenes],
        "created_at": p.created_at.isoformat(),
        "credits_spent": (sum(s.credits_spent for s in scenes)
                          + sum(s.audio_credits or 0 for s in scenes)),
        # Идёт ли сейчас озвучка всего мультфильма — по ней фронт держит опрос.
        "voicing": _voicing(p.pk),
    }


def _voicing(project_id: int):
    """Состояние озвучки всего мультфильма: идёт, завершилась или сорвалась.

    Отдаём и завершённое: иначе сбой («не хватило кредитов») пропал бы молча,
    а человек так и не понял бы, почему заговорили не все сцены.
    """
    from .voiceover import get_progress, is_stale

    state = get_progress(project_id)
    if not state:
        return None
    if is_stale(state):
        # Задачу убили (деплой, перезапуск воркера): показываем обрыв, а не
        # вечное «озвучиваю» — за неозвученное человек ничего не заплатил.
        return {**state, "finished": True, "error": state.get("error") or "interrupted"}
    if state.get("finished") and not state.get("error"):
        return None
    return state


class PresetsView(StudioPublicAPIView):
    """GET — активные пресеты сцен вместе с разделами библиотеки.

    Разделы отдаём тем же запросом, а не отдельной ручкой: библиотека без них
    не рисуется, а лишний поход по сети на старте студии — лишняя секунда до
    первого превью.
    """

    def get(self, request):
        # Сортировка по разделу нужна и во вкладке «Все»: там сцены идут одной
        # лентой, и без неё финал соседствует с началом.
        # Без превью сцену не показываем: карточка с пустым прямоугольником
        # хуже её отсутствия, а библиотека наполняется постепенно. Скрытый в
        # панели раздел прячет и свои сцены — иначе они оставались во «Всех».
        qs = CartoonPreset.objects.filter(is_active=True).exclude(
            preview_video="").filter(
            Q(category__isnull=True) | Q(category__is_active=True)).select_related(
            "image_model", "video_model", "category").order_by(
            "category__sort_order", "sort_order", "id")
        lang = _lang(request)
        # Формат мультфильма человека (необязательно): в режиме markup от него
        # зависит цена. Без него — формат самого пресета.
        raw_aspect = request.query_params.get("aspect_ratio")
        aspect = _aspect(raw_aspect) if raw_aspect else None
        # Настройки дока: мультфильм (?project=) и/или явные video_model,
        # resolution, duration (гость). Без них цены — по пресетам, как раньше.
        from .serializers import SettingsError, feed_settings

        project = None
        raw_project = request.query_params.get("project")
        if raw_project:
            project = _own_project(request, raw_project)
            if project is None:
                return Response({"detail": "Мультфильм не найден"}, status=status.HTTP_404_NOT_FOUND)
            if aspect is None:
                aspect = project.aspect_ratio or "16:9"
        memo: dict = {}
        try:
            settings = feed_settings(request.query_params, project, memo=memo)
        except SettingsError as exc:
            return Response(exc.payload(), status=exc.status)
        presets = [preset_json(p, lang, aspect, settings, memo) for p in qs]
        used = {p["category"] for p in presets}
        cats = CartoonCategory.objects.filter(is_active=True)
        body = {
            # Пустые разделы не показываем: человек ткнёт и увидит ничего.
            "categories": [category_json(c, lang) for c in cats if c.slug in used],
            "presets": presets,
            "popular": self._popular(),
        }
        if settings is not None:
            body["settings"] = {
                "video_model": settings["model"].openrouter_id if settings["model"] is not None else None,
                "resolution": settings["resolution"], "duration": settings["duration"],
                "aspect_ratio": aspect}
        return Response(body)

    @staticmethod
    def _popular(limit: int = 12) -> list:
        """Что чаще всего берут в ленту.

        Считаем по реальным добавлениям, а не по галочке в админке: подборка
        «Популярное», собранная руками, врёт ровно до первого пользователя.
        Пока данных мало, подборки просто нет — пустая вкладка хуже честного
        её отсутствия.
        """
        from django.db.models import Count

        rows = (CartoonScene.objects.exclude(preset__slug=_custom_slug()).values("preset__slug")
                .annotate(n=Count("id")).order_by("-n")[:limit])
        slugs = [r["preset__slug"] for r in rows if r["preset__slug"]]
        return slugs if len(slugs) >= 6 else []


def _own_project(request, raw_id):
    """Свой мультфильм по id из запроса (или None: чужой, не число, гость)."""
    if not request.user.is_authenticated:
        return None
    try:
        pk = int(raw_id)
    except (TypeError, ValueError):
        return None
    if not (0 < pk < 2 ** 31):
        return None
    return CartoonProject.objects.filter(pk=pk, user=request.user).select_related("video_model").first()


class ModelsView(StudioPublicAPIView):
    """GET — модели дока мультстудии (Seedance Mini, Fast, 2.0, 2.5) с ценой СЦЕНЫ.

    Форма — ModelJSON видеостудии, чтобы её пикеры рисовали список как есть:
    price.table — {качество: {секунды: кадр + видео}} в формате ?aspect_ratio=
    (или формате ?project=), price.by_aspect — по каждому формату. Открыто
    всем: гость собирает ленту и видит цены до входа.
    """

    def get(self, request):
        from .serializers import models_payload

        aspect = None
        raw_project = request.query_params.get("project")
        if raw_project:
            project = _own_project(request, raw_project)
            if project is None:
                return Response({"detail": "Мультфильм не найден"}, status=status.HTTP_404_NOT_FOUND)
            aspect = project.aspect_ratio or "16:9"
        raw_aspect = request.query_params.get("aspect_ratio")
        if raw_aspect:
            aspect = _aspect(raw_aspect)
        return Response(models_payload(aspect or "16:9", memo={}))


class DefaultsAdminView(APIView):
    """GET / PATCH — настройки новых мультфильмов (модель, качество, длительность).

    Для карточки «Мультстудия: по умолчанию» в «Настройках» админки. Только
    сотрудники. Пустое значение — вернуть значение из кода (Mini, 480p, 5 с).
    Применяются, только если модель включена и умеет это качество и длительность
    (pricing.new_project_settings) — иначе новые мультфильмы снимаются по пресету,
    а ответ говорит почему (warnings).
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsStaff]

    def get(self, request):
        from .serializers import defaults_admin_payload

        return Response(defaults_admin_payload())

    def patch(self, request):
        from django.db import transaction

        from adminapi.runtime import delete_runtime, set_runtime
        from ai.pricing import invalidate_price_caches
        from audit.services import log_admin_action

        from .pricing import (CODE_DEFAULT_DURATION, CODE_DEFAULT_MODEL, CODE_DEFAULT_RESOLUTION,
                              KEY_DEFAULT_DURATION, KEY_DEFAULT_MODEL, KEY_DEFAULT_RESOLUTION,
                              default_settings_raw, validate_defaults)
        from .serializers import defaults_admin_payload

        data = request.data if isinstance(request.data, dict) else {}
        fields = (("model", KEY_DEFAULT_MODEL, CODE_DEFAULT_MODEL),
                  ("resolution", KEY_DEFAULT_RESOLUTION, CODE_DEFAULT_RESOLUTION),
                  ("duration", KEY_DEFAULT_DURATION, CODE_DEFAULT_DURATION))
        if not any(name in data for name, _, _ in fields):
            return Response({"detail": "Нечего сохранять: пришлите model, resolution или duration"},
                            status=status.HTTP_400_BAD_REQUEST)
        before = default_settings_raw()
        wanted = dict(before)
        cleared = set()
        for name, _, code_default in fields:
            if name not in data:
                continue
            raw = data[name]
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                wanted[name] = code_default
                cleared.add(name)
            else:
                wanted[name] = raw
        try:
            clean = validate_defaults(wanted)
        except ValueError as exc:
            return Response({"detail": str(exc), "errors": {"defaults": str(exc)}},
                            status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            for name, key, _ in fields:
                if name not in data:
                    continue
                if name in cleared:
                    delete_runtime(key)
                else:
                    set_runtime(key, clean[name])
            after = {name: clean[name] for name, _, _ in fields}
            if after != before:
                log_admin_action(request.user, "settings.edit",
                                 before={"cartoon_defaults": before},
                                 after={"cartoon_defaults": after}, request=request)
        # Список моделей дока держит и то, что получат новые мультфильмы.
        invalidate_price_caches()
        transaction.on_commit(invalidate_price_caches)
        return Response(defaults_admin_payload())


class PricingView(StudioPublicAPIView):
    """GET — из чего складывается счёт студии.

    Считается по тем же моделям, что и реальные списания, а не вписывается
    руками: коэффициенты меняются в админке, и страница тарифов не должна
    расходиться со списаниями. Дороже сцены в студии ничего нет, поэтому
    именно она и есть единица счёта для пользователя.
    """

    def get(self, request):
        from ai.models import GPTModels
        from ai.pricing import image_credits

        from .pricing import new_project_settings, price_or_none, resolve_config, scene_credits_or_none, short_name
        from .serializers import defaults_json

        img = GPTModels.objects.filter(
            openrouter_id="google/gemini-2.5-flash-image", is_active=True).first()
        character = image_credits(img) if img else 4

        # Сцены считаются так, как снимет НОВЫЙ мультфильм: с настройками по
        # умолчанию из админки (Mini 480p 5 с) в формате 16:9, а если их не
        # применить (модель выключена) — по пресетам, как и сам мультфильм
        # (pricing.new_project_settings). Иначе тарифы обещали бы цену 2.0, а
        # мультфильм стоил бы цену Mini.
        memo: dict = {}
        model, resolution, duration = new_project_settings(memo)
        presets = CartoonPreset.objects.filter(is_active=True).select_related("image_model", "video_model")

        def price(p):
            if model is None:
                return scene_credits_or_none(p)
            cfg = resolve_config(p, model=model, resolution=resolution, duration=duration, aspect="16:9",
                                 memo=memo)
            found = price_or_none(p, cfg, memo=memo)
            return found.total if found is not None else None

        # Сцены без цены (режим markup, себестоимость неизвестна) не продаются —
        # в диапазон «от и до» они не входят.
        prices = sorted(value for value in (price(p) for p in presets) if value is not None)
        fallback = model is not None and not prices
        if fallback:
            # Модель по умолчанию предлагается, но цены у неё нет ни на одной сцене:
            # «сцена — от 0 кр» было бы враньём (бот печатал бы его) — считаем по
            # пресетам, как до настроек по умолчанию, и честно пишем source=preset.
            prices = sorted(value for value in (scene_credits_or_none(p) for p in presets) if value is not None)
        if not prices:
            prices = [0]
        # Медиана, а не среднее: пара коротких сцен не должна занижать цифру,
        # по которой человек прикидывает, на сколько ему хватит пакета.
        typical = prices[len(prices) // 2]
        defaults = defaults_json(memo, preset=fallback)
        return Response({
            "character": character,
            # «от N кр» за сцену — самая дешёвая сцена нового мультфильма.
            "scene_min": prices[0],
            "scene_typical": typical,
            "scene_max": prices[-1],
            # Склейка идёт на нашем сервере через ffmpeg и моделям не платится.
            "assembly": 0,
            # С чем снимается новый мультфильм: settings — настройки админки,
            # preset — откат на пресеты (у сцен тогда свои модель и длительность).
            "settings": {**defaults, "model_name": short_name(model) if model is not None and not fallback else "",
                         "aspect_ratio": "16:9"},
        })


class CharactersView(StudioPublicAPIView):
    """GET — библиотека и свои персонажи. POST — загрузить своего."""

    def get(self, request):
        library = Q(is_public=True, user__isnull=True)
        # У анонима нет своих персонажей, а Q(user=AnonymousUser) уронил бы запрос.
        mine = Q(user=request.user) if request.user.is_authenticated else Q(pk__in=[])
        qs = CartoonCharacter.objects.filter(library | mine).select_related(
            "category").order_by("-user_id", "sort_order", "-created_at")
        lang = _lang(request)
        return Response([character_json(c, lang) for c in qs])

    def post(self, request):
        if not request.user.is_authenticated:
            return Response({"detail": "Войдите, чтобы загрузить своего персонажа"},
                            status=status.HTTP_401_UNAUTHORIZED)
        image = request.FILES.get("image")
        if not image:
            return Response({"detail": "Приложите изображение персонажа"},
                            status=status.HTTP_400_BAD_REQUEST)
        image = _clean_character_image(image)
        if image is None:
            return Response({"detail": "Это не похоже на картинку. Загрузите фото JPG, PNG или WebP до 15 МБ"},
                            status=status.HTTP_400_BAD_REQUEST)
        char = CartoonCharacter.objects.create(
            user=request.user,
            name=(request.data.get("name") or "Мой персонаж").strip()[:120],
            image=image,
            description=(request.data.get("description") or "").strip()[:1000],
            source=CartoonCharacter.SOURCE_UPLOAD,
        )
        _attach_thumb(char)
        # Кто на картинке — нужно знать ДО первой примерки: без описания модель
        # рисует «человека вообще» вместо загруженного героя.
        from .services import ensure_description

        ensure_description(char)
        return Response(character_json(char, _lang(request)), status=status.HTTP_201_CREATED)


class CharacterDetailView(StudioAPIView):
    """DELETE — убрать своего героя из библиотеки.

    Только свой (загруженный или нарисованный): библиотечные общие, их правит
    админ. Снятые сцены герой не теряют — у них своё видео, а ссылка на героя
    просто обнуляется (SET_NULL). Но сцену, которая снимается прямо сейчас,
    без героя оставлять нельзя: съёмке он ещё нужен.
    """

    def delete(self, request, pk):
        char = CartoonCharacter.objects.filter(pk=pk, user=request.user).first()
        if not char:
            return Response({"detail": "Это не ваш герой"}, status=status.HTTP_404_NOT_FOUND)
        busy = CartoonScene.objects.filter(
            Q(character=char) | Q(character__isnull=True, project__character=char),
            status__in=(CartoonScene.STATUS_NEW, CartoonScene.STATUS_KEYFRAME,
                        CartoonScene.STATUS_VIDEO),
        ).exists()
        if busy:
            return Response({"detail": "С этим героем сейчас снимается сцена — дождитесь конца съёмки"},
                            status=status.HTTP_400_BAD_REQUEST)
        char.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CharacterGenerateView(StudioAPIView):
    """POST — нарисовать персонажа по описанию и сохранить в свою библиотеку.

    Рисуем на белом фоне в полный рост: такой кадр лучше всего работает
    референсом — модели проще перенести героя в любую сцену, когда его ничто
    не загораживает.
    """

    def post(self, request):
        import requests as http

        from ai.handlers import _openrouter_config
        from ai.models import GPTModels

        prompt = (request.data.get("prompt") or "").strip()
        if not prompt:
            return Response({"detail": "Опишите персонажа"}, status=status.HTTP_400_BAD_REQUEST)

        model = GPTModels.objects.filter(
            openrouter_id="google/gemini-2.5-flash-image", is_active=True).first()
        if not model:
            return Response({"detail": "Модель для персонажей недоступна"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        from ai.pricing import image_credits

        price = image_credits(model)
        balance = _free_balance(request.user)
        if balance < price:
            return Response({"detail": "Недостаточно кредитов", "required": price,
                             "balance": balance}, status=status.HTTP_402_PAYMENT_REQUIRED)

        cfg = _openrouter_config()
        # «character sheet» из промпта убрано намеренно: Nano Banana хорошо
        # рисует текст и честно печатала подпись прямо в картинке («FRIENDLY
        # DRAGON / CHARACTER SHEET»). Надписи запрещаем явно — иначе они
        # налезают на имя персонажа в плитке.
        full = (f"{prompt}. Full body view, standing, clean plain white background, "
                "NO text, NO captions, NO labels, NO watermark anywhere in the image. "
                "3D cartoon animation style, soft lighting, vibrant colors, front view.")
        try:
            r = http.post(
                f"{cfg['base_url'].rstrip('/')}/images",
                json={"model": model.openrouter_id, "prompt": full, "aspect_ratio": "1:1"},
                headers={"Authorization": f"Bearer {cfg['api_key']}",
                         "Content-Type": "application/json"},
                timeout=(10, 180),
            )
            if not (200 <= r.status_code < 300):
                raise RuntimeError(f"http {r.status_code}: {r.text[:200]}")
            b64 = (((r.json() or {}).get("data") or [{}])[0]).get("b64_json") or ""
            if not b64:
                raise RuntimeError("в ответе нет изображения")
        except Exception as exc:
            logger.exception("персонаж не сгенерировался")
            return _image_failure(exc, "hero")

        char = CartoonCharacter(
            user=request.user,
            name=(request.data.get("name") or prompt[:60]).strip()[:120],
            description=prompt[:1000],
            source=CartoonCharacter.SOURCE_GENERATED,
        )
        char.image.save(f"{uuid.uuid4().hex}.jpg", ContentFile(base64.b64decode(b64)), save=True)
        _attach_thumb(char)

        from .services import charge

        charge(request.user, price, "cartoon_character", meta={"character": char.pk},
               respect_reserves=True)
        return Response(character_json(char, _lang(request)), status=status.HTTP_201_CREATED)


class ProjectsView(StudioAPIView):
    """GET — мои мультфильмы. POST — начать новый."""

    def get(self, request):
        qs = CartoonProject.objects.filter(user=request.user).select_related(
            "video_model").prefetch_related("scenes")[:50]
        lang, memo = _lang(request), {}
        return Response([project_json(p, lang, memo) for p in qs])

    def post(self, request):
        char_id = request.data.get("character_id")
        character = CartoonCharacter.objects.filter(
            Q(pk=char_id) & (Q(user=request.user) | Q(is_public=True, user__isnull=True))
        ).first()
        if not character:
            return Response({"detail": "Выберите персонажа"}, status=status.HTTP_400_BAD_REQUEST)

        from .serializers import SettingsError, parse_project_settings

        data = request.data if isinstance(request.data, dict) else {}
        try:
            dock, adjusted = parse_project_settings(data, memo={})
        except SettingsError as exc:
            return Response(exc.payload(), status=exc.status)
        project = CartoonProject.objects.create(
            user=request.user,
            title=(request.data.get("title") or "Мой мультфильм").strip()[:140],
            character=character,
            aspect_ratio=_aspect(request.data.get("aspect_ratio")),
            **_new_project_dock(dock),
        )
        body = project_json(project, _lang(request))
        if adjusted:
            body["adjusted"] = adjusted
        return Response(body, status=status.HTTP_201_CREATED)


def _new_project_dock(dock: dict) -> dict:
    """Настройки нового мультфильма: присланные, иначе — по умолчанию из админки.

    По умолчанию (pricing.new_project_settings) — только если модель включена и
    умеет это качество и длительность; иначе всё пусто, то есть как в пресете.
    Так работают и бот, и старые клиенты: они ничего не присылают.
    """
    from .pricing import default_settings_raw, find_resolution, model_caps, new_project_settings

    if not dock:
        model, resolution, duration = new_project_settings()
        return {"video_model": model, "resolution": resolution, "duration": duration}
    out = {"video_model": dock.get("video_model"), "resolution": dock.get("resolution"),
           "duration": dock.get("duration")}
    model = out["video_model"]
    if model is not None and ("resolution" not in dock or "duration" not in dock):
        # Прислали только модель — качество и длительность по умолчанию, если она их умеет.
        raw, caps = default_settings_raw(), model_caps(model)
        if caps is not None:
            if "resolution" not in dock:
                out["resolution"] = find_resolution(caps.resolutions, raw["resolution"])
            if "duration" not in dock and raw["duration"] in caps.durations:
                out["duration"] = raw["duration"]
    return out


class ProjectImportView(StudioAPIView):
    """POST — перенести ленту, собранную гостем, в настоящий проект.

    Клиент: «после авторизации сохраняем героя, сцены и весь текущий проект и
    возвращаем пользователя именно в этот проект». Гость собирает ленту в
    браузере — в базе у него проектов нет, — а после входа фронт отдаёт её
    сюда целиком.

    Здесь ничего не списывается: сцены встают в ленту черновиками, как при
    обычном добавлении. Готовые кадры подставляются сразу.
    """

    MAX_SCENES = 30

    def post(self, request):
        from django.db import transaction

        data = request.data if isinstance(request.data, dict) else {}
        key = str(data.get("draft_id") or "").strip()[:64]
        lang = _lang(request)
        if key:
            existing = CartoonProject.objects.filter(user=request.user, import_key=key).first()
            if existing:
                return Response(project_json(existing, lang))

        character = _pick_character(request, data.get("character_id"))
        if not character:
            return Response({"detail": "Выберите персонажа"}, status=status.HTTP_400_BAD_REQUEST)

        rows = data.get("scenes") if isinstance(data.get("scenes"), list) else []
        rows = [r for r in rows if isinstance(r, dict)][: self.MAX_SCENES]
        ids = []
        for r in rows:
            try:
                ids.append(int(r.get("preset_id")))
            except (TypeError, ValueError):
                ids.append(None)
        presets = {p.pk: p for p in CartoonPreset.objects.filter(
            pk__in=[i for i in ids if i], is_active=True).exclude(slug=_custom_slug())}
        custom_base = None

        # Настройки дока из черновика гостя. Черновик мог устареть (модель
        # выключили, длительность другая) — не отказ, иначе лента пропала бы:
        # берём ближайшее и говорим об этом (adjusted).
        from .serializers import SettingsError, parse_project_settings

        memo: dict = {}
        try:
            dock, adjusted = parse_project_settings(data, lenient=True, memo=memo)
        except SettingsError:
            dock, adjusted = {}, []

        with transaction.atomic():
            project = CartoonProject.objects.create(
                user=request.user,
                title=(str(data.get("title") or "") or "Мой мультфильм").strip()[:140],
                character=character,
                aspect_ratio=_aspect(data.get("aspect_ratio")),
                import_key=key,
                **_new_project_dock(dock),
            )
            order = 0
            for r, pid in zip(rows, ids):
                custom_text, _ = _custom_text(r.get("custom_text"))
                if custom_text:
                    if custom_base is None:
                        try:
                            custom_base = _custom_preset()
                        except RuntimeError:
                            continue
                    preset = custom_base
                else:
                    preset = presets.get(pid)
                if not preset:
                    continue
                scene = CartoonScene.objects.create(
                    project=project, preset=preset,
                    character=_pick_character(request, r.get("character_id")),
                    order=order, status=CartoonScene.STATUS_DRAFT,
                    custom_text=custom_text, custom_title=custom_text[:60],
                    dialogue=_dialogue(r.get("dialogue")),
                )
                if r.get("duration") not in (None, ""):
                    _import_scene_duration(scene, r.get("duration"), memo, adjusted)
                order += 1

        for scene in project.scenes.select_related("project__character", "character"):
            _attach_ready_keyframe(scene)
        body = project_json(project, lang)
        if adjusted:
            body["adjusted"] = adjusted
        return Response(body, status=status.HTTP_201_CREATED)


def _import_scene_duration(scene, raw, memo: dict, adjusted: list) -> None:
    """Длительность сцены из черновика гостя: неверная — ближайшая, что умеет модель."""
    from .pricing import clamp_duration, model_caps, scene_config
    from .serializers import SettingsError, parse_duration_value, parse_scene_duration

    try:
        scene.duration = parse_scene_duration(raw, scene, memo=memo)
    except SettingsError:
        try:
            want = parse_duration_value(raw)
        except SettingsError:
            return
        model = scene_config(scene, memo).model
        caps = model_caps(model, memo)
        if want is None or caps is None or not caps.durations:
            return
        scene.duration = clamp_duration(caps.durations, want)
        adjusted.append({"field": "duration", "scene": scene.pk, "from": want, "to": scene.duration,
                         "message": f"Сцена {scene.order + 1}: {want} с не снять — выбрано {scene.duration} с"})
    scene.save(update_fields=["duration", "updated_at"])


class ProjectDetailView(StudioAPIView):
    """GET — состояние проекта (фронт опрашивает во время генерации).
    DELETE — удалить черновик."""

    def get(self, request, pk):
        project = get_object_or_404(CartoonProject, pk=pk, user=request.user)
        return Response(project_json(project, _lang(request)))

    def patch(self, request, pk):
        """Формат мультфильма: вертикальный, горизонтальный или квадрат.

        Клиент: формат применяется ко ВСЕМ сценам серии. Уже снятые сцены
        переснять нельзя (за них заплачено), но при склейке они вписываются в
        общий кадр — мультфильм всё равно выходит одного размера.
        """
        project = get_object_or_404(CartoonProject, pk=pk, user=request.user)
        data = request.data if isinstance(request.data, dict) else {}
        # Док: модель, качество, длительность — проверяем до любых сохранений,
        # чтобы отказ ничего не менял наполовину.
        from .serializers import SettingsError, parse_project_settings

        memo: dict = {}
        try:
            dock, adjusted = parse_project_settings(data, project, memo=memo)
        except SettingsError as exc:
            return Response(exc.payload(), status=exc.status)
        if "title" in data:
            # Клиент: человек должен давать название своему мультфильму.
            title = " ".join(str(data.get("title") or "").split())[:140]
            project.title = title or "Мой мультфильм"
            project.save(update_fields=["title", "updated_at"])
        if "aspect_ratio" in data:
            aspect = _aspect(data.get("aspect_ratio"))
            if aspect != project.aspect_ratio:
                project.aspect_ratio = aspect
                project.save(update_fields=["aspect_ratio", "updated_at"])
                # Кадры черновиков рисовались под прежний формат — сбрасываем
                # и подставляем готовые нужного формата, если они есть. Не
                # снявшиеся сцены тоже: их пересъёмка пошла бы со старым кадром.
                drafts = list(project.scenes.filter(status__in=(CartoonScene.STATUS_DRAFT,
                                                                CartoonScene.STATUS_FAILED))
                              .exclude(keyframe="").select_related("project__character",
                                                                   "character"))
                for scene in drafts:
                    scene.keyframe = ""
                    scene.video_prompt = ""
                    scene.save(update_fields=["keyframe", "video_prompt", "updated_at"])
                    _attach_ready_keyframe(scene)
        if dock:
            adjusted += _apply_dock(project, dock, memo)
        body = project_json(project, _lang(request))
        if adjusted:
            body["adjusted"] = adjusted
        return Response(body)

    def delete(self, request, pk):
        project = get_object_or_404(CartoonProject, pk=pk, user=request.user)
        # Пока идёт съёмка или склейка, мультфильм не удаляем: задача доделает
        # работу, а сохранить её будет некуда.
        if (project.status == CartoonProject.STATUS_ASSEMBLING
                or project.scenes.filter(status__in=WORKING_STATUSES).exists()):
            return Response({"detail": "Мультфильм сейчас снимается или склеивается — "
                                       "удалить его можно, когда работа закончится"},
                            status=status.HTTP_400_BAD_REQUEST)
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _apply_dock(project, dock: dict, memo: dict) -> list:
    """Сохранить настройки дока и подогнать под них сцены, которые сейчас не снимаются.

    Сцены в работе не трогаем: они снимаются по снимку. Своя длительность сцены,
    которую новая модель не умеет, становится ближайшей (adjusted). Промпт
    съёмки сцен-черновиков собран под прежнюю длительность — сбрасываем, как при
    смене формата; у остальных его сверит «Снять» (_queue_render).
    """
    from .pricing import clamp_duration, model_caps, scene_config

    idle = (CartoonScene.STATUS_DRAFT, CartoonScene.STATUS_FAILED, CartoonScene.STATUS_READY)
    scenes = list(project.scenes.filter(status__in=idle).select_related(
        "preset__video_model", "preset__image_model", "character").order_by("order", "id"))
    before = {s.pk: scene_config(s, memo).duration for s in scenes}
    fields = [name for name in ("video_model", "resolution", "duration") if name in dock]
    for name in fields:
        setattr(project, name, dock[name])
    project.save(update_fields=fields + ["updated_at"])
    adjusted = []
    for scene in scenes:
        update = []
        cfg = scene_config(scene, memo)
        caps = model_caps(cfg.model, memo)
        if scene.duration and caps is not None and caps.durations and scene.duration not in caps.durations:
            fixed = clamp_duration(caps.durations, scene.duration)
            adjusted.append({"field": "duration", "scene": scene.pk, "from": scene.duration, "to": fixed,
                             "message": f"Сцена {scene.order + 1}: {scene.duration} с не снять — "
                                        f"выбрано {fixed} с"})
            scene.duration = fixed
            update.append("duration")
            cfg = scene_config(scene, memo)
        if (scene.status != CartoonScene.STATUS_READY and scene.video_prompt
                and cfg.duration != before[scene.pk]):
            scene.video_prompt = ""
            scene.video_negative = ""
            update += ["video_prompt", "video_negative"]
        if update:
            scene.save(update_fields=update + ["updated_at"])
    return adjusted


class ProjectScenesView(StudioAPIView):
    """POST — добавить сцену в конец таймлайна. Генерация — отдельным запросом.

    Клиент: «набрал пользователь три сцены — они появились в ленте, и уже из
    ленты он генерирует любую». Поэтому здесь ничего не считается и не
    списывается: сцена просто встаёт в ленту черновиком.
    """

    def post(self, request, pk):
        project = get_object_or_404(CartoonProject, pk=pk, user=request.user)
        custom_text, error = _custom_text(request.data.get("custom_text"))
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        if custom_text:
            # Своя сцена: человек описал, что делает герой. Ничего не
            # генерируется и не списывается — сцена встаёт в ленту черновиком.
            try:
                preset = _custom_preset()
            except RuntimeError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            preset = CartoonPreset.objects.filter(
                pk=request.data.get("preset_id"), is_active=True
            ).select_related("image_model", "video_model").first()
            if not preset or preset.slug == _custom_slug():
                return Response({"detail": "Сцена не найдена"}, status=status.HTTP_400_BAD_REQUEST)

        last = project.scenes.order_by("-order").first()
        scene = CartoonScene.objects.create(
            project=project, preset=preset,
            character=_pick_character(request, request.data.get("character_id")),
            order=(last.order + 1) if last else 0,
            status=CartoonScene.STATUS_DRAFT,
            custom_text=custom_text,
            custom_title=custom_text[:60],
            dialogue=_dialogue(request.data.get("dialogue")),
        )
        _attach_ready_keyframe(scene)
        return Response(scene_json(scene, _lang(request)), status=status.HTTP_201_CREATED)


STUDIO_ASPECTS = ("16:9", "9:16", "1:1")


def _aspect(raw) -> str:
    """Формат мультфильма: вертикальный, горизонтальный или квадрат.

    Клиент: выбранный формат применяется ко ВСЕМ сценам серии, чтобы при
    склейке они были одинакового размера.
    """
    from ai.aspect import normalize

    value = normalize(raw) or ""
    return value if value in STUDIO_ASPECTS else "16:9"


def _dialogue(raw) -> str:
    """Реплика героя: одна строка, до 300 символов, на языке человека."""
    return " ".join(str(raw or "").split())[:300]


def _custom_slug() -> str:
    from .services import CUSTOM_PRESET_SLUG

    return CUSTOM_PRESET_SLUG


def _custom_preset():
    from .services import custom_base_preset

    return custom_base_preset()


def _custom_text(raw) -> tuple[str, str]:
    """Описание своей сцены из запроса: (текст, ошибка). Пусто — не своя сцена."""
    from .services import CUSTOM_TEXT_MAX, CUSTOM_TEXT_MIN

    text = " ".join(str(raw or "").split())
    if not text:
        return "", ""
    if len(text) < CUSTOM_TEXT_MIN:
        return "", "Опишите сцену хотя бы парой слов"
    if len(text) > CUSTOM_TEXT_MAX:
        return "", f"Описание длиннее {CUSTOM_TEXT_MAX} символов — сократите"
    return text, ""


def _attach_ready_keyframe(scene) -> None:
    """Подставить готовый кадр «герой в сцене», если он уже нарисован.

    Такой кадр лежит в общем запасе и ничего не стоит. Человек добавил сцену и
    сразу видит в ленте своего героя, а не обложку с чужим, — и при съёмке за
    этот кадр не платит: он же пойдёт первым.
    """
    from .models import CartoonKeyframe

    character = scene.character or scene.project.character
    # У своей сцены общего кадра нет: служебный пресет у всех один.
    if not character or scene.keyframe or scene.custom_text:
        return
    ready = CartoonKeyframe.objects.filter(
        preset_id=scene.preset_id, character=character,
        aspect_ratio=scene.project.aspect_ratio or "16:9").first()
    if ready and ready.image:
        scene.keyframe = ready.image
        scene.save(update_fields=["keyframe", "updated_at"])


def _pick_character(request, character_id):
    """Герой из запроса: библиотечный или свой. Чужого не отдаём."""
    if not character_id:
        return None
    # Из тела запроса может прийти что угодно: «abc», огромное число, список.
    try:
        character_id = int(character_id)
    except (TypeError, ValueError):
        return None
    if not (0 < character_id < 2 ** 31):
        return None
    library = Q(is_public=True, user__isnull=True)
    mine = Q(user=request.user) if request.user.is_authenticated else Q(pk__in=[])
    return CartoonCharacter.objects.filter(library | mine).filter(pk=character_id).first()


class PreviewsView(StudioPublicAPIView):
    """GET — всё готовое по герою: кадры и ролики пар «герой в сцене».

    {preset_id: {"frame": url, "video": url}}. Ролик — движущееся превью
    сцены с этим героем, кадр — запасной вариант, пока ролика нет. И то и
    другое уже нарисовано и отдаётся бесплатно, поэтому витрина подставляет
    их сразу при выборе героя.

    Отдельно от keyframes/: тем эндпоинтом пользуется бот, и его ответ менять
    нельзя.
    """

    def get(self, request):
        character = _pick_character(request, request.query_params.get("character_id"))
        if not character:
            return Response({})

        from .models import CartoonKeyframe, CartoonPairVideo

        out: dict = {}
        # Кадры своего формата: вертикальному мультфильму горизонтальные не
        # показываем — человек увидел бы не то, что получит.
        aspect = _aspect(request.query_params.get("aspect_ratio"))
        for r in (CartoonKeyframe.objects.filter(character=character, aspect_ratio=aspect)
                  .exclude(image="")):
            out.setdefault(str(r.preset_id), {"frame": "", "video": ""})["frame"] = _media(r.image)
        # Ролики — тоже своего формата: раньше вертикальный показывался в горизонтальном.
        for r in CartoonPairVideo.objects.filter(character=character, aspect_ratio=aspect).exclude(video=""):
            out.setdefault(str(r.preset_id), {"frame": "", "video": ""})["video"] = _pair_video_url(r)
        return Response(out)


class KeyframesView(StudioPublicAPIView):
    """GET — какие сцены уже нарисованы с этим героем.

    Такие кадры отдаются бесплатно и мгновенно, поэтому витрина подставляет их
    в карточки сама: человек выбрал героя и сразу видит его в тех сценах, где
    пара уже встречалась. Остальные рисуются по кнопке.
    """

    def get(self, request):
        character = _pick_character(request, request.query_params.get("character_id"))
        if not character:
            return Response({})

        from .models import CartoonKeyframe

        rows = CartoonKeyframe.objects.filter(character=character).exclude(image="")
        return Response({str(r.preset_id): _media(r.image) for r in rows})


class PresetTryOnView(StudioPublicAPIView):
    """POST — показать сцену с выбранным героем ещё до съёмки.

    Клиент: «выбрал кота — и видно, как он будет выглядеть в сцене». Рисуем тот
    же кадр, с которого потом начнётся сама сцена, поэтому дважды за него не
    платят: при съёмке он берётся из запаса.

    Уже нарисованная пара «сцена + герой» отдаётся бесплатно и мгновенно —
    героев в библиотеке два десятка, и такие пары быстро повторяются у разных
    людей.
    """

    def post(self, request, pk):
        preset = CartoonPreset.objects.filter(
            pk=pk, is_active=True).select_related("image_model").first()
        if not preset:
            return Response({"detail": "Сцена не найдена"},
                            status=status.HTTP_400_BAD_REQUEST)

        character = _pick_character(request, request.data.get("character_id"))
        if not character:
            return Response({"detail": "Сначала выберите героя"},
                            status=status.HTTP_400_BAD_REQUEST)

        from .models import CartoonKeyframe

        # Формат: вертикальный мультфильм примеряет вертикальный кадр.
        aspect = _aspect((request.data or {}).get("aspect_ratio")
                         if isinstance(request.data, dict) else None)
        ready = CartoonKeyframe.objects.filter(preset=preset, character=character,
                                               aspect_ratio=aspect).first()
        if ready and ready.image:
            return Response({"image": _media(ready.image), "charged": 0})

        # Гость: одна примерка без входа, дальше — регистрация. Готовые пары
        # выше отдаются всем и всегда, в лимит они не входят: они ничего не стоят.
        if not request.user.is_authenticated:
            return _guest_try_on(request, preset, character, aspect)

        price = _tryon_price(preset)
        balance = _free_balance(request.user)
        if balance < price:
            return Response({"detail": "Недостаточно кредитов", "required": price,
                             "balance": balance}, status=status.HTTP_402_PAYMENT_REQUIRED)

        from .services import get_or_create_keyframe

        try:
            path, charged = get_or_create_keyframe(preset, character, request.user, aspect)
        except Exception as exc:
            logger.exception("примерка героя: кадр не нарисовался")
            return _image_failure(exc)
        return Response({"image": _media(path), "charged": charged})


def _guest_try_on(request, preset, character, aspect: str = "16:9") -> Response:
    """Бесплатная примерка для гостя — одна на устройство.

    Ответ «нужен вход» отдаём 403 с need_auth, а не 401: на 401 фронт пробует
    обновить токен и может увести человека со страницы, а здесь нужно только
    показать окно «ваш проект сохранится».
    """
    from django.conf import settings as dj_settings
    from django.core.cache import cache
    from django.db import IntegrityError
    from django.utils import timezone
    from datetime import timedelta

    from adminapi.runtime import get_runtime
    from users.antifraud import get_client_ip

    from .models import CartoonGuestTryOn
    from .services import get_or_create_keyframe

    def need_auth(reason: str) -> Response:
        return Response({"detail": "Войдите, чтобы продолжить примерку",
                         "need_auth": True, "reason": reason},
                        status=status.HTTP_403_FORBIDDEN)

    device_key = (request.headers.get("X-Device-Key") or "").strip()[:64]
    # Без ключа устройства лимит «одна на устройство» не посчитать — значит,
    # и бесплатной примерки нет: иначе она бесконечна.
    if len(device_key) < 16:
        return need_auth("no_device")
    if CartoonGuestTryOn.objects.filter(device_key=device_key).exists():
        return need_auth("used")

    since = timezone.now() - timedelta(hours=24)
    ip = get_client_ip(request)
    per_ip = int(getattr(dj_settings, "STUDIO_GUEST_TRYON_PER_IP_DAY", 3))
    if ip and CartoonGuestTryOn.objects.filter(ip=ip, created_at__gte=since).count() >= per_ip:
        return need_auth("ip_limit")
    try:
        cap = int(get_runtime("studio_guest_tryon_daily_cap",
                              getattr(dj_settings, "STUDIO_GUEST_TRYON_DAILY_CAP", 100)))
    except (TypeError, ValueError):
        cap = int(getattr(dj_settings, "STUDIO_GUEST_TRYON_DAILY_CAP", 100))
    if CartoonGuestTryOn.objects.filter(created_at__gte=since).count() >= cap:
        return need_auth("daily_cap")

    # Две вкладки одного гостя разом не должны получить два бесплатных кадра:
    # запись о примерке появляется только после рисования, а рисование долгое.
    lock = f"studio:guest-tryon:{device_key}"
    if not cache.add(lock, "1", timeout=180):
        return Response({"detail": "Кадр уже рисуется — подождите несколько секунд",
                         "busy": True}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        path, _ = get_or_create_keyframe(preset, character, user=None, aspect=aspect)
        try:
            CartoonGuestTryOn.objects.create(
                device_key=device_key, ip=ip or None, preset=preset, character=character)
        except IntegrityError:
            pass
    except Exception as exc:
        logger.exception("бесплатная примерка гостя: кадр не нарисовался")
        return _image_failure(exc)
    finally:
        cache.delete(lock)
    return Response({"image": _media(path), "charged": 0, "free": True})


def _scene_quote(scene, *, keyframe_ready: bool):
    """Настройки дока сцены сейчас и цена по ним: (ShotConfig, ScenePrice).

    В режиме markup цена — в формате мультфильма; без себестоимости — PriceUnavailable.
    """
    from .pricing import config_price, scene_config

    config = scene_config(scene)
    return config, config_price(scene.preset, config, keyframe_ready=keyframe_ready)


def _scene_price(scene, *, keyframe_ready: bool, quote=None) -> int:
    """Во сколько обойдётся съёмка сцены ПРЯМО СЕЙЧАС.

    Готовый кадр заново не рисуется (см. tasks.render_scene), поэтому при
    пересъёмке с ним платится только видео-часть. Считаем той же формулой,
    что и списание в задаче (через снимок): разойдись гейт со счётом — человек
    либо не смог бы переснять при достаточном балансе, либо ушёл бы в минус.
    quote — уже посчитанный _scene_quote.
    """
    _config, price = quote or _scene_quote(scene, keyframe_ready=keyframe_ready)
    return price.video if keyframe_ready else price.total


def _human(exc, what: str = "image") -> str:
    from .services import human_error

    return human_error(exc, what)


def _image_failure(exc, what: str = "image") -> Response:
    """Модель картинок не нарисовала. Ничего не списано: списание — после картинки.

    Отказ модерации — 422 со словами «опишите по-другому»: повторять то же самое
    бессмысленно. Остальное — 502 «попробуйте ещё раз».
    """
    from .services import image_blocked

    blocked = image_blocked(exc)
    return Response({"detail": _human(exc, what), "refused": blocked},
                    status=(status.HTTP_422_UNPROCESSABLE_ENTITY if blocked
                            else status.HTTP_502_BAD_GATEWAY))


def _no_credits(need: int, balance: int, reserved: int = 0) -> Response:
    body = {"detail": "Недостаточно кредитов", "required": need, "balance": balance}
    if reserved:
        # Часть баланса уже обещана сценам, которые снимаются прямо сейчас.
        body["reserved"] = reserved
        body["detail"] = ("Недостаточно кредитов: часть баланса уже занята генерациями, "
                          "которые сейчас идут (сцены и видео)")
    return Response(body, status=status.HTTP_402_PAYMENT_REQUIRED)


WORKING_STATUSES = (CartoonScene.STATUS_NEW, CartoonScene.STATUS_KEYFRAME,
                    CartoonScene.STATUS_VIDEO)


def _enqueue_render(scene_id: int) -> None:
    """Поставить задачу съёмки. Вызывается после коммита: задача забирает сцену
    только из «Ожидает», и до коммита она бы этого состояния не увидела."""
    from django.utils import timezone

    try:
        render_scene.delay(scene_id)
    except Exception:
        logger.exception("сцена %s: задача съёмки не поставилась", scene_id)
        CartoonScene.objects.filter(pk=scene_id, status=CartoonScene.STATUS_NEW).update(
            status=CartoonScene.STATUS_FAILED, error="Очередь занята — попробуйте через минуту",
            updated_at=timezone.now())


def _prompt_seconds(scene) -> int:
    """Под какую длительность собран кэш промпта съёмки: прошлый снимок, а у сцен
    до снимков — длительность пресета (её и передавала задача)."""
    if scene.shot_duration:
        return int(scene.shot_duration)
    return int(scene.preset.duration or 5)


class _BadQuote(Exception):
    """quoted_credits прислали, но не числом."""


def _quoted_credits(request) -> int | None:
    """Цена, которую человек видел на кнопке «Снять» (quoted_credits).

    None — клиент цену не прислал (старый сайт или бот): снимаем, как раньше.
    Кривое значение — ошибка запроса, а не повод снять вслепую.
    """
    data = request.data if isinstance(request.data, dict) else {}
    raw = data.get("quoted_credits")
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise _BadQuote
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    elif isinstance(raw, str) and raw.strip().isascii() and raw.strip().isdigit():
        raw = int(raw.strip())
    if not isinstance(raw, int) or raw < 0:
        raise _BadQuote
    return raw


def _bad_quote() -> Response:
    text = "Цена на кнопке — целым числом кредитов. Обновите страницу и попробуйте снова."
    return Response({"detail": text, "error": text, "error_code": "invalid_quote",
                     "field": "quoted_credits"}, status=status.HTTP_400_BAD_REQUEST)


def _price_changed(scene, need: int, quoted: int, lang: str) -> Response:
    """409: «Снять» сейчас стоит больше, чем было на кнопке. Ничего не снято и не занято."""
    text = f"Цена изменилась: теперь {need} кр. Проверьте и нажмите «Снять» ещё раз."
    return Response({"detail": text, "error": text, "error_code": "price_changed",
                     "credits": need, "quoted": quoted, "scene": scene_json(scene, lang)},
                    status=status.HTTP_409_CONFLICT)


def _already_shot(scene, lang: str) -> Response:
    """409: сцена уже снята. «Снять» из устаревшей вкладки или старой кнопки бота
    иначе переснимал бы готовый ролик без вопроса и списывал второй раз."""
    text = "Сцена уже снята — переснять можно кнопкой «Переснять»"
    return Response({"detail": text, "error": text, "error_code": "already_shot",
                     "scene": scene_json(scene, lang)}, status=status.HTTP_409_CONFLICT)


# Из каких состояний «Снять» берёт сцену: первая съёмка — только не снятые;
# пересъёмка (PATCH retry) — ещё и готовую, её клиент подтверждает сам.
FIRST_SHOT_STATUSES = (CartoonScene.STATUS_DRAFT, CartoonScene.STATUS_FAILED)
RESHOOT_STATUSES = FIRST_SHOT_STATUSES + (CartoonScene.STATUS_READY,)
SCENE_STATUSES = {value for value, _ in CartoonScene.STATUS_CHOICES}


class _BadExpect(Exception):
    """expect_status прислали, но это не состояние сцены."""


def _expected_status(request) -> str | None:
    """Состояние сцены, которое человек видел, когда жал ↻ (expect_status).

    None — клиент его не прислал (бот, старый сайт): пересъёмка как раньше.
    """
    data = request.data if isinstance(request.data, dict) else {}
    raw = data.get("expect_status")
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or raw not in SCENE_STATUSES:
        raise _BadExpect
    return raw


def _expected_shot(request) -> str | None:
    """Метка ролика, который был в меню готовой сцены (expect_shot, см. shot_token).

    None — клиент её не прислал: как раньше. Не короткая строка из hex — отказ.
    """
    data = request.data if isinstance(request.data, dict) else {}
    raw = data.get("expect_shot")
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or len(raw) > 16 or not all(c in "0123456789abcdef" for c in raw):
        raise _BadExpect
    return raw


def _bad_expect(field: str = "expect_status") -> Response:
    text = "Состояние сцены на странице устарело. Обновите страницу и попробуйте снова."
    return Response({"detail": text, "error": text, "error_code": "invalid_expect_status",
                     "field": field}, status=status.HTTP_400_BAD_REQUEST)


def _scene_changed(scene, lang: str) -> Response:
    """409: кнопка из меню готовой сцены, а сцену с тех пор переснимают или пересъёмка
    не удалась. Ничего не снято и не списано — клиент покажет сцену как она есть."""
    text = "Сцену уже переснимали — проверьте её и нажмите ещё раз"
    return Response({"detail": text, "error": text, "error_code": "scene_changed",
                     "scene": scene_json(scene, lang)}, status=status.HTTP_409_CONFLICT)


def _queue_render(request, scene, *, new_keyframe: bool = False, quoted: int | None = None,
                  allowed: tuple = RESHOOT_STATUSES, expect_video: str | None = None) -> Response:
    """Отправить сцену в съёмку: проверить баланс и перевести её в «Ожидает».

    Две вещи, из-за которых раньше терялись деньги:
      * баланс проверялся по каждой сцене отдельно, а списание идёт в конце
        съёмки — две сцены при балансе на одну обе проходили проверку, вторая
        снималась за наш счёт и падала на списании. Теперь из баланса вычитается
        цена сцен, которые уже снимаются (pricing.reserved_credits);
      * проверка и смена состояния шли порознь — два запроса разом ставили две
        задачи. Теперь строка пользователя под замком, а сцена переводится
        условным UPDATE.

    quoted — цена, которую человек видел на кнопке. Цена сцены зависит от дока
    мультфильма, а его меняют с любого устройства (и модель может выключить
    админ): выросла — 409 price_changed, ничего не меняем. Стала ниже (кадр
    нашёлся в общем запасе) — снимаем молча: это в пользу человека.

    allowed — из каких состояний условный UPDATE заберёт сцену. Первая съёмка
    готовую не берёт, даже если она стала готовой между чтением и UPDATE:
    тогда 409 already_shot, а не вторая съёмка без вопроса.

    expect_video — пересъёмка именно этого ролика (кнопка меню готовой сцены в
    боте): пересняли его между чтением и UPDATE — 409 already_shot.
    """
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from django.utils import timezone

    from ai.pricing import PriceUnavailable
    # Дубли видеостудии и склейки в работе тоже держат баланс.
    from vstudio.reserve import merge_reserved, vstudio_reserved

    from .models import CartoonKeyframe
    from .pricing import reserved_credits, snapshot_fields

    lang = _lang(request)
    character = scene.character or scene.project.character
    if not new_keyframe:
        # Кадр, который человек уже видел в примерке (и оплатил), съёмка возьмёт
        # из общего запаса — платить за кадр второй раз не придётся.
        _attach_ready_keyframe(scene)
    keyframe_ready = bool(scene.keyframe) and not new_keyframe
    try:
        config, price = quote = _scene_quote(scene, keyframe_ready=keyframe_ready)
        need = _scene_price(scene, keyframe_ready=keyframe_ready, quote=quote)
    except PriceUnavailable as exc:
        return _price_unavailable(exc)
    if quoted is not None and need > quoted:
        return _price_changed(scene, need, quoted, lang)
    with transaction.atomic():
        # Строка пользователя под замком: два «Снять» разом иначе увидели бы
        # один и тот же свободный остаток.
        locked = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        balance = int(getattr(locked, "token_balance", 0) or 0)
        reserved = (reserved_credits(request.user, exclude_scene_id=scene.pk)
                    + vstudio_reserved(request.user) + merge_reserved(request.user))
        free = max(0, balance - reserved)
        if free < need:
            return _no_credits(need, free, reserved)
        # Снимок настроек и цены: съёмка, резерв и списание идут по нему, смена
        # дока после «Снять» эту сцену уже не меняет (pricing.shot_config).
        fields = {"status": CartoonScene.STATUS_NEW, "error": "", "updated_at": timezone.now(),
                  **snapshot_fields(config, price, keyframe_ready=keyframe_ready),
                  # Резерв держит ровно то, что проверили выше.
                  "credits_planned": need}
        if scene.video_prompt and config.duration != _prompt_seconds(scene):
            # Промпт съёмки собран под прежнюю длительность (биты «0-2 с…») — соберём заново.
            fields["video_prompt"] = ""
            fields["video_negative"] = ""
        if new_keyframe:
            fields["keyframe"] = ""
        target = CartoonScene.objects.filter(pk=scene.pk, status__in=allowed)
        if expect_video is not None:
            target = target.filter(video=expect_video)
        claimed = target.update(**fields)
        if claimed and new_keyframe and character and not scene.custom_text:
            # Новый кадр — значит, и не из общего запаса: иначе съёмка взяла бы
            # тот же неудачный кадр пары. Только после проверки баланса: при
            # отказе «не хватает кредитов» ничего не должно пропасть.
            CartoonKeyframe.objects.filter(preset_id=scene.preset_id, character=character).delete()
    if claimed:
        transaction.on_commit(lambda pk=scene.pk: _enqueue_render(pk))
    scene.refresh_from_db()
    if not claimed and scene.status == CartoonScene.STATUS_READY and (
            scene.status not in allowed or (expect_video is not None and scene.video != expect_video)):
        return _already_shot(scene, lang)
    if not claimed and expect_video is not None:
        return _scene_changed(scene, lang)
    return Response(scene_json(scene, lang))


class SceneFrameView(StudioAPIView):
    """POST — нарисовать кадр своей сцены до съёмки: увидеть, что получится.

    Клиент: «перед запуском генерации человек уже должен видеть, что именно
    получится». У сцены из библиотеки для этого есть примерка, у своей — эта
    кнопка. Кадр потом идёт первым кадром съёмки, дважды за него не платят.
    """

    def post(self, request, pk):
        from .services import CustomSceneRejected, draw_custom_keyframe

        scene = get_object_or_404(
            CartoonScene.objects.select_related(
                "preset__image_model", "preset__video_model", "project__character", "character"),
            pk=pk, project__user=request.user)
        if not scene.custom_text:
            return Response({"detail": "Кадр по кнопке — только у своей сцены"},
                            status=status.HTTP_400_BAD_REQUEST)
        if scene.keyframe:
            return Response(scene_json(scene, _lang(request)))
        if scene.status not in (CartoonScene.STATUS_DRAFT, CartoonScene.STATUS_FAILED):
            return Response({"detail": "Сцена уже снимается"}, status=status.HTTP_400_BAD_REQUEST)
        character = scene.character or scene.project.character
        if not character:
            return Response({"detail": "Сначала выберите героя"}, status=status.HTTP_400_BAD_REQUEST)

        need = _tryon_price(scene.preset)
        balance = _free_balance(request.user)
        if balance < need:
            return _no_credits(need, balance)
        try:
            # Формат мультфильма: без него кадр своей сцены рисовался в формате
            # пресета и потом не совпадал с остальными сценами.
            scene.keyframe, price = draw_custom_keyframe(scene, character, request.user,
                                                         scene.project.aspect_ratio or "16:9")
        except CustomSceneRejected as exc:
            return Response({"detail": str(exc), "rejected": True},
                            status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception("своя сцена %s: кадр не нарисовался", scene.pk)
            return _image_failure(exc)
        scene.credits_spent += price
        scene.error = ""
        scene.save(update_fields=["keyframe", "credits_spent", "error", "updated_at"])
        return Response(scene_json(scene, _lang(request)))


class SceneRenderView(StudioAPIView):
    """POST — снять сцену из ленты. Здесь и происходит проверка баланса.

    Отделено от добавления сознательно: деньги списываются в момент, когда
    человек осознанно нажал «Снять», а не когда он собирал ленту.

    Только первая съёмка: готовую сцену переснимают через PATCH {retry} (сайт
    спрашивает, бот показывает цену на кнопке). Иначе «Снять» из старой вкладки
    или из старого меню бота переснимал готовый ролик и списывал второй раз.
    """

    def post(self, request, pk):
        scene = get_object_or_404(
            CartoonScene.objects.select_related("preset__image_model", "preset__video_model"),
            pk=pk, project__user=request.user)
        try:
            quoted = _quoted_credits(request)
        except _BadQuote:
            return _bad_quote()
        if scene.status in WORKING_STATUSES:
            return Response(scene_json(scene, _lang(request)))
        if scene.status == CartoonScene.STATUS_READY:
            return _already_shot(scene, _lang(request))
        return _queue_render(request, scene, quoted=quoted, allowed=FIRST_SHOT_STATUSES)


class SceneDetailView(StudioAPIView):
    """PATCH — переставить в таймлайне или пересобрать. DELETE — убрать."""

    def patch(self, request, pk):
        scene = get_object_or_404(
            CartoonScene.objects.select_related("preset__image_model", "preset__video_model",
                                                "project__video_model"),
            pk=pk, project__user=request.user)

        quoted = None
        expected = None
        expected_shot = None
        if request.data.get("retry"):
            # Цену с кнопки разбираем до любых правок: кривая — не меняем ничего.
            try:
                quoted = _quoted_credits(request)
            except _BadQuote:
                return _bad_quote()
            try:
                expected = _expected_status(request)
            except _BadExpect:
                return _bad_expect()
            try:
                expected_shot = _expected_shot(request)
            except _BadExpect:
                return _bad_expect("expect_shot")
            if (expected is not None and expected != CartoonScene.STATUS_READY
                    and scene.status == CartoonScene.STATUS_READY):
                # ↻ нажали у строки «ошибка», а сцену с тех пор пересняли (другая
                # вкладка, бот): готовый ролик без вопроса не заменяем.
                return _already_shot(scene, _lang(request))
            if expected_shot is not None and (scene.status != CartoonScene.STATUS_READY
                                              or shot_token(scene) != expected_shot):
                # Кнопка из меню готовой сцены в боте, а сцену с тех пор пересняли
                # (этой же кнопкой, на сайте) или переснимают: второй раз не снимаем.
                if scene.status == CartoonScene.STATUS_READY:
                    return _already_shot(scene, _lang(request))
                return _scene_changed(scene, _lang(request))

        if "duration" in request.data:
            # Своя длительность сцены — в пределах модели, которой сцена снимется.
            # У снятой сцены меняется только следующая съёмка (новая, платная).
            if scene.status in WORKING_STATUSES:
                return Response({"detail": "Сцена уже снимается — длительность не поменять",
                                 "error_code": "scene_busy"}, status=status.HTTP_400_BAD_REQUEST)
            from .pricing import scene_config
            from .serializers import SettingsError, parse_scene_duration

            memo: dict = {}
            try:
                duration = parse_scene_duration(request.data.get("duration"), scene, memo=memo)
            except SettingsError as exc:
                return Response(exc.payload(), status=exc.status)
            before = scene_config(scene, memo).duration
            scene.duration = duration
            update = ["duration"]
            # Промпт съёмки разложен по секундам прежней длины — соберём заново. У
            # готовой сцены не трогаем: пустой промпт там значит «реплику меняли после
            # съёмки» (panel.publish_block); его сверит «Снять» (_queue_render).
            if (scene.status != CartoonScene.STATUS_READY and scene.video_prompt
                    and scene_config(scene, memo).duration != before):
                scene.video_prompt = ""
                scene.video_negative = ""
                update += ["video_prompt", "video_negative"]
            scene.save(update_fields=update + ["updated_at"])

        if "order" in request.data:
            try:
                scene.order = max(0, int(request.data["order"]))
                scene.save(update_fields=["order", "updated_at"])
            except (TypeError, ValueError):
                return Response({"detail": "Неверная позиция"},
                                status=status.HTTP_400_BAD_REQUEST)

        if "character_id" in request.data:
            # Менять героя можно, пока сцена не снята: после съёмки это была бы
            # уже другая сцена, а деньги за неё уже списаны.
            if scene.status not in (CartoonScene.STATUS_DRAFT, CartoonScene.STATUS_FAILED):
                return Response({"detail": "Сцена уже снимается — героя не сменить"},
                                status=status.HTTP_400_BAD_REQUEST)
            scene.character = _pick_character(request, request.data.get("character_id"))
            # Кадр рисовался под прежнего героя, с новым он не годится.
            scene.keyframe = ""
            scene.video_prompt = ""
            scene.save(update_fields=["character", "keyframe", "video_prompt", "updated_at"])
            _attach_ready_keyframe(scene)

        # «Кадр заново» без съёмки: кадр мог получиться неудачным (герой не
        # тот, поза не та), и заменить его до сих пор было нечем — оставалось
        # удалять сцену. Сам кадр потом рисует примерка, за свою цену.
        if request.data.get("new_keyframe") and not request.data.get("retry"):
            if scene.status not in (CartoonScene.STATUS_DRAFT, CartoonScene.STATUS_FAILED):
                return Response({"detail": "Сцена уже снимается — кадр не поменять"},
                                status=status.HTTP_400_BAD_REQUEST)
            if scene.keyframe:
                scene.keyframe = ""
                scene.save(update_fields=["keyframe", "updated_at"])
            # Общий кадр этой пары «герой + сцена» тоже неудачный — иначе
            # примерка вернула бы ту же картинку из кэша.
            character = scene.character or scene.project.character
            if character and not scene.custom_text:
                from .models import CartoonKeyframe

                CartoonKeyframe.objects.filter(preset_id=scene.preset_id,
                                               character=character).delete()
            return Response(scene_json(scene, _lang(request)))

        if "dialogue" in request.data:
            # У готовой сцены реплику тоже можно вписать: рот двигается только
            # когда её произносит сама модель, и такую сцену потом переснимают.
            if scene.status not in (CartoonScene.STATUS_DRAFT, CartoonScene.STATUS_FAILED,
                                    CartoonScene.STATUS_READY):
                return Response({"detail": "Сцена уже снимается — реплику не поменять"},
                                status=status.HTTP_400_BAD_REQUEST)
            scene.dialogue = _dialogue(request.data.get("dialogue"))
            # Промпт съёмки собран под прежнюю реплику — соберём заново.
            scene.video_prompt = ""
            scene.video_negative = ""
            scene.save(update_fields=["dialogue", "video_prompt", "video_negative", "updated_at"])

        if request.data.get("retry"):
            # Сцена уже в работе — второй задачи не ставим: обе сняли бы видео и
            # обе списали бы деньги, а человек видел бы одну сцену.
            if scene.status in (CartoonScene.STATUS_NEW, CartoonScene.STATUS_KEYFRAME,
                                CartoonScene.STATUS_VIDEO):
                return Response(scene_json(scene, _lang(request)))

            # Пересборка идёт с УЖЕ готовым кадром, если он есть: так персонаж
            # и композиция не сдвинутся, а заплатит человек только за видео.
            # Баланс проверяем ЗДЕСЬ, а не в задаче: провайдеру за генерацию мы
            # платим сразу, а списание в Celery упало бы уже после — видео
            # потеряно, деньги студии сгорели.
            # Видел не готовую — и UPDATE готовую не заберёт, даже если она стала
            # готовой прямо сейчас.
            allowed = (RESHOOT_STATUSES if expected in (None, CartoonScene.STATUS_READY)
                       else FIRST_SHOT_STATUSES)
            expect_video = None
            if expected_shot is not None:
                # Пересъёмка ровно того ролика, что был в меню: UPDATE берёт только его.
                allowed, expect_video = (CartoonScene.STATUS_READY,), scene.video
            return _queue_render(request, scene, new_keyframe=bool(request.data.get("new_keyframe")),
                                 quoted=quoted, allowed=allowed, expect_video=expect_video)

        return Response(scene_json(scene, _lang(request)))

    def delete(self, request, pk):
        scene = get_object_or_404(CartoonScene, pk=pk, project__user=request.user)
        # Снимающуюся сцену не удаляем: задача доснимет ролик, а сохранить его
        # будет некуда — провайдеру заплачено, человеку выдать нечего.
        if scene.status in WORKING_STATUSES:
            return Response({"detail": "Сцена сейчас снимается — удалить её можно, когда съёмка закончится"},
                            status=status.HTTP_400_BAD_REQUEST)
        project = scene.project
        scene.delete()
        # Уплотняем порядок, чтобы в таймлайне не осталось дырок.
        for i, s in enumerate(project.scenes.order_by("order", "id")):
            if s.order != i:
                s.order = i
                s.save(update_fields=["order"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectAssembleView(StudioAPIView):
    """POST — склеить готовые сцены в один ролик. Бесплатно."""

    def post(self, request, pk):
        from django.db import transaction
        from django.utils import timezone

        project = get_object_or_404(CartoonProject, pk=pk, user=request.user)
        ready = project.scenes.filter(status=CartoonScene.STATUS_READY).exclude(video="").count()
        if not ready:
            return Response({"detail": "Нет готовых сцен"}, status=status.HTTP_400_BAD_REQUEST)
        # «Собирается» — сразу и условно. Раньше ответ приходил со старым
        # состоянием: фронт не показывал крутилку, человек жал ещё раз, и в
        # очередь вставали две склейки. Уже собирается — вторую не ставим.
        # Отметка начала сбрасывается: пока задача не взялась, склейка стоит в
        # очереди, и уборка ждёт её дольше (tasks.fail_stale_work).
        started = CartoonProject.objects.filter(pk=project.pk).exclude(
            status=CartoonProject.STATUS_ASSEMBLING).update(
            status=CartoonProject.STATUS_ASSEMBLING, error="", assembly_started_at=None,
            updated_at=timezone.now())
        if started:
            transaction.on_commit(lambda pk=project.pk: _enqueue_assembly(pk))
        project.refresh_from_db()
        return Response(project_json(project, _lang(request)), status=status.HTTP_202_ACCEPTED)


def _enqueue_assembly(project_id: int) -> None:
    from django.utils import timezone

    try:
        assemble_movie.delay(project_id)
    except Exception:
        logger.exception("мультфильм %s: задача склейки не поставилась", project_id)
        CartoonProject.objects.filter(pk=project_id, status=CartoonProject.STATUS_ASSEMBLING).update(
            status=CartoonProject.STATUS_FAILED, error="Очередь занята — попробуйте собрать через минуту",
            updated_at=timezone.now())
