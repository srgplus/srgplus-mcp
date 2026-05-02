"""Eviction tests for the per-request SRGClient LRU cache.

Covers SRGDEV-23: previously _client_cache was an unbounded dict, which would
grow without limit on a long-lived Cloud Run revision serving many distinct
workspace api_keys. Bounded LRU keeps memory predictable.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from srg_mcp.serve import _patch


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test gets a fresh cache so they don't bleed into each other."""
    _patch._client_cache.clear()
    yield
    _patch._client_cache.clear()


class _StubClient:
    """Minimal stand-in for srg.SRGClient — avoids any real network/auth."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key


def _bind_and_resolve(api_key: str) -> _StubClient:
    """Helper: bind api_key into the contextvar and resolve a client."""
    token = _patch.set_current_key(api_key)
    try:
        with patch("srg_mcp.serve._patch.srg.SRGClient", _StubClient):
            return _patch._contextual_get_client()  # type: ignore[return-value]
    finally:
        _patch.reset_current_key(token)


def test_cache_returns_same_client_for_repeated_key():
    """Within capacity, the same key resolves to the same cached client."""
    a = _bind_and_resolve("key-a")
    b = _bind_and_resolve("key-a")
    assert a is b


def test_cache_evicts_oldest_at_capacity_plus_one():
    """The 513th unique key evicts the very first one (LRU semantics)."""
    maxsize = _patch._CLIENT_CACHE_MAXSIZE
    assert maxsize == 512

    # Fill the cache up to capacity.
    for i in range(maxsize):
        _bind_and_resolve(f"key-{i}")
    assert len(_patch._client_cache) == maxsize
    assert "key-0" in _patch._client_cache

    # One more pushes the cache over capacity → oldest entry is evicted.
    _bind_and_resolve(f"key-{maxsize}")  # the 513th unique key
    assert len(_patch._client_cache) == maxsize
    assert "key-0" not in _patch._client_cache
    assert f"key-{maxsize}" in _patch._client_cache


def test_cache_lru_recency_protects_recently_used_keys():
    """Touching a key bumps it to MRU so it survives subsequent eviction."""
    maxsize = _patch._CLIENT_CACHE_MAXSIZE

    for i in range(maxsize):
        _bind_and_resolve(f"key-{i}")

    # Re-touch key-0 so it becomes most recently used.
    _bind_and_resolve("key-0")

    # Now insert a new key — key-1 should be evicted (oldest), not key-0.
    _bind_and_resolve("new-key")
    assert "key-0" in _patch._client_cache
    assert "key-1" not in _patch._client_cache
