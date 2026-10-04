"""Права кабинета креатора.

Отказ отдаётся кодом программы (403 not_creator / creator_blocked), а не общим
«доступ запрещён»: по коду фронтенд решает, показать форму заявки или экран
«аккаунт заблокирован». Без входа отвечает сам DRF — 401.
"""
from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

from .errors import CreatorsError
from .models import Creator


def creator_of(user):
    """Строка креатора этого человека или None (user.creator у не-креатора бросает)."""
    if user is None or not getattr(user, "pk", None):
        return None
    return Creator.objects.filter(user_id=user.pk).select_related("level", "user").first()


class IsCreator(BasePermission):
    """Вошёл и состоит в программе. Заблокированный креатор только читает.

    Найденную строку кладёт в request.creator — вьюхе не нужен второй запрос.
    """

    # Заблокированному закрыто вообще всё (а не только запись).
    active_only = False

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return False
        creator = creator_of(user)
        if creator is None:
            raise CreatorsError("not_creator")
        blocked = creator.status != Creator.Status.ACTIVE
        if blocked and (self.active_only or request.method not in SAFE_METHODS):
            raise CreatorsError("creator_blocked")
        request.creator = creator
        return True


class IsActiveCreator(IsCreator):
    """Только действующий креатор (status == "active")."""

    active_only = True
