"""Публикации креатора: добавление и ручная проверка.

Креатор присылает ссылку на пост, сотрудник открывает её и подтверждает или
отклоняет. В прогресс уровня идут только подтверждённые (ТЗ п.17–18).
Один пост засчитывается одному креатору: повтор ловится по нормализованной
ссылке, отклонённую можно подать снова.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs, quote, urlsplit

from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.services import log_admin_action

from .errors import CreatorsError
from .models import Creator, CreatorPublication
from .notify import emit

logger = logging.getLogger("creators")

URL_MAX = 500
DESCRIPTION_MAX = 500

# Параметры запроса, в которых живёт сам идентификатор поста. Всё остальное в
# запросе — метки отслеживания (utm, igshid, si…), с ними одна и та же
# публикация выглядела бы разными ссылками.
_KEEP_QUERY = {
    "youtube.com": ("v",),
    "facebook.com": ("v", "story_fbid", "fbid", "id"),
    "vk.com": ("w", "z"),
}


def normalize_url(url) -> str:
    """Привести ссылку к виду, по которому ищем повторы: хост + путь (+ id поста).

    Без схемы, www./m., хвостового слэша, якоря и меток отслеживания.
    """
    if not isinstance(url, str):
        raise CreatorsError("url_invalid")
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        raise CreatorsError("url_invalid") from None
    if parts.scheme.lower() not in ("http", "https") or not host:
        raise CreatorsError("url_invalid")
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    if not host:
        raise CreatorsError("url_invalid")

    path = parts.path.rstrip("/")
    kept = []
    keep = _KEEP_QUERY.get(host)
    if keep and parts.query:
        query = parse_qs(parts.query)
        for name in keep:
            value = (query.get(name) or [""])[0].strip()
            if value:
                kept.append(f"{name}={quote(value, safe='')}")
    return host + path + ("?" + "&".join(kept) if kept else "")


def _locked(publication_id) -> CreatorPublication:
    try:
        # of=("self",): блокируем только публикацию, не строку креатора.
        return (CreatorPublication.objects.select_for_update(of=("self",))
                .select_related("creator").get(pk=publication_id))
    except (CreatorPublication.DoesNotExist, TypeError, ValueError):
        raise CreatorsError("not_found") from None


def submit(creator, network: str, url: str, description: str = "") -> CreatorPublication:
    """Добавить публикацию на проверку."""
    status = Creator.objects.filter(pk=getattr(creator, "pk", None)).values_list(
        "status", flat=True).first()
    if status is None:
        raise CreatorsError("not_found")
    if status != Creator.Status.ACTIVE:
        raise CreatorsError("creator_blocked")
    network = str(network or "").strip().lower()
    if network not in CreatorPublication.Network.values:
        raise CreatorsError("network_invalid")
    if not isinstance(url, str):
        raise CreatorsError("url_invalid")
    url = url.replace("\x00", "").strip()
    if not url or len(url) > URL_MAX:
        raise CreatorsError("url_invalid")
    url_norm = normalize_url(url)
    description = str(description or "").replace("\x00", "").strip()[:DESCRIPTION_MAX]

    taken = (CreatorPublication.objects.filter(url_norm=url_norm)
             .exclude(status=CreatorPublication.Status.REJECTED).exists())
    if taken:
        raise CreatorsError("publication_duplicate")
    try:
        # Своя точка сохранения: два креатора с одной ссылкой одновременно —
        # второго остановит уникальный индекс, транзакция запроса должна выжить.
        with transaction.atomic():
            return CreatorPublication.objects.create(
                creator_id=creator.pk, network=network, url=url, url_norm=url_norm,
                description=description, status=CreatorPublication.Status.REVIEW)
    except IntegrityError:
        raise CreatorsError("publication_duplicate") from None


def _check_next_level(creator) -> None:
    """После подтверждения могли выполниться условия следующего уровня.

    Это только уведомление: уровень меняет администратор. Сбой подсчёта не
    должен отменять подтверждение публикации.
    """
    try:
        from creators.stats import check_next_level

        with transaction.atomic():
            check_next_level(creator)
    except Exception:  # noqa: BLE001
        logger.exception("creators.publications: check_next_level(%s) не выполнен",
                         getattr(creator, "pk", None))


def approve(publication_id, *, actor, request=None) -> CreatorPublication:
    """Подтвердить публикацию: с этого момента она идёт в прогресс уровня."""
    with transaction.atomic():
        publication = _locked(publication_id)
        if publication.status != CreatorPublication.Status.REVIEW:
            raise CreatorsError("bad_state")
        publication.status = CreatorPublication.Status.APPROVED
        publication.decided_by = actor
        publication.decided_at = timezone.now()
        publication.save(update_fields=["status", "decided_by", "decided_at"])
        log_admin_action(actor, "publication.approve", target=publication,
                         creator=publication.creator,
                         before={"status": CreatorPublication.Status.REVIEW.value},
                         after={"status": CreatorPublication.Status.APPROVED.value},
                         request=request)
        emit(publication.creator, "publication_approved", url=publication.url)
        _check_next_level(publication.creator)
    return publication


def reject(publication_id, *, actor, reason: str = "", request=None) -> CreatorPublication:
    """Отклонить публикацию. Ту же ссылку после этого можно подать снова."""
    reason = str(reason or "").replace("\x00", "").strip()
    with transaction.atomic():
        publication = _locked(publication_id)
        if publication.status != CreatorPublication.Status.REVIEW:
            raise CreatorsError("bad_state")
        publication.status = CreatorPublication.Status.REJECTED
        publication.reject_reason = reason
        publication.decided_by = actor
        publication.decided_at = timezone.now()
        publication.save(update_fields=["status", "reject_reason", "decided_by", "decided_at"])
        log_admin_action(actor, "publication.reject", target=publication,
                         creator=publication.creator,
                         before={"status": CreatorPublication.Status.REVIEW.value},
                         after={"status": CreatorPublication.Status.REJECTED.value},
                         reason=reason, request=request)
        emit(publication.creator, "publication_rejected", url=publication.url, reason=reason)
    return publication
