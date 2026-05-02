"""Lazy SRGClient lookup used by every tool module.

Two execution modes:

1. **Local stdio** — single-tenant. ``SRG_API_KEY`` from the env (or
   ``.env``) is the only key. Falls through to a single cached
   ``SRGClient()`` which the SDK bootstraps from the env var.

2. **Hosted server (multi-tenant)** — every incoming HTTP request first
   binds its api_key into ``_current_key_var`` (see ``serve/main.py``).
   Tools then call ``get_client()`` and receive a per-key ``SRGClient``
   from the LRU cache. Each per-key client eagerly bootstraps its own
   ``workspace_id`` at construction time, which is required because the
   SDK bakes ``workspace_id`` into its ``hub_profiles`` / ``workspaces``
   resources via ``@cached_property`` — a single shared client cannot
   serve two workspaces correctly.

The LRU cap (1024 entries) keeps memory bounded under DoS-style traffic
without ever evicting the active set in normal use — Cloud Run instances
serving more than ~1024 distinct workspaces concurrently is well past the
point we'd shard / migrate to Redis-backed state anyway.
"""
from __future__ import annotations

import contextvars
import threading

import srg
from cachetools import LRUCache
from dotenv import load_dotenv

# Per-request api_key. ``serve/main.py`` sets this before dispatching the
# request into the MCP framework; tools read it via ``get_client()``.
_current_key_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "srg_mcp_current_api_key", default=None
)

_clients_by_key: LRUCache = LRUCache(maxsize=1024)
_clients_lock = threading.Lock()
_dotenv_loaded = False


def _ensure_dotenv_once() -> None:
    """Load ``.env`` once for stdio mode. Hosted server doesn't need it."""
    global _dotenv_loaded
    if not _dotenv_loaded:
        load_dotenv()
        _dotenv_loaded = True


def set_current_api_key(api_key: str | None) -> contextvars.Token:
    """Bind ``api_key`` to the current async context.

    Returns the contextvars Token; pass to :func:`reset_current_api_key`
    in the matching ``finally`` to restore the previous binding.
    """
    return _current_key_var.set(api_key)


def reset_current_api_key(token: contextvars.Token) -> None:
    _current_key_var.reset(token)


def get_client() -> srg.SRGClient:
    """Return the ``SRGClient`` bound to this request's api_key.

    Hosted-server path: ``_current_key_var`` is set; we look up (or build)
    the per-key client. Stdio path: contextvar is unset; we use the SDK's
    env-driven default.
    """
    key = _current_key_var.get()
    if key is None:
        _ensure_dotenv_once()
        with _clients_lock:
            client = _clients_by_key.get("__env_default__")
            if client is None:
                client = srg.SRGClient()  # picks up SRG_API_KEY
                _clients_by_key["__env_default__"] = client
            return client

    with _clients_lock:
        client = _clients_by_key.get(key)
        if client is None:
            # Constructor eagerly fetches /api/v1/workspaces and caches
            # workspace_id on the instance — exactly what we need for the
            # SDK's cached_property resources to point at the right tenant.
            client = srg.SRGClient(api_key=key)
            _clients_by_key[key] = client
        return client
