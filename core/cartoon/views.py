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


def preset_json(p: CartoonPreset, lang: str = "ru", aspect: str | None = None) -> dict:
    """Пользователю — только витрина: название, превью, длительность и цена.
    Промпты и модели наружу не отдаём: это внутренняя кухня студии.

    aspect — формат мультфильма человека: в режиме цен markup квадрат дешевле
    16:9. Цены нет (себестоимость неизвестна) — credits None и price_unavailable.
    """
    from .pricing import scene_credits_or_none

    credits = scene_credits_or_none(p, aspect=aspect)
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
        "duration": p.duration,
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
    """Ролики пар для сцен проекта одним запросом: {(сцена, герой): url}."""
    from .models import CartoonPairVideo

    keys = set()
    for s in scenes:
        if s.custom_text:
            continue
        hero_id = s.character_id or (s.project.character_id if s.project_id else None)
        if s.preset_id and hero_id:
            keys.add((s.preset_id, hero_id))
    if not keys:
        return {}
    rows = CartoonPairVideo.objects.filter(
        preset_id__in={k[0] for k in keys}, character_id__in={k[1] for k in keys})
    return {(r.preset_id, r.character_id): _pair_video_url(r)
            for r in rows if (r.preset_id, r.character_id) in keys}


def scene_json(s: CartoonScene, lang: str = "ru", pair_videos: dict | None = None) -> dict:
    from ai.pricing import PriceUnavailable

    from .pricing import frame_credits, scene_video_credits

    hero_id = s.character_id or s.project.character_id
    if pair_videos is None:
        pair_videos = _pair_videos_for([s])
    custom = bool(s.custom_text)
    # Та же формула, что у проверки баланса и списания (pricing.scene_credits),
    # в формате мультфильма. Цены нет (markup без себестоимости) — None.
    try:
        video_price = scene_video_credits(s.preset, aspect=s.project.aspect_ratio) if s.preset_id else 0
    except PriceUnavailable:
        video_price = None
    frame_price = frame_credits(s.preset.image_model) if s.preset_id else 0
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
                   "duration": s.preset.duration if s.preset_id else 0,
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
                           else video_price if s.keyframe else frame_price + video_price),
    }
    if video_price is None:
        row["price_unavailable"] = True
    return row


