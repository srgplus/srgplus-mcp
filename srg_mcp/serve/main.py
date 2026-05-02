"""Hosted SRG+ MCP server.

Single Streamable HTTP endpoint (/mcp) that authenticates each request via
the X-API-Key header (or Authorization: Bearer), binds the workspace api_key
into a contextvar for the duration of the request, and lets the upstream
srg_mcp tools resolve their SRGClient from that contextvar.

Run locally:

    pip install 'srgplus-mcp[server]'
    srgplus-mcp-serve

or:

    python -m srg_mcp.serve.main

Connect from Claude Desktop / Claude Code:

    {
      "mcpServers": {
        "srgplus": {
          "url": "http://localhost:8090/mcp",
          "headers": { "X-API-Key": "srgplus_..." }
        }
      }
    }
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
from importlib.metadata import PackageNotFoundError, version as _pkg_version

import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# Patch the upstream srgplus-mcp client BEFORE importing tool modules so they
# pick up the contextual get_client at import time.
from srg_mcp.serve import _patch

_patch.install()

# Now safe to import the tool modules — their @mcp.tool() decorators register
# on the shared FastMCP instance.
from srg_mcp._app import mcp  # noqa: E402
import srg_mcp.assets  # noqa: F401, E402
import srg_mcp.channels  # noqa: F401, E402
import srg_mcp.contents  # noqa: F401, E402
import srg_mcp.hub_profiles  # noqa: F401, E402
import srg_mcp.permission_groups  # noqa: F401, E402
import srg_mcp.users  # noqa: F401, E402
import srg_mcp.workspaces  # noqa: F401, E402


logger = logging.getLogger("srgplus-mcp-serve")


# Streamable HTTP session manager wrapping the FastMCP underlying server.
# stateless=True + json_response=True keeps each request self-contained — no
# server-side session state, which fits a multi-tenant Cloud Run deploy.
_session_manager = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    stateless=True,
    json_response=True,
)


try:
    _SERVER_VERSION = _pkg_version("srgplus-mcp")
except PackageNotFoundError:
    _SERVER_VERSION = "0.0.0+unknown"


async def health(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "srg-mcp-server",
            "version": _SERVER_VERSION,
            "transport": "streamable-http",
            "tool_count": len(await mcp.list_tools()),
        }
    )


def _bearer_token(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    parts = auth_header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


async def _send_json(send, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class _MCPEndpoint:
    """ASGI app that authenticates the request and runs the MCP session.

    Auth is intentionally lazy: we don't pre-validate the api_key against the
    SRG+ API — we just bind whatever the client sent and let the SDK return a
    401 on the first tool call if the key is bad. That keeps this layer thin
    and avoids an extra round-trip per request.

    Starlette's `Route` treats a callable instance with a 3-arg ASGI signature
    as a raw ASGI app, which is what we need to forward (scope, receive, send)
    straight into the MCP StreamableHTTPSessionManager.
    """

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return

        headers = {
            k.decode().lower(): v.decode() for k, v in scope.get("headers") or []
        }
        # Strip both header values consistently — Bearer-stripping happens in
        # _bearer_token, so do the same for raw X-API-Key here.
        x_api_key = (headers.get("x-api-key") or "").strip()
        api_key = x_api_key or _bearer_token(headers.get("authorization"))

        if not api_key:
            await _send_json(
                send,
                401,
                {
                    "error": "missing_api_key",
                    "message": (
                        "Provide your SRG+ workspace API key via "
                        "'X-API-Key' header or 'Authorization: Bearer <key>'."
                    ),
                },
            )
            return

        token = _patch.set_current_key(api_key)
        try:
            await _session_manager.handle_request(scope, receive, send)
        finally:
            _patch.reset_current_key(token)


mcp_endpoint = _MCPEndpoint()


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with _session_manager.run():
        yield


app = Starlette(
    routes=[
        Route("/health", endpoint=health, methods=["GET"]),
        Route(
            "/mcp",
            endpoint=mcp_endpoint,
            methods=["GET", "POST", "DELETE"],
        ),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["mcp-session-id"],
        ),
    ],
    lifespan=lifespan,
)


def run() -> None:
    port = int(os.environ.get("PORT", "8090"))
    host = os.environ.get("HOST", "0.0.0.0")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("srgplus-mcp-serve listening on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
