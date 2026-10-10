"""Витрина первого экрана: настоящие работы видеостудии, отобранные владельцем.

У одного списка две стороны:
- сайт (GET /api/vstudio/showcase/) открыт всем, включая гостей, поэтому наружу
  идёт только перечисленное в public_json: файл результата, обложка, название,
  сценарий, модель и размеры. Ни uid дубля, ни почты автора, ни фото, с
  которыми работа снята; текст запроса и параметры — только с галочкой
  «Показывать запрос».
  С той же галочкой у работы «Image → Video» становится виден и первый кадр —
  картинка, с которой ролик начинается (start_frame_url): по примеру должно
  быть понятно, что из чего получилось. Референсы, последний кадр и роли не
  выходят никогда; про остальные работы со своими фото сайт знает только сам
  факт (needs_photo).
  Одно исключение: исходник, обложка и первый кадр лежат в папке автора
  (vstudio/<номер аккаунта>/<uid материала>…), и номер виден в их адресах.
  Поэтому в витрину ставятся только работы сотрудников (can_publish);
- панель (/api/manage/vstudio/showcase/, adminapi.vstudio) видит ту же витрину
  вместе со скрытыми строками и готовые дубли, которые можно в неё поставить.

Правила панели живут здесь, а не во вьюхах: проверка полей, запись в журнал
действий (audit.AdminActionLog) в одной транзакции с правкой, сброс кэша.
Сколько работ из списка берёт карусель, тоже решает панель — настройка
reel_size; в список и его кэш она не входит.

Ролики первый экран крутит сам, поэтому у каждой работы есть лёгкая копия
(ShowcaseItem.clip, рецепт cartoon.clips). Её собирает задача в общей очереди
после добавления строки; пока копии нет или она не собралась — играет исходник.
"""
from __future__ import annotations

import logging
import math
import re
import uuid
from functools import partial

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import F, Prefetch, Q
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from rest_framework import status as http
from rest_framework.exceptions import APIException

from audit.services import log_admin_action
from cartoon.clips import make_clip

from . import prompt_doc as pd
from . import serializers as S
from .assets import delete_files
from .models import TAKE_DONE, Asset, ShotInput, ShowcaseItem, Take

logger = logging.getLogger("vstudio")

CACHE_KEY = "vstudio:showcase:v1"
CACHE_S = 300
# Больше первый экран не покажет: карусель берёт reel_size() работ, остальное —
# запас на замену.
MAX_PUBLIC = 48
# Размер карусели — настройка панели (runtime-ключ). Меньше пяти у карусели нет
# «крыльев» по бокам, больше MAX_PUBLIC сайт всё равно не получит.
REEL_SIZE_KEY = "vstudio_reel_size"
REEL_SIZE_MIN = 5
REEL_SIZE_MAX = MAX_PUBLIC
REEL_SIZE_DEFAULT = 12
# Что нужно кнопке «Снять похожее». Сид и негативный промпт наружу не идут.
PARAM_KEYS = ("duration", "resolution", "aspect_ratio")
SCOPES = ("staff", "all")
CATEGORY_CHOICES = ShowcaseItem.CATEGORY_CHOICES
CATEGORIES = tuple(key for key, _label in CATEGORY_CHOICES)
# Сценарии карусели по порядку — те же ключи без «Другое».
SCENARIOS = ShowcaseItem.SCENARIOS
TITLE_MAX = ShowcaseItem._meta.get_field("title").max_length
SORT_LIMIT = 100_000
# Режимы, в которых модели ушёл один текст — без фото человека.
TEXT_MODES = (Take.MODE_T2V, Take.MODE_T2I)
# Режимы, в которых ролик начинается ровно с присланной картинки.
FRAME_MODES = (Take.MODE_I2V, Take.MODE_FLF2V)
# make_clip берёт ролик байтами. Больше этого в память не читаем (тот же
# потолок, что у постера в delivery): такая работа остаётся с исходником.
CLIP_SOURCE_MAX_BYTES = 64 * 1024 * 1024

# Своего кода у витрины нет: список кодов журнала закрытый
# (audit.models.ADMIN_ACTIONS, его сверяют тесты Creators). Как и правки
# настроек панели, витрина пишется кодом settings.edit, а что именно меняли —
# видно по типу объекта и ключу vstudio_showcase.
LOG_ACTION = "settings.edit"
LOG_KEY = "vstudio_showcase"

