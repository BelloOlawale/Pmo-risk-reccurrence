"""Unit tests for the in-process TTL cache used by read-heavy endpoints."""

from __future__ import annotations

import time

from riskapp import cache


def test_get_or_set_caches_until_ttl_expires() -> None:
    ttl = cache.TtlCache(ttl_seconds=0.05)
    calls = {"n": 0}

    def factory() -> int:
        calls["n"] += 1
        return calls["n"]

    assert ttl.get_or_set(factory) == 1
    assert ttl.get_or_set(factory) == 1  # served from cache
    assert calls["n"] == 1

    time.sleep(0.06)
    assert ttl.get_or_set(factory) == 2  # recomputed after expiry
    assert calls["n"] == 2


def test_clear_forces_recompute() -> None:
    ttl = cache.TtlCache(ttl_seconds=3600)
    calls = {"n": 0}

    def factory() -> int:
        calls["n"] += 1
        return calls["n"]

    assert ttl.get_or_set(factory) == 1
    ttl.clear()
    assert ttl.get_or_set(factory) == 2
