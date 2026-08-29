"""Аккаунты OpenRouter в панели: подключить, проверить, переключиться.

Задача клиента: ключ был один, и когда на нём кончались деньги, вставал весь
сайт. Теперь аккаунтов может быть несколько, а переключение — в один клик,
без похода на сервер.

Ключ наружу не отдаётся никогда, даже администратору: в списке он показан
огрызком вида «sk-or-v1-abc…9f21». Панель и так под JWT со staff-правами, но
секрет, который незачем показывать, лучше не показывать вовсе — он утечёт с
первым же скриншотом, отправленным в переписке.
"""
from __future__ import annotations

import requests as http_requests
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from ai.models import OpenRouterAccount

from .views import StaffAPIView

CREDITS_URL = "https://openrouter.ai/api/v1/credits"


def check_key(key: str) -> dict:
    """Спросить у OpenRouter, сколько денег на ключе.

    Возвращает {ok, balance, spent, limit, error}. Ошибку не поднимаем:
    неверный ключ — обычное дело при подключении, и человеку нужно увидеть
    причину, а не пятисотую страницу.
    """
    key = (key or "").strip()
    if not key:
        return {"ok": False, "error": "Ключ не задан"}
    try:
        r = http_requests.get(CREDITS_URL, headers={"Authorization": f"Bearer {key}"},
                              timeout=12)
    except Exception as exc:
        return {"ok": False, "error": f"OpenRouter недоступен: {exc}"}

    if r.status_code == 401:
        return {"ok": False, "error": "OpenRouter не принял ключ (401)"}
    if r.status_code != 200:
        return {"ok": False, "error": f"OpenRouter ответил HTTP {r.status_code}"}
    try:
        d = (r.json() or {}).get("data") or {}
        limit = float(d.get("total_credits") or 0)
        spent = float(d.get("total_usage") or 0)
    except Exception:
        return {"ok": False, "error": "Не удалось разобрать ответ OpenRouter"}
    return {"ok": True, "balance": round(limit - spent, 2),
            "spent": round(spent, 2), "limit": round(limit, 2), "error": ""}


def refresh(account: OpenRouterAccount) -> OpenRouterAccount:
    """Обновить снимок баланса аккаунта."""
    res = check_key(account.api_key)
    account.checked_at = timezone.now()
    if res["ok"]:
        account.balance_usd = res["balance"]
        account.spent_usd = res["spent"]
        account.limit_usd = res["limit"]
        account.last_error = ""
    else:
        account.last_error = res.get("error") or "неизвестная ошибка"
    account.save(update_fields=["balance_usd", "spent_usd", "limit_usd",
                                "checked_at", "last_error"])
    return account


def account_json(a: OpenRouterAccount) -> dict:
    return {
        "id": a.id,
        "title": a.title,
        "key_masked": a.masked_key(),
        "is_active": a.is_active,
        "note": a.note,
        "balance_usd": a.balance_usd,
        "spent_usd": a.spent_usd,
        "limit_usd": a.limit_usd,
        "checked_at": a.checked_at.isoformat() if a.checked_at else None,
        "last_error": a.last_error,
    }


class AccountsView(StaffAPIView):
    """GET — список аккаунтов. POST — подключить новый."""

    def get(self, request):
        return Response([account_json(a) for a in OpenRouterAccount.objects.all()])

    def post(self, request):
        data = request.data or {}
        key = str(data.get("api_key") or "").strip()
        title = str(data.get("title") or "").strip()[:80]
        if not key:
            return Response({"detail": "Вставьте ключ OpenRouter"},
                            status=status.HTTP_400_BAD_REQUEST)
        if OpenRouterAccount.objects.filter(api_key=key).exists():
            return Response({"detail": "Этот ключ уже подключён"},
                            status=status.HTTP_400_BAD_REQUEST)

        # Ключ проверяем ДО сохранения: подключить неработающий аккаунт и
        # узнать об этом, когда на него переключились, — худший из сценариев.
        res = check_key(key)
        if not res["ok"]:
            return Response({"detail": res.get("error") or "Ключ не работает"},
                            status=status.HTTP_400_BAD_REQUEST)

        account = OpenRouterAccount.objects.create(
            title=title or "Аккаунт OpenRouter",
            api_key=key,
            note=str(data.get("note") or "").strip()[:2000],
            balance_usd=res["balance"], spent_usd=res["spent"], limit_usd=res["limit"],
            checked_at=timezone.now(),
            # Первый подключённый аккаунт сразу становится рабочим: иначе можно
            # завести его и не понять, почему ничего не изменилось.
            is_active=not OpenRouterAccount.objects.filter(is_active=True).exists(),
        )
        return Response(account_json(account), status=status.HTTP_201_CREATED)


class AccountDetailView(StaffAPIView):
    """PATCH — переименовать, заменить ключ. DELETE — убрать аккаунт."""

    def patch(self, request, pk):
        account = get_object_or_404(OpenRouterAccount, pk=pk)
        data = request.data or {}
        fields = []

        if "title" in data:
            account.title = str(data["title"] or "").strip()[:80] or account.title
            fields.append("title")
        if "note" in data:
            account.note = str(data["note"] or "").strip()[:2000]
            fields.append("note")

        key = str(data.get("api_key") or "").strip()
        if key and key != account.api_key:
            res = check_key(key)
            if not res["ok"]:
                return Response({"detail": res.get("error") or "Ключ не работает"},
                                status=status.HTTP_400_BAD_REQUEST)
            account.api_key = key
            account.balance_usd, account.spent_usd = res["balance"], res["spent"]
            account.limit_usd, account.checked_at = res["limit"], timezone.now()
            account.last_error = ""
            fields += ["api_key", "balance_usd", "spent_usd", "limit_usd",
                       "checked_at", "last_error"]

        if fields:
            account.save(update_fields=fields)
        return Response(account_json(account))

    def delete(self, request, pk):
        account = get_object_or_404(OpenRouterAccount, pk=pk)
        if account.is_active:
            # Удалить рабочий аккаунт — это остановить сайт молча.
            return Response(
                {"detail": "Сначала переключитесь на другой аккаунт"},
                status=status.HTTP_400_BAD_REQUEST)
        account.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AccountActivateView(StaffAPIView):
    """POST — сделать аккаунт рабочим. С этого мгновения с него идут все запросы."""

    def post(self, request, pk):
        account = get_object_or_404(OpenRouterAccount, pk=pk)
        refresh(account)
        if account.last_error:
            return Response({"detail": f"Аккаунт не отвечает: {account.last_error}"},
                            status=status.HTTP_400_BAD_REQUEST)
        account.is_active = True
        account.save(update_fields=["is_active"])
        return Response([account_json(a) for a in OpenRouterAccount.objects.all()])


class AccountRefreshView(StaffAPIView):
    """POST — перепроверить балансы. Без pk — все аккаунты разом."""

    def post(self, request, pk=None):
        if pk is not None:
            refresh(get_object_or_404(OpenRouterAccount, pk=pk))
        else:
            for a in OpenRouterAccount.objects.all():
                refresh(a)
        return Response([account_json(a) for a in OpenRouterAccount.objects.all()])
