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


class IsSuperuser(BasePermission):
    """Пускает только сотрудника с is_superuser=True.

    Для действий с деньгами и структурой программы Creators (выплаты, уровни,
    коды, перепривязка, Creator Credits, блокировки): проверять заявки может
    любой сотрудник, распоряжаться деньгами — только главный администратор.
    """

    message = "Это действие доступно только главному администратору"
    code = "superuser_required"

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
            and request.user.is_superuser
        )