_ASPECT_RE = re.compile(r"^\d{1,4}:\d{1,4}$")
_ORDER = ("sort", "-created_at", "-pk")


class ShowcaseError(APIException):
    """Отказ панели: текст человеку и код ответа.

    DRF отдаёт его телом {"detail": "<текст>"}, как остальная панель, и
    откатывает транзакцию запроса.
    """

    def __init__(self, detail: str, *, status: int = http.HTTP_400_BAD_REQUEST):
        super().__init__(detail=detail)
        self.status_code = status


# ---------------------------------------------------------------- что показываем

def _ready_q(prefix: str = "") -> Q:
    """Дубль готов и результат на месте: файл сохранён, человек его не удалил."""
    return (Q(**{f"{prefix}status": TAKE_DONE,
                 f"{prefix}result_asset__status": Asset.STATUS_READY,
                 f"{prefix}result_asset__deleted_at__isnull": True})
            & ~Q(**{f"{prefix}result_asset__file": ""}))


def _is_ready(take: Take) -> bool:
    asset = take.result_asset
    return bool(take.status == TAKE_DONE and asset is not None and asset.file
                and asset.status == Asset.STATUS_READY and asset.deleted_at is None)


def _model_name(take: Take) -> str:
    # Модель могли убрать из каталога — тогда остаётся её ID.
    return take.shot.model.name if take.shot.model_id else take.model_ref


def _aspect(take: Take, asset: Asset | None) -> str | None:
    """Соотношение сторон кадра: заказанное, а при «auto» — по размеру файла."""
    value = str((take.effective or {}).get("aspect_ratio") or "")
    if _ASPECT_RE.match(value):
        return value
    if asset is not None and asset.width and asset.height:
        common = math.gcd(asset.width, asset.height)
        return f"{asset.width // common}:{asset.height // common}"
    return None


def _duration(take: Take, asset: Asset | None) -> int | None:
    if take.kind != Take.KIND_VIDEO:
        return None
    if asset is not None and asset.duration_s:
        return max(1, round(asset.duration_s))
    value = (take.effective or {}).get("duration")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return max(1, round(value))
    return None


def _params(take: Take) -> dict:
    """Параметры, с которыми работа снята на деле (Take.effective, не заказ)."""
    effective = take.effective or {}
    return {key: effective[key] for key in PARAM_KEYS if effective.get(key) not in (None, "")}


def _media(take: Take) -> dict:
    """Карточка работы: файл, обложка, модель и размеры — одинаково сайту и панели."""
    asset = take.result_asset
    is_video = take.kind == Take.KIND_VIDEO
    url = (asset.url or None) if asset is not None else None
    thumb = (asset.thumb_url or None) if asset is not None else None
    return {
        "kind": take.kind,
        "model": {"id": take.model_ref, "name": _model_name(take)},
        "aspect_ratio": _aspect(take, asset),
        "duration_s": _duration(take, asset),
        "width": asset.width if asset is not None else None,
        "height": asset.height if asset is not None else None,
        "video_url": url if is_video else None,
        "image_url": None if is_video else url,
        # У картинки без лёгкой копии обложкой служит она сама.
        "poster_url": thumb or (None if is_video else url),
    }


# ---------------------------------------------------------------- свои фото

def needs_photo(take: Take) -> bool:
    """Работа снята со своими картинками: повторить её можно, только добавив свою."""
    return take.mode not in TEXT_MODES


