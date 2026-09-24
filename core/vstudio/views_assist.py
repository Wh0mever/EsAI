"""POST /api/vstudio/assist/condense/ — «Сжать с ИИ» (спецификация §4.8, §8.2).

Тело: {model, prompt_doc | prompt_text, inputs}. Ответ: {prompt_doc, before:{chars,
words}, after:{chars, words}}; не вышло — 422 condense_failed.

- Бесплатно: кредиты не резервируются и не списываются, запись в журнал
  генераций не создаётся (себестоимость около $0.001). От злоупотреблений —
  throttle vstudio_assist, 20 в час на человека.
- Вызов текстовой модели идёт до 30 с (а с повтором — до минуты), поэтому вьюха
  вне транзакции запроса (@non_atomic_requests): держать открытую транзакцию
  Postgres на время чужого HTTP незачем, а в базу мы ничего не пишем.
- Материалы — только свои (owned_by): чужой uid просто не найден, его тег в
  тексте всё равно сохраняется плейсхолдером и вернётся на своё место.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils.decorators import method_decorator
from rest_framework.response import Response

from . import assist, compiler
from . import prompt_doc as pd
from . import serializers as S
from .errors import StudioError
from .models import Asset
from .views import StudioAPIView, resolve_model

logger = logging.getLogger(__name__)

SCOPE_ASSIST = "vstudio_assist"
MODEL_UNAVAILABLE = "Эта модель сейчас недоступна. Выберите другую."


def _resolved_inputs(user, rows: list[dict]) -> list[compiler.ResolvedInput]:
    """Входы запроса → ResolvedInput только по материалам этого человека."""
    if not rows:
        return []
    uids = {row["asset"] for row in rows}
    assets = {a.uid: a for a in Asset.objects.owned_by(user).filter(uid__in=uids)}
    out = []
    for row in rows:
        asset = assets.get(row["asset"])
        if asset is None:
            continue
        out.append(compiler.ResolvedInput(compiler.AssetView.from_asset(asset), row["slot"],
                                          row["position"], row["role"], row["included"]))
    return out


def _doc_from_body(data: dict, inputs) -> dict:
    """Ровно одно из prompt_doc / prompt_text (как в quote): кривое — 422 prompt_doc_invalid."""
    has_doc = data.get("prompt_doc") is not None
    has_text = data.get("prompt_text") is not None
    if has_doc == has_text:
        raise S.bad("prompt_doc")
    try:
        if has_doc:
            return pd.validate(data.get("prompt_doc"))
        text = data.get("prompt_text")
        if not isinstance(text, str) or len(text) > S.MAX_PROMPT_TEXT_RAW:
            raise S.bad("prompt_text")
        return pd.from_text(text, inputs).doc
    except pd.PromptDocError:
        raise StudioError("prompt_doc_invalid") from None


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class CondenseView(StudioAPIView):
    """POST assist/condense/ — было/стало для диалога; ничего не сохраняет."""

    scopes = {"POST": SCOPE_ASSIST}
    default_scope = SCOPE_ASSIST

    def post(self, request):
        data = S.body_dict(request)
        model_ref = data.get("model")
        if not isinstance(model_ref, str) or not model_ref.strip() or len(model_ref) > S.MAX_MODEL_REF:
            raise S.bad("model")
        inputs = _resolved_inputs(request.user, S.parse_inputs(data.get("inputs")))
        doc = _doc_from_body(data, inputs)

        _model_obj, caps, _spec = resolve_model(model_ref.strip())
        if caps is None:
            # Скрытая или неизвестная модель: лимитов нет — сжимать не под что.
            raise StudioError("model_unavailable", status=422, message=MODEL_UNAVAILABLE)

        try:
            result = assist.condense(caps, doc, inputs)
        except assist.CondenseError as err:
            logger.info("vstudio condense refused user=%s model=%s reason=%s attempts=%s",
                        request.user.pk, caps.model, err.reason, err.attempts)
            raise StudioError(assist.CondenseError.code, status=422, message=err.message,
                              reason=err.reason) from None
        logger.info("vstudio condense user=%s model=%s attempts=%s words %s→%s",
                    request.user.pk, caps.model, result.attempts, result.before["words"],
                    result.after["words"])
        return Response(result.to_json())


__all__ = ["CondenseView", "SCOPE_ASSIST"]
