from __future__ import annotations

import hashlib
from typing import Any, Dict, List
from urllib.parse import urlparse


def _collect_values(params: Any) -> List[str]:
    """Collect values in alphabetical key order, recursively.

    Mirrors common Paybox signature behavior: arrays/dicts flattened to a
    sequence of values; keys sorted alphabetically; exclude pg_sig itself.
    """
    if isinstance(params, dict):
        items: List[str] = []
        for k in sorted(params.keys()):
            if k == "pg_sig":
                continue
            items.extend(_collect_values(params[k]))
        return items
    if isinstance(params, (list, tuple)):
        items: List[str] = []
        for v in params:
            items.extend(_collect_values(v))
        return items
    return ["" if params is None else str(params)]


def method_name_from_path(path: str) -> str:
    """Derive API method name from URL path, e.g. '/v1/.../card/pay' -> 'pay'."""
    p = urlparse(path).path if "://" in path else path
    parts = [s for s in p.split("/") if s]
    return parts[-1] if parts else "pay"


def calculate_pg_sig(method_name: str, params: Dict[str, Any], secret: str, algo: str = "md5") -> str:
    """Calculate pg_sig according to FreedomPay/Paybox spec.

    IMPORTANT: Follow the official docs precisely for your integration.
    The typical pattern is:
      - Build list: [method_name] + flattened(sorted(params)) + [secret]
      - Join with ';' and hash with MD5 (or SHA256 per spec/setting)

    Replace with the exact algorithm from FreedomPay docs if it differs.
    """
    values = _collect_values(params)
    base = [method_name] + values + [secret or ""]
    payload = ";".join(base).encode("utf-8")
    if algo.lower() == "sha256":
        return hashlib.sha256(payload).hexdigest()
    return hashlib.md5(payload).hexdigest()  # nosec B303 - per provider spec