def start_frame_url(take: Take) -> str | None:
    """Адрес картинки, с которой начинается ролик, — или None.

    Единственный материал запроса, который может уйти наружу, поэтому всё
    правило здесь и при любом сомнении ответ — None:
    - режим «первый кадр → видео» (i2v, flf2v). В остальных фото — референсы:
      лица и вещи, которые человек показывать не собирался;
    - работа сотрудника (can_publish) и картинка из его же материалов: в её
      адресе тот же номер аккаунта, что уже виден в адресе результата;
    - кадр ровно один — тот, что ушёл модели: включён и не отброшен как лишний
      (Take.dropped). Двоякий случай не разбираем;
    - картинка готова, файл на месте и человек её не удалил.
    Отдаём лёгкую копию, если она есть: наружу нужна миниатюра, а не оригинал.
    """
    if take.mode not in FRAME_MODES or not can_publish(take):
        return None
    slot = ShotInput.SLOT_FIRST_FRAME
    dropped = {row.get("asset") for row in (take.dropped if isinstance(take.dropped, list) else [])
               if isinstance(row, dict) and row.get("slot") == slot}
    frames = [row.asset for row in take.shot.inputs.all()
              if row.slot == slot and row.included and row.asset.uid not in dropped]
    if len(frames) != 1:
        return None
    asset = frames[0]
    if (asset.user_id != take.user_id or asset.kind != Asset.KIND_IMAGE
            or asset.status != Asset.STATUS_READY or asset.deleted_at is not None
            or not asset.file):
        return None
    return asset.thumb_url or asset.url or None


def _with_inputs(qs, prefix: str = ""):
    """Материалы запросов — одним заходом на весь список: по ним ищется первый кадр."""
    return qs.prefetch_related(Prefetch(f"{prefix}shot__inputs",
                                        queryset=ShotInput.objects.select_related("asset")))


# ---------------------------------------------------------------- сайт

def public_qs():
    """Что видно всем: включённые строки с готовым, не удалённым результатом."""
    return (ShowcaseItem.objects.filter(_ready_q("take__"), is_active=True)
            .select_related("take__user", "take__result_asset", "take__shot__model")
            .order_by(*_ORDER))


def public_json(item: ShowcaseItem) -> dict:
    """Карточка для сайта. Список полей закрытый: новое поле дубля само наружу не уйдёт."""
    take = item.take
    out = {"id": item.pk, "title": item.title, "category": item.category, **_media(take),
           "full_url": None, "prompt": None, "params": None,
           "needs_photo": False, "start_frame_url": None}
    if out["video_url"]:
        # В лентах играет лёгкая копия, исходник — рядом, для показа в полном
        # качестве. Копии ещё нет — работа видна сразу, с исходником.
        out["full_url"] = out["video_url"]
        if item.clip:
            out["video_url"] = item.clip.url
    if item.show_prompt:
        # prompt_text — запрос глазами человека: фото в нём названы «@Image N», без uid.
        out["prompt"] = take.shot.prompt_text or None
        out["params"] = _params(take)
        # Как работа снята — тоже часть рецепта: без галочки сайт не знает даже
        # того, что в ней были свои фото.
        out["needs_photo"] = needs_photo(take)
        out["start_frame_url"] = start_frame_url(take)
    return out


def public_items() -> list[dict]:
    """Список для первого экрана. Кэш 5 минут, правка витрины сбрасывает его сразу."""
    try:
        cached = cache.get(CACHE_KEY)
    except Exception:
        cached = None
    if cached is not None:
        return cached
    items = [public_json(item) for item in _with_inputs(public_qs(), "take__")[:MAX_PUBLIC]]
    try:
        cache.set(CACHE_KEY, items, CACHE_S)
    except Exception:
        pass
    return items


def _forget() -> None:
    try:
        cache.delete(CACHE_KEY)
    except Exception:
        logger.warning("vstudio showcase: кэш не сбросился, витрина обновится сама через %s с",
                       CACHE_S, exc_info=True)


def drop_cache() -> None:
    """Забыть кэш витрины — после фиксации транзакции.

    Запросы идут в транзакции (ATOMIC_REQUESTS): сбросить раньше — значит дать
    соседнему запросу собрать кэш из ещё не изменённой базы на пять минут.
    Вне транзакции сброс происходит сразу.
    """
    transaction.on_commit(_forget)


@receiver((post_save, post_delete), sender=ShowcaseItem, dispatch_uid="vstudio_showcase_cache")
def _item_changed(sender, **kwargs) -> None:
    # Сигнал, а не вызов из вьюхи: строку меняют и панель, и Django-админка,
    # а удаление дубля или аккаунта уносит её каскадом.
    drop_cache()


# ---------------------------------------------------------------- размер карусели

def _reel_clamp(value) -> int:
    """Число — в границы карусели; не целое число — размер по умолчанию."""
    if isinstance(value, bool) or not isinstance(value, int):
        return REEL_SIZE_DEFAULT
    return min(max(value, REEL_SIZE_MIN), REEL_SIZE_MAX)


