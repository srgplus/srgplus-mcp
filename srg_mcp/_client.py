"""Lazy SRGClient lookup used by every tool module.

Two execution modes:

1. **Local stdio** — single-tenant. ``SRG_API_KEYS`` from the env (or
   ``.env``) is the only key. Falls through to a single cached
   ``SRGClient()`` which the SDK bootstraps from the env var.

2. **Hosted server (multi-tenant)** — every incoming HTTP request first
   binds its api_key into ``_current_key_var`` (see ``serve/main.py``).
   Tools then call ``get_client()`` and receive a per-key ``SRGClient``.
"""

from __future__ import annotations

import contextvars
import threading

import srg
from dotenv import load_dotenv

# Per-request api_key. ``serve/main.py`` sets this before dispatching the
# request into the MCP framework; tools read it via ``get_client()``.
_current_key_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "srg_mcp_current_api_key", default=None
)

_clients: dict[str, srg.SRGClient] = {}
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
    env-driven default (``SRG_API_KEYS`` env var).
    """
    key = _current_key_var.get()
    cache_key = key or "__env_default__"
    with _clients_lock:
        if cache_key not in _clients:
            if key is None:
                _ensure_dotenv_once()
                _clients[cache_key] = srg.SRGClient()  # picks up SRG_API_KEYS
            else:
                keys_list = [k.strip() for k in key.split(",") if k.strip()]
                _clients[cache_key] = srg.SRGClient(api_keys=keys_list)
        return _clients[cache_key]