def project_json(p: CartoonProject, lang: str = "ru") -> dict:
    from django.db.models import Count, Sum

    scenes = list(p.scenes.select_related(
        "preset", "preset__image_model", "preset__video_model", "character",
        "project__character").annotate(
        audio_n=Count("audio_tracks"),
        audio_credits=Sum("audio_tracks__credits_spent")).order_by("order", "id"))
    pairs = _pair_videos_for(scenes)
    return {
        "id": p.id,
        "title": p.title,
        "status": p.status,
        "aspect_ratio": p.aspect_ratio,
        "character": character_json(p.character, lang) if p.character else None,
        "result_video": _media(p.result_video),
        "error": p.error,
        "scenes": [scene_json(s, lang, pairs) for s in scenes],
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
        presets = [preset_json(p, lang, aspect) for p in qs]
        used = {p["category"] for p in presets}
        cats = CartoonCategory.objects.filter(is_active=True)
        return Response({
            # Пустые разделы не показываем: человек ткнёт и увидит ничего.
            "categories": [category_json(c, lang) for c in cats if c.slug in used],
            "presets": presets,
            "popular": self._popular(),
        })

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

        from .pricing import scene_credits_or_none

        img = GPTModels.objects.filter(
            openrouter_id="google/gemini-2.5-flash-image", is_active=True).first()
        character = image_credits(img) if img else 4

        # Сцены без цены (режим markup, себестоимость неизвестна) не продаются —
        # в диапазон «от и до» они не входят.
        prices = sorted(
            price for price in (
                scene_credits_or_none(p)
                for p in CartoonPreset.objects.filter(is_active=True).select_related(
                    "image_model", "video_model"))
            if price is not None
        )
        if not prices:
            prices = [0]
        # Медиана, а не среднее: пара коротких сцен не должна занижать цифру,
        # по которой человек прикидывает, на сколько ему хватит пакета.
        typical = prices[len(prices) // 2]
        return Response({
            "character": character,
            "scene_min": prices[0],
            "scene_typical": typical,
            "scene_max": prices[-1],
            # Склейка идёт на нашем сервере через ffmpeg и моделям не платится.
            "assembly": 0,
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
        qs = CartoonProject.objects.filter(user=request.user).prefetch_related("scenes")[:50]
        return Response([project_json(p, _lang(request)) for p in qs])

    def post(self, request):
        char_id = request.data.get("character_id")
        character = CartoonCharacter.objects.filter(
            Q(pk=char_id) & (Q(user=request.user) | Q(is_public=True, user__isnull=True))
        ).first()
        if not character:
            return Response({"detail": "Выберите персонажа"}, status=status.HTTP_400_BAD_REQUEST)

        project = CartoonProject.objects.create(
            user=request.user,
            title=(request.data.get("title") or "Мой мультфильм").strip()[:140],
            character=character,
            aspect_ratio=_aspect(request.data.get("aspect_ratio")),
        )
        return Response(project_json(project, _lang(request)), status=status.HTTP_201_CREATED)


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

        with transaction.atomic():
            project = CartoonProject.objects.create(
                user=request.user,
                title=(str(data.get("title") or "") or "Мой мультфильм").strip()[:140],
                character=character,
                aspect_ratio=_aspect(data.get("aspect_ratio")),
                import_key=key,
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
                CartoonScene.objects.create(
                    project=project, preset=preset,
                    character=_pick_character(request, r.get("character_id")),
                    order=order, status=CartoonScene.STATUS_DRAFT,
                    custom_text=custom_text, custom_title=custom_text[:60],
                    dialogue=_dialogue(r.get("dialogue")),
                )
                order += 1

        for scene in project.scenes.select_related("project__character", "character"):
            _attach_ready_keyframe(scene)
        return Response(project_json(project, lang), status=status.HTTP_201_CREATED)


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
        return Response(project_json(project, _lang(request)))

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
        for r in CartoonPairVideo.objects.filter(character=character).exclude(video=""):
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


def _scene_price(scene, *, keyframe_ready: bool) -> int:
    """Во сколько обойдётся съёмка сцены ПРЯМО СЕЙЧАС.

    Готовый кадр заново не рисуется (см. tasks.render_scene), поэтому при
    пересъёмке с ним платится только видео-часть. Считаем той же формулой,
    что и списание в задаче: разойдись гейт со счётом — человек либо не смог бы
    переснять при достаточном балансе, либо ушёл бы в минус.

    В режиме markup цена — в формате мультфильма; без себестоимости —
    PriceUnavailable.
    """
    from .pricing import scene_credits

    return scene_credits(scene.preset, keyframe_ready=keyframe_ready,
                         aspect=scene.project.aspect_ratio)


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


def _queue_render(request, scene, *, new_keyframe: bool = False) -> Response:
    """Отправить сцену в съёмку: проверить баланс и перевести её в «Ожидает».

    Две вещи, из-за которых раньше терялись деньги:
      * баланс проверялся по каждой сцене отдельно, а списание идёт в конце
        съёмки — две сцены при балансе на одну обе проходили проверку, вторая
        снималась за наш счёт и падала на списании. Теперь из баланса вычитается
        цена сцен, которые уже снимаются (pricing.reserved_credits);
      * проверка и смена состояния шли порознь — два запроса разом ставили две
        задачи. Теперь строка пользователя под замком, а сцена переводится
        условным UPDATE.
    """
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from django.utils import timezone

    from ai.pricing import PriceUnavailable
    from vstudio.reserve import vstudio_reserved  # дубли видеостудии в работе тоже держат баланс

    from .models import CartoonKeyframe
    from .pricing import reserved_credits

    lang = _lang(request)
    character = scene.character or scene.project.character
    if not new_keyframe:
        # Кадр, который человек уже видел в примерке (и оплатил), съёмка возьмёт
        # из общего запаса — платить за кадр второй раз не придётся.
        _attach_ready_keyframe(scene)
    try:
        need = _scene_price(scene, keyframe_ready=bool(scene.keyframe) and not new_keyframe)
    except PriceUnavailable as exc:
        return _price_unavailable(exc)
    with transaction.atomic():
        # Строка пользователя под замком: два «Снять» разом иначе увидели бы
        # один и тот же свободный остаток.
        locked = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        balance = int(getattr(locked, "token_balance", 0) or 0)
        reserved = reserved_credits(request.user, exclude_scene_id=scene.pk) + vstudio_reserved(request.user)
        free = max(0, balance - reserved)
        if free < need:
            return _no_credits(need, free, reserved)
        fields = {"status": CartoonScene.STATUS_NEW, "error": "", "updated_at": timezone.now()}
        if new_keyframe:
            fields["keyframe"] = ""
        claimed = CartoonScene.objects.filter(
            pk=scene.pk, status__in=(CartoonScene.STATUS_DRAFT, CartoonScene.STATUS_FAILED,
                                     CartoonScene.STATUS_READY)).update(**fields)
        if claimed and new_keyframe and character and not scene.custom_text:
            # Новый кадр — значит, и не из общего запаса: иначе съёмка взяла бы
            # тот же неудачный кадр пары. Только после проверки баланса: при
            # отказе «не хватает кредитов» ничего не должно пропасть.
            CartoonKeyframe.objects.filter(preset_id=scene.preset_id, character=character).delete()
    if claimed:
        transaction.on_commit(lambda pk=scene.pk: _enqueue_render(pk))
    scene.refresh_from_db()
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
    """

    def post(self, request, pk):
        scene = get_object_or_404(
            CartoonScene.objects.select_related("preset__image_model", "preset__video_model"),
            pk=pk, project__user=request.user)
        if scene.status in WORKING_STATUSES:
            return Response(scene_json(scene, _lang(request)))
        return _queue_render(request, scene)


class SceneDetailView(StudioAPIView):
    """PATCH — переставить в таймлайне или пересобрать. DELETE — убрать."""

    def patch(self, request, pk):
        scene = get_object_or_404(
            CartoonScene.objects.select_related("preset__image_model", "preset__video_model"),
            pk=pk, project__user=request.user)

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
            return _queue_render(request, scene,
                                 new_keyframe=bool(request.data.get("new_keyframe")))

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
