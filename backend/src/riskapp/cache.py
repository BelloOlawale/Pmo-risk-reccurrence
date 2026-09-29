"""Tiny in-process TTL cache for read-heavy, rarely-changing lookups.

The API is latency-bound by round-trips to a database in a different region,
so caching a couple of small, slow-changing option sets removes a round-trip
from most page loads. This is deliberately per-process and best-effort: a
stale-but-valid response for a few tens of seconds is fine for these lookups,
and each replica simply warms its own copy. Every cache is registered so tests
(and any future admin action) can clear them all.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar, cast

T = TypeVar("T")

_instances: list[TtlCache] = []


class TtlCache:
    """A single value with a time-to-live, refreshed on demand."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._value: Any = None
        self._has_value = False
        self._expires_at = 0.0
        _instances.append(self)

    def get_or_set(self, factory: Callable[[], T]) -> T:
        """Return the cached value, computing and storing it when stale/absent."""
        now = time.monotonic()
        with self._lock:
            if self._has_value and now < self._expires_at:
                return cast(T, self._value)
        # Compute outside the lock: a concurrent miss may compute twice, but the
        # value is small and this keeps a slow factory from blocking readers.
        value = factory()
        with self._lock:
            self._value = value
            self._has_value = True
            self._expires_at = time.monotonic() + self._ttl
        return value

    def clear(self) -> None:
        with self._lock:
            self._value = None
            self._has_value = False
            self._expires_at = 0.0


def clear_caches() -> None:
    """Drop every registered cache (used between tests)."""
    for cache in _instances:
        cache.clear()
