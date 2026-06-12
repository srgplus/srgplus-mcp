"""Uniform error handling for tool calls on the hosted server.

Without this, an SDK/httpx exception inside any of the ~98 tools reaches the
MCP client as an opaque exception string and leaves no server-side trace of
which tool failed, with what status, for which key. ``install_tool_error_wrapper``
wraps every registered tool function so that failures:

* log ONE structured WARNING line: tool name, exception class, HTTP status,
  message — enough to triage "the connector is broken" reports from Cloud
  Logging alone;
* reach the client as one concise, actionable line, e.g.
  ``SRG+ API error (401) in list_workspaces: HTTP 401 — The API key is
  invalid or revoked...`` instead of a bare ``HTTP 401``.

Non-SRG errors (programming bugs, validation) are logged and re-raised
untouched so FastMCP's normal conversion applies.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, NoReturn

import httpx

import srg.exceptions

logger = logging.getLogger("srgplus-mcp-serve.tools")

# Per-status guidance appended to the client-facing message. Wording matters:
# these are read by an LLM agent that should self-correct (skip blocked
# categories, re-check ids) instead of aborting the whole task.
_STATUS_HINTS = {
    401: (
        "The API key is invalid or revoked. Create a new key in SRG+ "
        "Settings → API Keys and reconnect."
    ),
    403: (
        "The key's user lacks access to this resource. Per-category/channel "
        "ACLs make this normal for a subset of items — skip it and continue."
    ),
    404: "Resource not found — re-check the id (it may have been deleted).",
    429: "Rate limited — wait a moment and retry.",
}


def _format_client_message(tool_name: str, exc: Exception) -> tuple[str, Any] | None:
    """Return (message, status) for SRG+/network errors, None for the rest."""
    if isinstance(exc, srg.exceptions.APIStatusError):
        status = exc.status_code
        hint = _STATUS_HINTS.get(status, "")
        message = f"SRG+ API error ({status}) in {tool_name}: {exc.message}"
        return (f"{message}. {hint}".strip() if hint else message), status
    if isinstance(exc, httpx.TimeoutException):
        return (
            f"SRG+ API timeout in {tool_name} — the backend took too long. "
            "Retry once; if it persists, narrow the request (smaller page, "
            "single workspace).",
            "timeout",
        )
    if isinstance(exc, (srg.exceptions.SRGError, httpx.HTTPError)):
        return f"SRG+ API error in {tool_name}: {exc}", None
    return None


def _handle_tool_exception(tool_name: str, exc: Exception) -> NoReturn:
    formatted = _format_client_message(tool_name, exc)
    if formatted is None:
        # Not an SRG+/network failure — a bug or bad input. Log it (FastMCP
        # swallows the traceback otherwise) and let the framework convert it.
        logger.warning(
            "tool=%s failed: %s: %s", tool_name, type(exc).__name__, exc
        )
        raise exc
    message, status = formatted
    logger.warning(
        "tool=%s status=%s error=%s: %s",
        tool_name,
        status,
        type(exc).__name__,
        exc,
    )
    raise RuntimeError(message) from exc


def install_tool_error_wrapper(mcp: Any) -> int:
    """Wrap every tool registered on ``mcp``; return how many were wrapped.

    Reaches into FastMCP internals (``_tool_manager._tools``, ``Tool.fn``) —
    the ``mcp`` dependency is upper-bounded ``<2.0`` in pyproject precisely
    because we depend on private attributes. Fails open: if the internals
    moved, log loudly and serve unwrapped rather than crash at startup.
    """
    try:
        tools = mcp._tool_manager._tools
    except AttributeError:  # pragma: no cover - guards against mcp upgrades
        logger.error(
            "FastMCP internals changed — tool error wrapper NOT installed; "
            "tool failures will surface raw"
        )
        return 0

    wrapped = 0
    for name, tool in tools.items():
        fn = getattr(tool, "fn", None)
        if fn is None or getattr(fn, "_srg_error_wrapped", False):
            continue

        if getattr(tool, "is_async", False):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, _fn=fn, _name=name, **kwargs: Any):
                try:
                    return await _fn(*args, **kwargs)
                except Exception as exc:
                    _handle_tool_exception(_name, exc)

            new_fn: Any = async_wrapper
        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, _fn=fn, _name=name, **kwargs: Any):
                try:
                    return _fn(*args, **kwargs)
                except Exception as exc:
                    _handle_tool_exception(_name, exc)

            new_fn = sync_wrapper

        new_fn._srg_error_wrapped = True
        try:
            tool.fn = new_fn
        except Exception:  # pydantic frozen-model fallback
            object.__setattr__(tool, "fn", new_fn)
        wrapped += 1

    logger.info("tool error wrapper installed on %d tools", wrapped)
    return wrapped
