"""Работы пользователей студии: отбор удачных для витрины и рекламы.

Клиент: пары «герой + сцена» создают сами пользователи, а самые удачные работы
потом идут в библиотеку и в рекламу. Здесь их видно все разом, и три кнопки:
- «Для рекламы» — отметка, по которой такие ролики потом легко найти;
- «Превью сцены» — ролик становится превью сцены в библиотеке для всех;
- «Опубликовать как новую сцену» — своя сцена пользователя становится новой
  сценой библиотеки (снятой с публикации: владелец правит названия и
  публикует её в «Сценах мультстудии»). Что туда пускается — cartoon.panel.

Ролики со СВОИМИ персонажами пользователей (загруженными или нарисованными по
описанию) ни туда ни туда не пускаются: на загруженном фото может быть живой
человек или ребёнок, и показывать его публично без явного согласия нельзя.
Мультфильм считается «своим», если своим героем снята хотя бы одна сцена.
"""
from __future__ import annotations

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from cartoon import panel
from cartoon.models import CartoonProject, CartoonScene

from .views import StaffAPIView, _paginate


def _url(path: str) -> str:
    return default_storage.url(path) if path else ""


def _hero(scene):
    return scene.character or scene.project.character


def _scene_row(s: CartoonScene, frames: dict | None = None, copies: dict | None = None) -> dict:
    """frames и copies — panel.frame_sources и panel.library_copies для страницы
    сцен; None — посчитать для этой."""
    hero = _hero(s)
    own = bool(hero and hero.user_id is not None)
    custom = bool(s.custom_text)
    block = ""
    copy = None
    if custom:
        if frames is None:
            frames = panel.frame_sources([s])
        if copies is None:
            copies = panel.library_copies([s.pk])
        block = panel.publish_block(s, frames.get(s.pk))
        copy = copies.get(s.pk)
    return {
        "kind": "scene",
        "id": s.pk,
        "created_at": s.updated_at.isoformat(),
        "user_email": s.project.user.email if s.project.user_id else "",
        "project_id": s.project_id,
        "title": (s.custom_title or s.custom_text[:60]) if custom else (s.preset.title if s.preset_id else ""),
        "custom_text": s.custom_text,
        "preset_id": None if custom else s.preset_id,
        "preset_slug": "" if custom else (s.preset.slug if s.preset_id else ""),
        "hero": {"name": hero.name, "image": _url(hero.image_thumb.name if hero.image_thumb else hero.image.name),
                 "own": own} if hero else None,
        # Для рекламы — со звуком, если его накладывали.
        "video": _url(s.mixed_video or s.video),
        "poster": _url(s.keyframe),
        "featured": bool(s.featured_at),
        "public_ok": bool(hero) and not own,
        # Превью сцены библиотеки можно ставить только из сцены библиотеки.
        "can_preview": bool(hero) and not own and not custom,
        # Новой сценой библиотеки — только своя сцена без личного в кадре и звуке.
        "can_publish_scene": custom and not block,
        "publish_scene_note": block if custom else "",
        # Сцена библиотеки, уже сделанная из этой: вместо кнопки — ссылка на неё,
        # и после перезагрузки страницы, и у другого сотрудника.
        "library_scene_id": copy,
    }


def _movie_row(p: CartoonProject, own: bool) -> dict:
    first = p.scenes.exclude(keyframe="").order_by("order").first()
    return {
        "kind": "movie",
        "id": p.pk,
        "created_at": p.updated_at.isoformat(),
        "user_email": p.user.email if p.user_id else "",
        "project_id": p.pk,
        "title": p.title,
        "custom_text": "",
        "preset_id": None,
        "preset_slug": "",
        "hero": {"name": p.character.name,
                 "image": _url(p.character.image_thumb.name if p.character.image_thumb else p.character.image.name),
                 "own": p.character.user_id is not None} if p.character else None,
        "scenes": p.scenes.filter(status=CartoonScene.STATUS_READY).count(),
        "video": _url(p.result_video),
        "poster": _url(first.keyframe) if first else "",
        "featured": bool(p.featured_at),
        "public_ok": not own,
        "can_preview": False,
    }


def _own_scene_q(prefix: str = "") -> Q:
    """Сцена снята своим героем пользователя (свой у сцены или у мультфильма)."""
    return (Q(**{f"{prefix}character__user__isnull": False})
            | Q(**{f"{prefix}character__isnull": True, f"{prefix}project__character__user__isnull": False}))


class StudioWorksView(StaffAPIView):
    """GET ?kind=scenes|movies&show=all|public|featured&q=почта"""

    def get(self, request):
        kind = request.query_params.get("kind") or "scenes"
        show = request.query_params.get("show") or "all"
        query = str(request.query_params.get("q") or "").strip()

        if kind == "movies":
            own_scene = CartoonScene.objects.filter(project=OuterRef("pk")).filter(_own_scene_q())
            qs = (CartoonProject.objects.exclude(result_video="")
                  .select_related("user", "character")
                  .annotate(has_own=Exists(own_scene))
                  .order_by("-updated_at"))
            if show == "public":
                qs = qs.filter(has_own=False)
            elif show == "featured":
                qs = qs.filter(featured_at__isnull=False)
            if query:
                qs = qs.filter(user__email__icontains=query)
            count, page = _paginate(qs, request)
            return Response({"count": count, "results": [_movie_row(p, p.has_own) for p in page]})

        qs = (CartoonScene.objects.filter(status=CartoonScene.STATUS_READY).exclude(video="")
              .select_related("project__user", "project__character", "character", "preset")
              .order_by("-updated_at"))
        if show == "public":
            qs = qs.exclude(_own_scene_q())
        elif show == "featured":
            qs = qs.filter(featured_at__isnull=False)
        if query:
            qs = qs.filter(project__user__email__icontains=query)
        count, page = _paginate(qs, request)
        page = list(page)
        # Чем рисовались кадры своих сцен и какие уже в библиотеке — запросом на страницу.
        frames = panel.frame_sources(page)
        copies = panel.library_copies([s.pk for s in page if s.custom_text])
        return Response({"count": count, "results": [_scene_row(s, frames, copies) for s in page]})


