"""Эндпоинты панели /admin-new для блокировок (раздел «Блокировки»).

Отдельный модуль, а не хвост views.py: там уже 700+ строк, и мешать в ту же
кучу ещё одну тему смысла нет.

Что умеет:
  * список правил с числом попавших под них аккаунтов;
  * создание правила — сразу отключает подходящие аккаунты и ВОЗВРАЩАЕТ их
    список, чтобы панель показала «заблокировано N аккаунтов» с именами;
  * снятие правила — возвращает доступ отключённым по нему;
  * точечное отключение/возврат одного аккаунта;
  * «подозрительные» — домены, устройства и IP, с которых заведено больше
    одного аккаунта: по ним клиент и находит одноразовую почту.

Сами правила и их применение — в users/models.py::SignupBlock и
users/blocklist.py.
"""
from __future__ import annotations

import ipaddress
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from .views import StaffAPIView

User = get_user_model()

# Сколько аккаунтов отдаём в одном ответе. Панель показывает их списком, и
# несколько сотен строк она уже не переварит осмысленно.
ACCOUNTS_LIMIT = 200


def matching_users(kind: str, value: str):
    """Аккаунты, попадающие под правило.

    Домен ищем по почте, остальное — по слепкам регистрации
    (audit.SignupDevice): только там сохраняются IP и ключ устройства.
    """
    from audit.models import SignupDevice

    value = (value or "").strip().lower()
    if not value:
        return User.objects.none()

    if kind == "domain":
        # Поддомены тоже: @jmaie.com и @mail.jmaie.com.
        return User.objects.filter(
            Q(email__iendswith=f"@{value}") | Q(email__iendswith=f".{value}")
        ).order_by("date_joined")

    if kind == "device":
        ids = SignupDevice.objects.filter(fingerprint=value).values_list("user_id", flat=True)
        return User.objects.filter(id__in=list(ids)).order_by("date_joined")

    if kind == "ip":
        ids = SignupDevice.objects.filter(ip=value).values_list("user_id", flat=True)
        return User.objects.filter(id__in=list(ids)).order_by("date_joined")

    # Подсеть: сравниваем в питоне — БД про CIDR не знает.
    try:
        net = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return User.objects.none()
    ids = []
    for d in SignupDevice.objects.exclude(ip=None).only("user_id", "ip"):
        try:
            if ipaddress.ip_address(str(d.ip)) in net:
                ids.append(d.user_id)
        except ValueError:
            continue
    return User.objects.filter(id__in=ids).order_by("date_joined")


def account_brief(u) -> dict:
    full_name = f"{getattr(u, 'first_name', '') or ''} {getattr(u, 'last_name', '') or ''}".strip()
    return {
        "id": u.id,
        "email": u.email,
        "name": full_name or u.email,
        "is_active": bool(u.is_active),
        "balance": getattr(u, "token_balance", 0),
        "date_joined": u.date_joined.isoformat() if u.date_joined else None,
    }


def block_payload(rule, with_accounts: bool = False) -> dict:
    accounts = matching_users(rule.kind, rule.value)
    data = {
        "id": rule.id,
        "kind": rule.kind,
        "kind_label": rule.get_kind_display(),
        "value": rule.value,
        "block_login": rule.block_login,
        "reason": rule.reason,
        "is_active": rule.is_active,
        "hits": rule.hits,
        "last_hit_at": rule.last_hit_at.isoformat() if rule.last_hit_at else None,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "accounts_total": accounts.count(),
        "accounts_blocked": accounts.filter(is_active=False).count(),
    }
    if with_accounts:
        data["accounts"] = [account_brief(u) for u in accounts[:ACCOUNTS_LIMIT]]
    return data


class BlocksListView(StaffAPIView):
    """GET список правил, POST создать новое."""

    def get(self, request):
        from users.models import SignupBlock

        return Response([block_payload(r) for r in SignupBlock.objects.all()])

    def post(self, request):
        from users.blocklist import normalize_domain
        from users.models import SignupBlock

        kind = (request.data.get("kind") or "domain").strip()
        value = (request.data.get("value") or "").strip()
        if kind not in dict(SignupBlock.KIND_CHOICES):
            return Response({"detail": "Неизвестный тип правила"}, status=status.HTTP_400_BAD_REQUEST)
        if not value:
            return Response({"detail": "Укажите значение"}, status=status.HTTP_400_BAD_REQUEST)

        # Дубль ищем по НОРМАЛИЗОВАННОМУ значению (нормализация живёт в
        # SignupBlock.save): иначе «@Jmaie.com» и «jmaie.com» прошли бы как
        # разные правила и упали бы на unique_together уже в базе.
        normalized = (
            normalize_domain(value) if kind == SignupBlock.KIND_DOMAIN else value.lower()
        )
        if SignupBlock.objects.filter(kind=kind, value=normalized).exists():
            return Response({"detail": "Такое правило уже есть"}, status=status.HTTP_400_BAD_REQUEST)

        rule = SignupBlock(
            kind=kind,
            value=value,
            block_login=bool(request.data.get("block_login", True)),
            reason=(request.data.get("reason") or "").strip()[:255],
        )
        rule.save()

        # По умолчанию правило сразу закрывает уже заведённые аккаунты — иначе
        # смысл «забанить» терялся бы: старые аккаунты продолжали бы работать.
        just_blocked: list[dict] = []
        if request.data.get("deactivate", True):
            qs = matching_users(rule.kind, rule.value).filter(is_active=True)
            just_blocked = [account_brief(u) for u in qs[:ACCOUNTS_LIMIT]]
            qs.update(is_active=False)

        payload = block_payload(rule, with_accounts=True)
        payload["just_blocked"] = just_blocked
        return Response(payload, status=status.HTTP_201_CREATED)