def reel_size() -> int:
    """Сколько роликов берёт карусель первого экрана: от REEL_SIZE_MIN до REEL_SIZE_MAX.

    Не бросает никогда — её зовёт открытая всем витрина. Настройки не
    прочитались или в базе не число — размер по умолчанию; число вне границ —
    ближайшая граница. В кэш списка работ значение не входит: у настроек свой,
    на полминуты (adminapi.runtime), так что в базу чтение ходит редко.
    Чтение — в savepoint, как у studio_mode: сбой запроса к настройкам не
    должен ломать транзакцию запроса.
    """
    try:
        from adminapi.runtime import get_runtime

        with transaction.atomic():
            value = get_runtime(REEL_SIZE_KEY, REEL_SIZE_DEFAULT)
    except Exception:
        logger.debug("vstudio showcase: размер карусели не прочитался", exc_info=True)
        return REEL_SIZE_DEFAULT
    return _reel_clamp(value)


def _forget_reel_size() -> None:
    """Забыть размер в кэше настроек: следующее чтение пойдёт в базу."""
    try:
        from adminapi.runtime import CACHE_PREFIX

        cache.delete(CACHE_PREFIX + REEL_SIZE_KEY)
    except Exception:
        logger.warning("vstudio showcase: кэш размера карусели не сбросился, значение "
                       "обновится само в течение полминуты", exc_info=True)


# ---------------------------------------------------------------- лёгкая копия

def enqueue_clip(item_pk) -> None:
    """Поставить сборку лёгкой копии (vstudio.tasks.build_showcase_clip).

    Сбой брокера вызывающего не роняет: работа остаётся в витрине с
    исходником, а сборку повторит «Пересобрать» в Django-админке.
    """
    try:
        from . import tasks

        tasks.build_showcase_clip.apply_async(args=[item_pk])
    except Exception:
        logger.exception("vstudio showcase: сборка лёгкой копии работы %s не поставилась", item_pk)


def request_clip(item_pk) -> None:
    """То же после фиксации: воркер не должен искать строку, которой ещё нет в базе."""
    transaction.on_commit(partial(enqueue_clip, item_pk))


def _set_clip(item_pk, name: str) -> bool:
    """Записать строке файл копии (пусто — убрать копию). False — строки уже нет.

    Под замком строки: две сборки подряд (добавление и «Пересобрать») иначе
    оставили бы на диске файл, на который никто не ссылается. Прежний файл
    стираем после фиксации — откатится запрос, и строка всё ещё на него смотрит.
    """
    with transaction.atomic():
        old = (ShowcaseItem.objects.select_for_update().filter(pk=item_pk)
               .values_list("clip", flat=True).first())
        if old is None:
            return False
        if old != name:
            ShowcaseItem.objects.filter(pk=item_pk).update(clip=name)
            if old:
                transaction.on_commit(partial(delete_files, old))
    drop_cache()
    return True


def build_clip(item_pk) -> bool:
    """Собрать лёгкую копию ролика одной работы. True — копия на месте.

    Тело задачи build_showcase_clip: ffmpeg работает секунды, и не в запросе
    панели. Любой сбой — строка в логе и False: работа остаётся в витрине с
    исходником. Картинкам копия не нужна.
    """
    item = ShowcaseItem.objects.select_related("take__result_asset").filter(pk=item_pk).first()
    if item is None or item.take.kind != Take.KIND_VIDEO or not _is_ready(item.take):
        return False
    asset = item.take.result_asset
    name = ""
    try:
        size = asset.bytes or default_storage.size(asset.file)
        if size > CLIP_SOURCE_MAX_BYTES:
            logger.warning("vstudio showcase: исходник работы %s весит %s байт — остаётся без "
                           "лёгкой копии", item_pk, size)
            return False
        with default_storage.open(asset.file, "rb") as fh:
            clip = make_clip(fh.read())
        if not clip:
            logger.warning("vstudio showcase: лёгкая копия работы %s не собралась — играет "
                           "исходник", item_pk)
            return False
        # Имя случайное: в адресе копии нет ни автора, ни материала, а
        # пересобранную копию CDN не отдаст из кэша под старым адресом.
        item.clip.save(f"{uuid.uuid4().hex}.mp4", ContentFile(clip), save=False)
        name = item.clip.name
        if _set_clip(item.pk, name):
            return True
    except Exception:
        logger.exception("vstudio showcase: лёгкая копия работы %s не собралась", item_pk)
    # Строку убрали, пока шла сборка, или запись не удалась — файл ничей.
    delete_files(name)
    return False


