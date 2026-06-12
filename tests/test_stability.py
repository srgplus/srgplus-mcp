"""Stability fixes: bounded client cache, timeouts, tool error wrapper,
health's oauth_keys_persistent flag."""

from __future__ import annotations

import httpx
import pytest

import srg.exceptions

import srg_mcp._client as client_mod
from srg_mcp.serve._tool_errors import (
    _format_client_message,
    install_tool_error_wrapper,
)


class _DummyClient:
    """Stands in for srg.SRGClient — records init kwargs and close calls."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def clean_cache(monkeypatch):
    """Isolated client cache with the dummy SRGClient."""
    monkeypatch.setattr(client_mod.srg, "SRGClient", _DummyClient)
    monkeypatch.setattr(client_mod, "_clients", {})
    monkeypatch.setattr(client_mod, "_last_used", {})
    yield


def _get_for_key(key: str):
    token = client_mod.set_current_api_key(key)
    try:
        return client_mod.get_client()
    finally:
        client_mod.reset_current_api_key(token)


# --------------------------------------------------------------- client cache


def test_client_built_with_timeout_and_parsed_keys(clean_cache):
    c = _get_for_key("srgplus_aaa, srgplus_bbb,")
    assert c.kwargs["api_keys"] == ["srgplus_aaa", "srgplus_bbb"]
    assert c.kwargs["timeout"] == client_mod._HTTP_TIMEOUT_SECONDS


def test_client_cached_per_key(clean_cache):
    assert _get_for_key("srgplus_aaa") is _get_for_key("srgplus_aaa")
    assert _get_for_key("srgplus_aaa") is not _get_for_key("srgplus_bbb")


def test_idle_entries_evicted_and_closed(clean_cache):
    stale = _get_for_key("srgplus_old")
    # Backdate the entry beyond the idle TTL, then touch the cache again.
    client_mod._last_used["srgplus_old"] -= client_mod._CACHE_TTL_SECONDS + 1
    fresh = _get_for_key("srgplus_new")
    assert stale.closed
    assert not fresh.closed
    assert "srgplus_old" not in client_mod._clients


def test_size_cap_evicts_lru(clean_cache, monkeypatch):
    monkeypatch.setattr(client_mod, "_CACHE_MAX", 2)
    first = _get_for_key("srgplus_1")
    second = _get_for_key("srgplus_2")
    _get_for_key("srgplus_1")  # refresh 1 → 2 becomes LRU
    third = _get_for_key("srgplus_3")
    assert second.closed
    assert not first.closed and not third.closed
    assert set(client_mod._clients) == {"srgplus_1", "srgplus_3"}


def test_active_use_refreshes_ttl(clean_cache):
    c = _get_for_key("srgplus_busy")
    client_mod._last_used["srgplus_busy"] -= client_mod._CACHE_TTL_SECONDS - 60
    assert _get_for_key("srgplus_busy") is c  # refreshed, not evicted
    assert not c.closed


# --------------------------------------------------------- tool error wrapper


def _status_error(cls, status: int, detail: str):
    response = httpx.Response(status, request=httpx.Request("GET", "http://t"))
    return cls(body={"detail": detail}, response=response)


def test_format_api_status_error_includes_hint():
    exc = _status_error(srg.exceptions.AuthenticationError, 401, "Unauthorized")
    message, status = _format_client_message("list_workspaces", exc)
    assert status == 401
    assert "SRG+ API error (401) in list_workspaces" in message
    assert "revoked" in message  # actionable hint


def test_format_timeout():
    message, status = _format_client_message(
        "upload_asset", httpx.ReadTimeout("boom")
    )
    assert status == "timeout"
    assert "upload_asset" in message


def test_format_passes_through_unrelated_errors():
    assert _format_client_message("t", ValueError("nope")) is None


def _make_mcp_with_tools():
    from mcp.server.fastmcp import FastMCP

    test_mcp = FastMCP("test")

    @test_mcp.tool()
    def boom_api() -> str:
        raise _status_error(srg.exceptions.NotFoundError, 404, "gone")

    @test_mcp.tool()
    def boom_bug() -> str:
        raise ValueError("a programming bug")

    @test_mcp.tool()
    def fine() -> str:
        return "ok"

    return test_mcp


def test_wrapper_converts_api_errors_and_preserves_others():
    test_mcp = _make_mcp_with_tools()
    assert install_tool_error_wrapper(test_mcp) == 3
    tools = test_mcp._tool_manager._tools

    with pytest.raises(RuntimeError) as ri:
        tools["boom_api"].fn()
    assert "SRG+ API error (404) in boom_api" in str(ri.value)
    assert isinstance(ri.value.__cause__, srg.exceptions.NotFoundError)

    with pytest.raises(ValueError):
        tools["boom_bug"].fn()

    assert tools["fine"].fn() == "ok"


def test_wrapper_is_idempotent():
    test_mcp = _make_mcp_with_tools()
    assert install_tool_error_wrapper(test_mcp) == 3
    assert install_tool_error_wrapper(test_mcp) == 0  # already wrapped


def test_all_served_tools_are_wrapped():
    # serve/main.py installs the wrapper at import time on the real instance.
    import srg_mcp.serve.main  # noqa: F401
    from srg_mcp._app import mcp

    tools = mcp._tool_manager._tools
    assert len(tools) >= 90
    unwrapped = [
        name
        for name, tool in tools.items()
        if not getattr(tool.fn, "_srg_error_wrapped", False)
    ]
    assert unwrapped == []


# ------------------------------------------------------------------- /health


@pytest.mark.asyncio
async def test_health_reports_persistent_oauth_keys(client):
    # conftest sets all three OAUTH_* env vars for the suite
    body = (await client.get("/health")).json()
    assert body["oauth_keys_persistent"] is True


@pytest.mark.asyncio
async def test_health_flags_ephemeral_oauth_keys(client, monkeypatch):
    monkeypatch.delenv("OAUTH_TOKEN_SIGNING_KEY", raising=False)
    body = (await client.get("/health")).json()
    assert body["oauth_keys_persistent"] is False
