from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests


def _default_cache_dir() -> str:
    return os.getenv("NBA_WATCH_CACHE_DIR", os.path.join(os.getcwd(), ".cache"))


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _hash_key(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]


def _cache_path(namespace: str, key: str) -> str:
    cache_dir = _default_cache_dir()
    path = os.path.join(cache_dir, "http", namespace)
    _ensure_dir(path)
    return os.path.join(path, f"{_hash_key(key)}.json")


def _read_json(path: str) -> Optional[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: str, payload: dict[str, Any]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


@dataclass(frozen=True)
class CachedResponse:
    url: str
    data: Any
    from_cache: bool


def get_json_cached(
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    namespace: str = "default",
    cache_key: Optional[str] = None,
    ttl_seconds: int = 600,
    timeout_seconds: int = 10,
) -> CachedResponse:
    key = cache_key or url + ("?" + json.dumps(params, sort_keys=True) if params else "")
    path = _cache_path(namespace, key)
    now = time.time()

    cached = _read_json(path)
    if cached:
        ts = float(cached.get("_ts", 0))
        if now - ts <= float(ttl_seconds):
            return CachedResponse(url=url, data=cached.get("data"), from_cache=True)

    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout_seconds)
        r.raise_for_status()
        data = r.json()
        _write_json(path, {"_ts": now, "data": data})
        return CachedResponse(url=url, data=data, from_cache=False)
    except Exception:
        # If we have *any* cached data (even if stale), prefer returning it over failing hard.
        if cached and "data" in cached:
            return CachedResponse(url=url, data=cached.get("data"), from_cache=True)
        raise