class BlockDetailView(StaffAPIView):
    """GET подробности, PATCH правка, DELETE снять правило.

    Снятие ВОЗВРАЩАЕТ доступ отключённым по правилу аккаунтам: иначе правило
    убиралось бы только на будущее, а люди оставались бы отключёнными навсегда.
    Отключить возврат можно параметром ?restore=0.
    """

    def get(self, request, pk):
        from users.models import SignupBlock

        return Response(block_payload(get_object_or_404(SignupBlock, pk=pk), with_accounts=True))

    def patch(self, request, pk):
        from users.models import SignupBlock

        rule = get_object_or_404(SignupBlock, pk=pk)
        for field in ("block_login", "is_active"):
            if field in request.data:
                setattr(rule, field, bool(request.data[field]))
        if "reason" in request.data:
            rule.reason = (request.data.get("reason") or "").strip()[:255]
        rule.save()
        return Response(block_payload(rule, with_accounts=True))

    def delete(self, request, pk):
        from users.models import SignupBlock

        rule = get_object_or_404(SignupBlock, pk=pk)
        restored = 0
        if request.query_params.get("restore", "1") not in ("0", "false", "no"):
            restored = (
                matching_users(rule.kind, rule.value)
                .filter(is_active=False)
                .update(is_active=True)
            )
        rule.delete()
        return Response({"restored": restored})


class BlockAccountsView(StaffAPIView):
    """POST отключить/вернуть аккаунты правила — все или один.

    Тело: {"action": "block" | "unblock", "user_id": <необязательно>}.
    """

    def post(self, request, pk):
        from users.models import SignupBlock

        rule = get_object_or_404(SignupBlock, pk=pk)
        action = (request.data.get("action") or "block").strip()
        target_active = action == "unblock"

        qs = matching_users(rule.kind, rule.value)
        user_id = request.data.get("user_id")
        if user_id:
            qs = qs.filter(id=user_id)
        qs = qs.filter(is_active=not target_active)

        affected = [account_brief(u) for u in qs[:ACCOUNTS_LIMIT]]
        count = qs.update(is_active=target_active)
        return Response({
            "action": action,
            "count": count,
            "accounts": affected,
            "rule": block_payload(rule, with_accounts=True),
        })


class BlockSuspectsView(StaffAPIView):
    """GET домены, устройства и IP, похожие на фабрики аккаунтов.

    Ровно то, о чём просил клиент: «найдём такие одноразовые — заблокируем
    массово». Крупные почтовики отфильтрованы: иначе gmail всегда наверху и
    закрывает собой настоящую аномалию.
    """

    KNOWN_MAIL = {
        "gmail.com", "googlemail.com", "yandex.ru", "yandex.com", "ya.ru",
        "mail.ru", "bk.ru", "inbox.ru", "list.ru", "internet.ru",
        "outlook.com", "hotmail.com", "live.com", "icloud.com", "me.com",
        "yahoo.com", "rambler.ru", "proton.me", "protonmail.com",
        "esai.kg", "social.esai.local",
    }

    def get(self, request):
        from audit.models import SignupDevice

        by_domain: dict[str, list] = defaultdict(list)
        for email, active, joined in User.objects.exclude(email="").values_list(
            "email", "is_active", "date_joined"
        ):
            dom = (email or "").rsplit("@", 1)[-1].strip().lower()
            if dom:
                by_domain[dom].append((active, joined))

        domains = []
        for dom, rows in by_domain.items():
            # Один аккаунт на домене — это обычная корпоративная почта, а не
            # фабрика. Показываем от двух.
            if dom in self.KNOWN_MAIL or len(rows) < 2:
                continue
            domains.append({
                "value": dom,
                "accounts": len(rows),
                "active": sum(1 for r in rows if r[0]),
                "first_seen": min(r[1] for r in rows).isoformat(),
                "last_seen": max(r[1] for r in rows).isoformat(),
            })
        domains.sort(key=lambda d: -d["accounts"])

        dev_map: dict[str, set] = defaultdict(set)
        ip_map: dict[str, set] = defaultdict(set)
        for fp, ip, uid in SignupDevice.objects.exclude(user_id=None).values_list(
            "fingerprint", "ip", "user_id"
        ):
            if fp:
                dev_map[fp].add(uid)
            if ip:
                ip_map[str(ip)].add(uid)

        devices = sorted(
            ({"value": fp, "accounts": len(ids)} for fp, ids in dev_map.items() if len(ids) > 1),
            key=lambda d: -d["accounts"],
        )
        # По IP порог выше: за одним адресом законно сидит целый офис или
        # мобильный оператор, два аккаунта там ничего не значат.
        ips = sorted(
            ({"value": ip, "accounts": len(ids)} for ip, ids in ip_map.items() if len(ids) > 2),
            key=lambda d: -d["accounts"],
        )

        return Response({
            "domains": domains[:40],
            "devices": devices[:40],
            "ips": ips[:40],
        })
