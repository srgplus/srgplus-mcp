"""Per-request API key routing via contextvar.

The upstream `srgplus-mcp` stdio entry point uses a process-singleton
SRGClient seeded from the SRG_API_KEY env var. For the multi-tenant hosted
HTTP endpoint we need a different client per workspace, picked from the
X-API-Key header on each incoming request.

This module patches `srg_mcp._client.get_client` (and the local `get_client`
references inside every tool module) to resolve the current request's api_key
from a contextvar and lazily build/cache an SRGClient for it.

This is a temporary workaround until the SDK supports per-request auth
natively — once that lands, this whole module can be deleted and the HTTP
server can drop the patch step.
"""
from __future__ import annotations

import contextvars
import importlib

import srg
import srg_mcp._client
from cachetools import LRUCache


_current_key_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "srg_current_key"
)
# Bounded LRU keeps memory growth predictable when many distinct workspace
# api_keys hit the same revision. cachetools.LRUCache is not threadsafe, but
# this server is single-process async (one Cloud Run revision per worker) and
# request isolation comes from contextvars, so no lock is needed here.
_CLIENT_CACHE_MAXSIZE = 512
_client_cache: LRUCache[str, srg.SRGClient] = LRUCache(maxsize=_CLIENT_CACHE_MAXSIZE)


def set_current_key(api_key: str) -> contextvars.Token:
    """Bind an api_key to the current request context."""
    return _current_key_var.set(api_key)


def reset_current_key(token: contextvars.Token) -> None:
    _current_key_var.reset(token)


def _contextual_get_client() -> srg.SRGClient:
    """Resolve the current request's SRGClient from the contextvar.

    Builds (and caches) a client per unique api_key on first use. Invalid keys
    surface as upstream 401s on the first SDK call — same behaviour as the
    single-key wrapper, just routed per request.
    """
    try:
        key = _current_key_var.get()
    except LookupError as exc:
        raise RuntimeError(
            "No SRG+ api_key bound to this request. "
            "Did the X-API-Key middleware run?"
        ) from exc

    client = _client_cache.get(key)
    if client is None:
        client = srg.SRGClient(api_key=key)
        _client_cache[key] = client
    return client


def install() -> None:
    """Patch upstream get_client + per-module bindings.

    Tool modules captured `get_client` at import time via `from ... import`,
    so we have to rebind it inside each module too.
    """
    srg_mcp._client.get_client = _contextual_get_client

    tool_modules = (
        "srg_mcp.hub_profiles",
        "srg_mcp.channels",
        "srg_mcp.contents",
        "srg_mcp.assets",
        "srg_mcp.users",
        "srg_mcp.workspaces",
        "srg_mcp.permission_groups",
    )
    for name in tool_modules:
        module = importlib.import_module(name)
        if hasattr(module, "get_client"):
            module.get_client = _contextual_get_client
