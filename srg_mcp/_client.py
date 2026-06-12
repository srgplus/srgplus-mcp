"""Lazy SRGClient lookup used by every tool module.

Two execution modes:

1. **Local stdio** — single-tenant. ``SRG_API_KEYS`` from the env (or
   ``.env``) is the only key. Falls through to a single cached
   ``SRGClient()`` which the SDK bootstraps from the env var.

2. **Hosted server (multi-tenant)** — every incoming HTTP request first
   binds its api_key into ``_current_key_var`` (see ``serve/main.py``).
   Tools then call ``get_client()`` and receive a per-key ``SRGClient``.

The per-key cache is bounded (size + idle TTL): every unique key-set owns an
``httpx`` connection pool, so an unbounded dict slowly leaks memory on a
long-running multi-tenant server. Entries idle longer than the TTL (and the
least-recently-used ones past the size cap) are evicted and their clients
closed.
"""

from __future__ import annotations

import contextvars
import logging
import os
import threading
import time

import srg
from dotenv import load_dotenv

logger = logging.getLogger("srgplus-mcp")

# Per-request api_key. ``serve/main.py`` sets this before dispatching the
# request into the MCP framework; tools read it via ``get_client()``.
_current_key_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "srg_mcp_current_api_key", default=None
)

# Tunables (env-overridable so ops can adjust without a release). TTL counts
# IDLE time — every ``get_client()`` hit refreshes the entry, so a client in
# active use is never evicted mid-conversation.
_CACHE_MAX = int(os.environ.get("SRG_CLIENT_CACHE_MAX", "128"))
_CACHE_TTL_SECONDS = float(os.environ.get("SRG_CLIENT_CACHE_TTL", str(24 * 3600)))
_HTTP_TIMEOUT_SECONDS = float(os.environ.get("SRG_HTTP_TIMEOUT", "60"))

_clients: dict[str, srg.SRGClient] = {}
_last_used: dict[str, float] = {}
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


def _close_quietly(client: srg.SRGClient) -> None:
    try:
        client.close()
    except Exception:  # pragma: no cover - close failures are non-fatal
        logger.debug("error closing evicted SRGClient", exc_info=True)


def _evict_locked(now: float, protect: str | None = None) -> None:
    """Drop idle-expired entries, then enforce the size cap (LRU).

    ``protect`` (the key just acquired) is never evicted — it may share a
    timestamp with another entry and must win the tie. Caller must hold
    ``_clients_lock``.
    """
    expired = [
        k
        for k, ts in _last_used.items()
        if now - ts > _CACHE_TTL_SECONDS and k != protect
    ]
    for key in expired:
        _close_quietly(_clients.pop(key))
        del _last_used[key]
        logger.info("evicted idle SRGClient (cache size now %d)", len(_clients))
    while len(_clients) > _CACHE_MAX:
        candidates = [k for k in _last_used if k != protect]
        if not candidates:
            break
        oldest = min(candidates, key=_last_used.__getitem__)
        _close_quietly(_clients.pop(oldest))
        del _last_used[oldest]
        logger.info("evicted LRU SRGClient (cache size now %d)", len(_clients))


def get_client() -> srg.SRGClient:
    """Return the ``SRGClient`` bound to this request's api_key.

    Hosted-server path: ``_current_key_var`` is set; we look up (or build)
    the per-key client. Stdio path: contextvar is unset; we use the SDK's
    env-driven default (``SRG_API_KEYS`` env var).
    """
    key = _current_key_var.get()
    cache_key = key or "__env_default__"
    now = time.monotonic()
    with _clients_lock:
        client = _clients.get(cache_key)
        if client is None:
            if key is None:
                _ensure_dotenv_once()
                # picks up SRG_API_KEYS from the env
                client = srg.SRGClient(timeout=_HTTP_TIMEOUT_SECONDS)
            else:
                keys_list = [k.strip() for k in key.split(",") if k.strip()]
                client = srg.SRGClient(
                    api_keys=keys_list, timeout=_HTTP_TIMEOUT_SECONDS
                )
            _clients[cache_key] = client
        _last_used[cache_key] = now
        _evict_locked(now, protect=cache_key)
        return client