@receiver(post_save, sender=ShowcaseItem, dispatch_uid="vstudio_showcase_clip")
def _item_added(sender, instance, created=False, raw=False, **kwargs) -> None:
    # Тоже сигнал: работу ставит и панель, и Django-админка.
    if created and not raw and instance.take.kind == Take.KIND_VIDEO:
        request_clip(instance.pk)


@receiver(post_delete, sender=ShowcaseItem, dispatch_uid="vstudio_showcase_clip_file")
def _item_deleted(sender, instance, **kwargs) -> None:
    if instance.clip:
        # После фиксации: откатится удаление — строка останется со своим файлом.
        transaction.on_commit(partial(delete_files, instance.clip.name))


def forget_assets(asset_pks) -> None:
    """Результаты удалили: их работы уходят из витрины сразу, а не через пять минут.

    Лёгкая копия — наш дубликат ролика: раз результат удалён, по прямой ссылке
    не должна жить и она. Удалили не результат, а первый кадр работы — работа
    остаётся, но адрес кадра с сайта уходит так же сразу.
    """
    rows = list(ShowcaseItem.objects.filter(take__result_asset_id__in=asset_pks)
                .values_list("pk", "clip"))
    for pk, clip in rows:
        if clip:
            _set_clip(pk, "")
    if rows or ShowcaseItem.objects.filter(
            take__shot__inputs__asset_id__in=asset_pks,
            take__shot__inputs__slot=ShotInput.SLOT_FIRST_FRAME).exists():
        drop_cache()


def revive_assets(asset_pks) -> None:
    """Результаты вернули (Django-админка): работы снова на сайте, копии собираем заново."""
    for pk in ShowcaseItem.objects.filter(take__result_asset_id__in=asset_pks, clip="",
                                          take__kind=Take.KIND_VIDEO).values_list("pk", flat=True):
        request_clip(pk)
    drop_cache()


# ---------------------------------------------------------------- панель: строки

def can_publish(take: Take) -> bool:
    """Можно ли показывать работу всем: пока — только работу сотрудника.

    Чужую не ставим по двум причинам. Адреса исходника и обложки содержат
    номер аккаунта автора и uid материала: гость узнал бы, чья это работа, и
    связал бы между собой все работы одного человека. А на загруженном фото
    может быть живой человек или ребёнок (то же правило у работ мультстудии,
    adminapi.studio_works). Работы пользователей, снятые по одному тексту,
    можно будет открыть, когда наружу пойдут только копии по нейтральным
    адресам — как уже идёт clip.
    """
    return bool(take.user.is_staff)


def take_row(take: Take) -> dict:
    """Дубль глазами панели: что за работа, чья она и можно ли её показывать."""
    return {
        "uid": take.uid,
        "status": take.status,
        **_media(take),
        "prompt": take.shot.prompt_text or "",
        "params": _params(take),
        "own_photos": needs_photo(take),
        # Что станет видно всем с галочкой «Показывать запрос» — показать заранее.
        "start_frame_url": start_frame_url(take),
        "public_ok": can_publish(take),
        "user_email": take.user.email,
        "user_is_staff": bool(take.user.is_staff),
        "created_at": S.iso(take.created_at),
        "finished_at": S.iso(take.finished_at),
    }


def _live_ids() -> set:
    return set(public_qs().values_list("pk", flat=True)[:MAX_PUBLIC])


def _state(item: ShowcaseItem, live: set) -> str:
    """Видна ли строка на сайте, а если нет — почему."""
    if not item.is_active:
        return "hidden"
    if item.pk in live:
        return "live"
    return "over_limit" if _is_ready(item.take) else "result_gone"


def staff_json(item: ShowcaseItem, live: set | None = None) -> dict:
    return {
        "id": item.pk,
        "title": item.title,
        "category": item.category,
        "sort": item.sort,
        "is_active": item.is_active,
        "show_prompt": item.show_prompt,
        "state": _state(item, _live_ids() if live is None else live),
        "created_by_email": item.created_by.email if item.created_by_id else "",
        "created_at": S.iso(item.created_at),
        "updated_at": S.iso(item.updated_at),
        "take": take_row(item.take),
    }


