"""Права доступа кастомной админ-панели: только сотрудники (is_staff)."""
from rest_framework.permissions import BasePermission


class IsStaff(BasePermission):
    """Пускает только аутентифицированного пользователя с is_staff=True.

    Без токена DRF вернёт 401 (JWTAuthentication), с токеном не-стаффа — 403.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
        )
