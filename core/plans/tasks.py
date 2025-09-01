from __future__ import annotations
import logging
from celery import shared_task
from django.core.cache import cache
from plans.services import update_currency_rates

logger = logging.getLogger(__name__)
_LOCK_KEY = "plans:currency_update:lock"

@shared_task(
    name="plans.tasks.refresh_currency_rates",
    bind=True,
    autoretry_for=(RuntimeError, Exception),
    retry_backoff=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def refresh_currency_rates(self, force: bool = False) -> dict[str, str]:
    # naive lock
    if not force and not cache.add(_LOCK_KEY, "1", timeout=5 * 60):
        logger.info("Currency update skipped due to lock")
        return {}
    try:
        rates = update_currency_rates()
        cache.delete("plans:currency_per_usd:all")
        logger.info("Currency rates updated: %s", {k: str(v) for k, v in rates.items()})
        return {k: str(v) for k, v in rates.items()}
    finally:
        cache.delete(_LOCK_KEY)
