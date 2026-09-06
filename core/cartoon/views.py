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


def _media(path: str) -> str:
    return default_storage.url(path) if path else ""


def preset_json(p: CartoonPreset, lang: str = "ru") -> dict:
    """Пользователю — только витрина: название, превью, длительность и цена.
    Промпты и модели наружу не отдаём: это внутренняя кухня студии."""
    return {
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
        "credits": p.estimated_credits(),
        "category": p.category.slug if p.category_id else "",
        "audience": p.audience,
        "is_pick": p.is_pick,
    }


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


def scene_json(s: CartoonScene, lang: str = "ru") -> dict:
    return {
        "id": s.id,
        "order": s.order,
        "preset": {"id": s.preset_id,
                   "title": _tr(s.preset, "title", lang) if s.preset_id else "",
                   # Цена нужна прямо в ленте: снимают оттуда, и человек должен
                   # видеть, во что обойдётся кнопка, до нажатия.
                   "credits": s.preset.estimated_credits() if s.preset_id else 0,
                   "duration": s.preset.duration if s.preset_id else 0,
                   # Обложка нужна черновику: своего кадра у него ещё нет, а
                   # пустой прямоугольник с крутилкой выглядит так, будто
                   # что-то грузится и зависло.
                   "poster": (s.preset.preview_thumb.url if s.preset.preview_thumb
                              else (s.preset.preview_poster.url
                                    if s.preset.preview_poster else ""))
                   if s.preset_id else ""},
        # Герой именно этой сцены: свой, если задан, иначе герой мультфильма.
        # Фронту нужно показать, кем сцена снимется, ещё до съёмки.
        "character": character_json(s.character or s.project.character, lang)
                     if (s.character_id or s.project.character_id) else None,
        "keyframe": _media(s.keyframe),
        "video": _media(s.video),
        "status": s.status,
        "error": s.error,
        "credits_spent": s.credits_spent,
    }