class StudioWorkFeatureView(StaffAPIView):
    """POST {featured: bool} — отметить работу для рекламы. Свои персонажи — нет."""

    def post(self, request, kind, pk):
        featured = bool((request.data or {}).get("featured", True))
        if kind == "scene":
            obj = (CartoonScene.objects.select_related("project__character", "character", "preset", "project__user")
                   .filter(pk=pk, status=CartoonScene.STATUS_READY).first())
            if not obj:
                return Response({"detail": "Сцена не найдена"}, status=status.HTTP_404_NOT_FOUND)
            hero = _hero(obj)
            if featured and (not hero or hero.user_id is not None):
                return Response({"detail": "Свой персонаж пользователя — публично показывать нельзя"},
                                status=status.HTTP_400_BAD_REQUEST)
            obj.featured_at = timezone.now() if featured else None
            obj.save(update_fields=["featured_at", "updated_at"])
            return Response(_scene_row(obj))

        if kind == "movie":
            obj = CartoonProject.objects.select_related("user", "character").filter(pk=pk).exclude(
                result_video="").first()
            if not obj:
                return Response({"detail": "Мультфильм не найден"}, status=status.HTTP_404_NOT_FOUND)
            own = obj.scenes.filter(_own_scene_q()).exists()
            if featured and own:
                return Response({"detail": "В мультфильме есть свой персонаж пользователя — публично показывать нельзя"},
                                status=status.HTTP_400_BAD_REQUEST)
            obj.featured_at = timezone.now() if featured else None
            obj.save(update_fields=["featured_at", "updated_at"])
            return Response(_movie_row(obj, own))

        return Response({"detail": "Неизвестный тип"}, status=status.HTTP_400_BAD_REQUEST)


class StudioWorkSetPreviewView(StaffAPIView):
    """POST — сделать ролик сцены превью этой сцены в библиотеке.

    Превью видят все посетители студии, поэтому только герой библиотеки и
    только сцена из библиотеки. Лёгкая копия и обложка пересобираются сразу —
    иначе в витрине до следующего прогона команд висело бы старое.
    """

    def post(self, request, pk):
        from cartoon.clips import make_clip
        from cartoon.thumbs import POSTER_BOX, make_thumb

        scene = (CartoonScene.objects.select_related("preset", "character", "project__character")
                 .filter(pk=pk, status=CartoonScene.STATUS_READY).exclude(video="").first())
        if not scene:
            return Response({"detail": "Сцена не найдена"}, status=status.HTTP_404_NOT_FOUND)
        hero = _hero(scene)
        if scene.custom_text or not scene.preset_id:
            return Response({"detail": "Своя сцена по описанию — у неё нет сцены в библиотеке"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not hero or hero.user_id is not None:
            return Response({"detail": "Свой персонаж пользователя — в библиотеку нельзя"},
                            status=status.HTTP_400_BAD_REQUEST)

        preset = scene.preset
        preset.preview_video.name = scene.video
        fields = ["preview_video"]
        if scene.keyframe:
            preset.preview_poster.name = scene.keyframe
            fields.append("preview_poster")
        notes = []
        try:
            with default_storage.open(scene.video, "rb") as fh:
                clip = make_clip(fh.read())
            if clip:
                preset.preview_clip.save(f"{preset.slug}-w{scene.pk}.mp4", ContentFile(clip), save=False)
                fields.append("preview_clip")
            else:
                notes.append("лёгкая копия не сделалась — в витрине пойдёт оригинал")
                preset.preview_clip = None
                fields.append("preview_clip")
        except Exception:
            notes.append("лёгкая копия не сделалась — в витрине пойдёт оригинал")
        if scene.keyframe:
            try:
                with default_storage.open(scene.keyframe, "rb") as fh:
                    thumb = make_thumb(fh.read(), POSTER_BOX)
                if thumb:
                    preset.preview_thumb.save(f"{preset.slug}-w{scene.pk}.jpg", ContentFile(thumb), save=False)
                    fields.append("preview_thumb")
            except Exception:
                notes.append("миниатюра обложки не сделалась")
        preset.save(update_fields=list(dict.fromkeys(fields)))

        row = _scene_row(scene)
        row["notes"] = notes
        return Response(row)


class StudioWorkPublishSceneView(StaffAPIView):
    """POST — своя сцена пользователя становится новой сценой библиотеки.

    Сцена создаётся снятой с публикации: владелец правит названия и публикует
    её в «Сценах мультстудии». Повторный клик отдаёт уже созданную (200).
    Отказ, если в кадр или звук могло попасть личное, — 400 с причиной.
    """

    def post(self, request, pk):
        preset, created = panel.publish_from_scene(pk, actor=request.user, request=request)
        return Response({"created": created, "preset": panel.scene_row(preset)},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