def _items_qs():
    return _with_inputs(ShowcaseItem.objects.select_related(
        "created_by", "take__user", "take__result_asset", "take__shot__model"), "take__")


def staff_items() -> list[dict]:
    """Вся витрина, включая скрытые строки, в том же порядке, что на сайте."""
    live = _live_ids()
    return [staff_json(item, live) for item in _items_qs().order_by(*_ORDER)]


def get_item(pk) -> ShowcaseItem:
    item = _items_qs().filter(pk=pk).first()
    if item is None:
        raise ShowcaseError("Работа в витрине не найдена", status=http.HTTP_404_NOT_FOUND)
    return item


def parse_scope(raw) -> str:
    scope = str(raw or "staff").strip().lower()
    if scope not in SCOPES:
        raise ShowcaseError("scope: staff или all")
    return scope


def candidates_qs(scope: str, query: str = ""):
    """Готовые дубли, которых в витрине ещё нет, — новые выше.

    scope=staff — только работы сотрудников: их снимают для витрины, и вопроса
    о согласии автора нет. all — работы всех: посмотреть можно, поставить
    нельзя (см. can_publish).
    """
    qs = _with_inputs(Take.objects.filter(_ready_q(), showcase__isnull=True)
                      .select_related("user", "result_asset", "shot__model"))
    if scope == "staff":
        qs = qs.filter(user__is_staff=True)
    if query:
        qs = qs.filter(Q(shot__prompt_text__icontains=query) | Q(user__email__icontains=query)
                       | Q(model_ref__icontains=query) | Q(uid=query))
    return qs.order_by(F("finished_at").desc(nulls_last=True), "-pk")


# ---------------------------------------------------------------- панель: правки

def _clean(data) -> dict:
    """Поля строки из тела запроса. Все проверки — до первой записи."""
    out: dict = {}
    if "title" in data:
        title = data["title"]
        if title is not None and not isinstance(title, str):
            raise ShowcaseError("Название — строка")
        title = re.sub(r"\s+", " ", pd.normalize_text(title or "")).strip()
        if len(title) > TITLE_MAX:
            raise ShowcaseError(f"Название длиннее {TITLE_MAX} символов")
        out["title"] = title
    if "category" in data:
        # Прежние ключи (social, anime) сюда уже не проходят: их перенесла миграция 0004.
        if data["category"] not in CATEGORIES:
            raise ShowcaseError("Сценарий: " + ", ".join(CATEGORIES))
        out["category"] = data["category"]
    if "sort" in data:
        sort = data["sort"]
        if isinstance(sort, bool) or not isinstance(sort, int) or abs(sort) > SORT_LIMIT:
            raise ShowcaseError(f"Порядок — целое число от −{SORT_LIMIT} до {SORT_LIMIT}")
        out["sort"] = sort
    for name in ("is_active", "show_prompt"):
        if name not in data:
            continue
        # Только настоящий булев: строка "false" из формы не должна включить показ.
        if not isinstance(data[name], bool):
            raise ShowcaseError(f"{name}: true или false")
        out[name] = data[name]
    return out


def _snapshot(item: ShowcaseItem) -> dict:
    return {"take": item.take.uid, "title": item.title, "category": item.category,
            "sort": item.sort, "is_active": item.is_active, "show_prompt": item.show_prompt}


def add(data, *, actor, request=None) -> tuple[ShowcaseItem, bool]:
    """Поставить дубль в витрину: (строка, создана ли).

    Дубль уже в витрине — отдаём его строку как есть: двойной клик не должен
    ни падать, ни молча переписывать название.
    """
    uid = data.get("take")
    take = (Take.objects.select_related("user", "result_asset", "shot__model").filter(uid=uid).first()
            if S.is_uid(uid) else None)
    if take is None:
        raise ShowcaseError("Дубль не найден", status=http.HTTP_404_NOT_FOUND)
    existing = _items_qs().filter(take=take).first()
    if existing is not None:
        return existing, False
    if not _is_ready(take):
        raise ShowcaseError("В витрину ставится только готовый дубль с сохранённым результатом")
    if not can_publish(take):
        raise ShowcaseError("В витрину пока ставятся только работы сотрудников")
    fields = _clean(data)
    try:
        with transaction.atomic():
            item = ShowcaseItem.objects.create(take=take, created_by=actor, **fields)
            # В журнал — в той же транзакции: не записалось, откатится и строка.
            log_admin_action(actor, LOG_ACTION, target=item, before={LOG_KEY: None},
                             after={LOG_KEY: _snapshot(item)}, request=request)
    except IntegrityError:
        # Второй запрос того же клика успел раньше: один дубль — одна строка.
        existing = _items_qs().filter(take=take).first()
        if existing is None:
            raise
        return existing, False
    return item, True