def project_json(p: CartoonProject, lang: str = "ru") -> dict:
    scenes = list(p.scenes.select_related(
        "preset", "character", "project__character").order_by("order", "id"))
    return {
        "id": p.id,
        "title": p.title,
        "status": p.status,
        "aspect_ratio": p.aspect_ratio,
        "character": character_json(p.character, lang) if p.character else None,
        "result_video": _media(p.result_video),
        "error": p.error,
        "scenes": [scene_json(s, lang) for s in scenes],
        "created_at": p.created_at.isoformat(),
        "credits_spent": sum(s.credits_spent for s in scenes),
    }


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
        # хуже её отсутствия, а библиотека наполняется постепенно.
        qs = CartoonPreset.objects.filter(is_active=True).exclude(
            preview_video="").select_related(
            "image_model", "video_model", "category").order_by(
            "category__sort_order", "sort_order", "id")
        lang = _lang(request)
        presets = [preset_json(p, lang) for p in qs]
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

        rows = (CartoonScene.objects.values("preset__slug")
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

        img = GPTModels.objects.filter(
            openrouter_id="google/gemini-2.5-flash-image", is_active=True).first()
        character = max(1, int(float(img.markup_coefficient or 1))) if img else 4

        prices = sorted(
            p.estimated_credits()
            for p in CartoonPreset.objects.filter(is_active=True).select_related(
                "image_model", "video_model")
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
        char = CartoonCharacter.objects.create(
            user=request.user,
            name=(request.data.get("name") or "Мой персонаж").strip()[:120],
            image=image,
            description=(request.data.get("description") or "").strip()[:1000],
            source=CartoonCharacter.SOURCE_UPLOAD,
        )
        _attach_thumb(char)
        return Response(character_json(char, _lang(request)), status=status.HTTP_201_CREATED)


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

        price = max(1, int(float(model.markup_coefficient or 1)))
        balance = int(getattr(request.user, "token_balance", 0) or 0)
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
            return Response({"detail": f"Не удалось нарисовать персонажа: {exc}"},
                            status=status.HTTP_502_BAD_GATEWAY)

        char = CartoonCharacter(
            user=request.user,
            name=(request.data.get("name") or prompt[:60]).strip()[:120],
            description=prompt[:1000],
            source=CartoonCharacter.SOURCE_GENERATED,
        )
        char.image.save(f"{uuid.uuid4().hex}.jpg", ContentFile(base64.b64decode(b64)), save=True)
        _attach_thumb(char)

        from .services import charge

        charge(request.user, price, "cartoon_character", meta={"character": char.pk})
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
            aspect_ratio=(request.data.get("aspect_ratio") or "16:9").strip()[:8],
        )
        return Response(project_json(project, _lang(request)), status=status.HTTP_201_CREATED)


class ProjectDetailView(StudioAPIView):
    """GET — состояние проекта (фронт опрашивает во время генерации).
    DELETE — удалить черновик."""

    def get(self, request, pk):
        project = get_object_or_404(CartoonProject, pk=pk, user=request.user)
        return Response(project_json(project, _lang(request)))

    def delete(self, request, pk):
        project = get_object_or_404(CartoonProject, pk=pk, user=request.user)
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
        preset = CartoonPreset.objects.filter(
            pk=request.data.get("preset_id"), is_active=True
        ).select_related("image_model", "video_model").first()
        if not preset:
            return Response({"detail": "Сцена не найдена"}, status=status.HTTP_400_BAD_REQUEST)

        last = project.scenes.order_by("-order").first()
        scene = CartoonScene.objects.create(
            project=project, preset=preset,
            character=_pick_character(request, request.data.get("character_id")),
            order=(last.order + 1) if last else 0,
            status=CartoonScene.STATUS_DRAFT,
        )
        _attach_ready_keyframe(scene)
        return Response(scene_json(scene, _lang(request)), status=status.HTTP_201_CREATED)


def _attach_ready_keyframe(scene) -> None:
    """Подставить готовый кадр «герой в сцене», если он уже нарисован.

    Такой кадр лежит в общем запасе и ничего не стоит. Человек добавил сцену и
    сразу видит в ленте своего героя, а не обложку с чужим, — и при съёмке за
    этот кадр не платит: он же пойдёт первым.
    """
    from .models import CartoonKeyframe

    character = scene.character or scene.project.character
    if not character or scene.keyframe:
        return
    ready = CartoonKeyframe.objects.filter(
        preset_id=scene.preset_id, character=character).first()
    if ready and ready.image:
        scene.keyframe = ready.image
        scene.save(update_fields=["keyframe", "updated_at"])


def _pick_character(request, character_id):
    """Герой из запроса: библиотечный или свой. Чужого не отдаём."""
    if not character_id:
        return None
    library = Q(is_public=True, user__isnull=True)
    mine = Q(user=request.user) if request.user.is_authenticated else Q(pk__in=[])
    return CartoonCharacter.objects.filter(library | mine).filter(pk=character_id).first()


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


class PresetTryOnView(StudioAPIView):
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

        ready = CartoonKeyframe.objects.filter(preset=preset, character=character).first()
        if ready and ready.image:
            return Response({"image": _media(ready.image), "charged": 0})

        price = max(1, int(float(preset.image_model.markup_coefficient or 1)))
        balance = int(getattr(request.user, "token_balance", 0) or 0)
        if balance < price:
            return Response({"detail": "Недостаточно кредитов", "required": price,
                             "balance": balance}, status=status.HTTP_402_PAYMENT_REQUIRED)

        from .services import get_or_create_keyframe

        try:
            path, charged = get_or_create_keyframe(preset, character, request.user)
        except Exception as exc:
            logger.exception("примерка героя: кадр не нарисовался")
            return Response({"detail": f"Кадр не получился: {exc}"[:200]},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({"image": _media(path), "charged": charged})


def _scene_price(scene, *, keyframe_ready: bool) -> int:
    """Во сколько обойдётся съёмка сцены ПРЯМО СЕЙЧАС.

    Готовый кадр заново не рисуется (см. tasks.render_scene), поэтому при
    пересъёмке с ним платится только видео-часть. Считаем её той же формулой,
    что и списание в задаче: разойдись гейт со счётом — человек либо не смог бы
    переснять при достаточном балансе, либо ушёл бы в минус.
    """
    preset = scene.preset
    if not keyframe_ready:
        return preset.estimated_credits()
    return max(1, round(int(preset.duration or 5)
                        * float(preset.video_model.markup_coefficient or 1)))


def _no_credits(need: int, balance: int) -> Response:
    return Response({"detail": "Недостаточно кредитов", "required": need,
                     "balance": balance}, status=status.HTTP_402_PAYMENT_REQUIRED)


class SceneRenderView(StudioAPIView):
    """POST — снять сцену из ленты. Здесь и происходит проверка баланса.

    Отделено от добавления сознательно: деньги списываются в момент, когда
    человек осознанно нажал «Снять», а не когда он собирал ленту.
    """

    def post(self, request, pk):
        scene = get_object_or_404(
            CartoonScene.objects.select_related("preset__image_model", "preset__video_model"),
            pk=pk, project__user=request.user)
        if scene.status in (CartoonScene.STATUS_NEW, CartoonScene.STATUS_KEYFRAME,
                            CartoonScene.STATUS_VIDEO):
            return Response(scene_json(scene, _lang(request)))

        need = scene.preset.estimated_credits()
        balance = int(getattr(request.user, "token_balance", 0) or 0)
        if balance < need:
            return _no_credits(need, balance)

        scene.status = CartoonScene.STATUS_NEW
        scene.error = ""
        scene.save(update_fields=["status", "error", "updated_at"])
        render_scene.delay(scene.pk)
        return Response(scene_json(scene, _lang(request)))


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
            scene.save(update_fields=["character", "keyframe", "updated_at"])
            _attach_ready_keyframe(scene)

        if request.data.get("retry"):
            # Сцена уже в работе — второй задачи не ставим: обе сняли бы видео и
            # обе списали бы деньги, а человек видел бы одну сцену.
            if scene.status in (CartoonScene.STATUS_NEW, CartoonScene.STATUS_KEYFRAME,
                                CartoonScene.STATUS_VIDEO):
                return Response(scene_json(scene, _lang(request)))

            # Пересборка идёт с УЖЕ готовым кадром, если он есть: так персонаж
            # и композиция не сдвинутся, а заплатит человек только за видео.
            new_keyframe = bool(request.data.get("new_keyframe"))
            # Баланс проверяем ЗДЕСЬ, а не в задаче: провайдеру за генерацию мы
            # платим сразу, а списание в Celery упало бы уже после — видео
            # потеряно, деньги студии сгорели.
            need = _scene_price(scene, keyframe_ready=bool(scene.keyframe) and not new_keyframe)
            balance = int(getattr(request.user, "token_balance", 0) or 0)
            if balance < need:
                return _no_credits(need, balance)

            if new_keyframe:
                scene.keyframe = ""
            scene.status = CartoonScene.STATUS_NEW
            scene.error = ""
            scene.save(update_fields=["keyframe", "status", "error", "updated_at"])
            render_scene.delay(scene.pk)

        return Response(scene_json(scene, _lang(request)))

    def delete(self, request, pk):
        scene = get_object_or_404(CartoonScene, pk=pk, project__user=request.user)
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
        project = get_object_or_404(CartoonProject, pk=pk, user=request.user)
        ready = project.scenes.filter(status=CartoonScene.STATUS_READY).exclude(video="").count()
        if not ready:
            return Response({"detail": "Нет готовых сцен"}, status=status.HTTP_400_BAD_REQUEST)
        assemble_movie.delay(project.pk)
        project.refresh_from_db()
        return Response(project_json(project, _lang(request)), status=status.HTTP_202_ACCEPTED)
