from __future__ import annotations

# Music and image generation Celery tasks were removed for the text-only ESAI build.
# This module is intentionally kept (without tasks) so existing imports of
# `core.celery.app` and Celery autodiscovery remain valid.

from core.celery import app  # noqa: F401