def edit(item: ShowcaseItem, data, *, actor, request=None) -> ShowcaseItem:
    """Поправить строку. Те же значения — ни записи в базу, ни строки в журнале."""
    new = _clean(data)
    if not new:
        raise ShowcaseError("Нечего менять")
    changed = {name: value for name, value in new.items() if getattr(item, name) != value}
    if not changed:
        return item
    before = {name: getattr(item, name) for name in changed}
    with transaction.atomic():
        for name, value in changed.items():
            setattr(item, name, value)
        item.save(update_fields=[*changed, "updated_at"])
        log_admin_action(actor, LOG_ACTION, target=item, before={LOG_KEY: before},
                         after={LOG_KEY: changed}, request=request)
    return item


def remove(item: ShowcaseItem, *, actor, request=None) -> None:
    """Убрать работу из витрины. Сам дубль и его файл не трогаем."""
    with transaction.atomic():
        # Журнал — до удаления: после него у строки уже нет номера.
        log_admin_action(actor, LOG_ACTION, target=item, before={LOG_KEY: _snapshot(item)},
                         after={LOG_KEY: None}, request=request)
        item.delete()


def _clean_reel_size(data) -> int:
    """Новый размер карусели из тела запроса. Все проверки — до первой записи."""
    if any(name != "reel_size" for name in data):
        raise ShowcaseError("Здесь меняется только размер карусели — поле reel_size")
    if "reel_size" not in data:
        raise ShowcaseError("Нечего менять")
    size = data["reel_size"]
    # Только настоящее целое: строку "24" шлёт форма, а True для Python тоже int.
    if (isinstance(size, bool) or not isinstance(size, int)
            or not REEL_SIZE_MIN <= size <= REEL_SIZE_MAX):
        raise ShowcaseError(
            f"Роликов в карусели — целое число от {REEL_SIZE_MIN} до {REEL_SIZE_MAX}")
    return size


def set_reel_size(data, *, actor, request=None) -> int:
    """Поменять размер карусели. То же значение — ни записи в базу, ни строки в журнале."""
    from adminapi.runtime import set_runtime

    size = _clean_reel_size(data)
    # «Было» читаем мимо кэша настроек: по устаревшему значению настоящая
    # правка сошла бы за повтор и не записалась.
    _forget_reel_size()
    before = reel_size()
    if before == size:
        return size
    with transaction.atomic():
        set_runtime(REEL_SIZE_KEY, size)
        # В журнал — в той же транзакции: не записалось, откатится и настройка.
        log_admin_action(actor, LOG_ACTION, before={REEL_SIZE_KEY: before},
                         after={REEL_SIZE_KEY: size}, request=request)
    # Пока транзакция запроса открыта, сосед мог прочитать из базы прежнее
    # значение и положить его в кэш настроек — после фиксации сбрасываем ещё раз.
    transaction.on_commit(_forget_reel_size)
    return size


__all__ = [
    "CACHE_KEY", "CACHE_S", "MAX_PUBLIC", "SCOPES", "CATEGORY_CHOICES", "CATEGORIES", "SCENARIOS",
    "REEL_SIZE_KEY", "REEL_SIZE_MIN", "REEL_SIZE_MAX", "REEL_SIZE_DEFAULT",
    "ShowcaseError",
    "needs_photo", "start_frame_url",
    "public_qs", "public_json", "public_items", "drop_cache", "forget_assets", "revive_assets",
    "reel_size",
    "enqueue_clip", "request_clip", "build_clip", "can_publish",
    "take_row", "staff_json", "staff_items", "get_item", "parse_scope", "candidates_qs",
    "add", "edit", "remove", "set_reel_size",
]
