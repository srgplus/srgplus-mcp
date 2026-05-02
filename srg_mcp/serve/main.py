"""Hosted SRG+ MCP server.

Single Streamable HTTP endpoint (/mcp) that authenticates each request via
the X-API-Key header (or Authorization: Bearer), binds the workspace api_key
into the SDK's per-request contextvar via ``SRGClient.use_api_key`` for the
duration of the request, and lets the upstream srg_mcp tools share a single
``SRGClient`` (and therefore a single ``httpx`` connection pool).

Three accepted credential formats:

* ``X-API-Key: srgplus_...`` — original header, still works
* ``Authorization: Bearer srgplus_...`` — original header, still works
* ``Authorization: Bearer <jwt>``  — OAuth 2.1 access token (new in 0.4.0)

The OAuth layer is implemented in :mod:`srg_mcp.serve.oauth`. It exposes a
DCR endpoint, authorize page, token endpoint, and revocation — together
enough for claude.ai web's Custom Connector wizard to onboard a user.

Run locally:

    pip install 'srgplus-mcp[server]'
    srgplus-mcp-serve

or:

    python -m srg_mcp.serve.main

Connect from Claude Desktop / Claude Code (header auth):

    {
      "mcpServers": {
        "srgplus": {
          "url": "http://localhost:8090/mcp",
          "headers": { "X-API-Key": "srgplus_..." }
        }
      }
    }

Connect from claude.ai web (OAuth auto-discovery):

    Settings → Connectors → Add custom connector → URL: https://mcp.srgplus.com/mcp
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
from importlib.metadata import PackageNotFoundError, version as _pkg_version

import srg
import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# Build a single base SRGClient with no default api_key — its httpx.Client is
# the shared connection pool used across all incoming requests. Each request
# binds its own api_key via ``base_client.use_api_key(...)`` (a contextvar
# scope inside the SDK), so the same ``hub_profiles.list()`` call resolves
# different workspaces depending on which request context it runs in.
#
# We seed ``srg_mcp._client._client`` directly so the lazy ``get_client()``
# helper used by every tool module returns this shared instance — no
# monkey-patching required. We do this BEFORE importing the tool modules so
# they pick up the seeded singleton on first call.
import srg_mcp._client as _srg_mcp_client  # noqa: E402

# Strip any ambient SRG_API_KEY from the env so the base client doesn't pick
# it up as a default (the SDK falls back to that env var when api_key is None).
# The hosted server is multi-tenant — it must never have a default key, every
# request brings its own.
os.environ.pop("SRG_API_KEY", None)

_base_client = srg.SRGClient()  # no api_key — keys come per-request
_srg_mcp_client._client = _base_client

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

from srg_mcp.serve import oauth  # noqa: E402


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


def _issuer() -> str:
    return os.environ.get("OAUTH_ISSUER", "https://mcp.srgplus.com").rstrip("/")


async def health(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "srg-mcp-server",
            "version": _SERVER_VERSION,
            "transport": "streamable-http",
            "tool_count": len(await mcp.list_tools()),
            "oauth": True,
        }
    )


def _bearer_token(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    parts = auth_header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _www_authenticate_header() -> tuple[bytes, bytes]:
    """The WWW-Authenticate header pointing clients at our AS metadata.

    Per the MCP Authorization spec (2025-06-18), 401 responses on the MCP
    endpoint should advertise the AS so well-behaved clients can discover
    where to authenticate.
    """
    iss = _issuer()
    value = (
        f'Bearer realm="{iss}/mcp", '
        f'as_uri="{iss}/.well-known/oauth-authorization-server"'
    )
    return (b"www-authenticate", value.encode())


async def _send_json(send, status: int, body: dict, *, extra_headers: list | None = None) -> None:
    payload = json.dumps(body).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode()),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})


class _MCPEndpoint:
    """ASGI app that authenticates the request and runs the MCP session.

    Auth precedence (first match wins):

    1. ``X-API-Key`` header — raw SRG+ workspace api_key (legacy/header path)
    2. ``Authorization: Bearer srgplus_...`` — raw SRG+ workspace api_key
    3. ``Authorization: Bearer <jwt>`` — OAuth 2.1 access token issued by us

    For (1) and (2) we don't pre-validate against SRG+ — the SDK's first call
    raises 401 if the key is bad. For (3) we verify the JWT (signature, exp,
    aud, iss, jti deny-list) and decrypt the wrapped api_key.

    On 401 we include a ``WWW-Authenticate`` header pointing at our AS
    metadata so MCP clients that follow the discovery spec can find us.
    """

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return

        headers = {
            k.decode().lower(): v.decode() for k, v in scope.get("headers") or []
        }
        x_api_key = (headers.get("x-api-key") or "").strip()
        bearer = _bearer_token(headers.get("authorization"))

        api_key: str | None = None
        if x_api_key:
            api_key = x_api_key
        elif bearer:
            # Distinguish raw api_key (legacy) from OAuth JWT. SRG+ workspace
            # keys are prefixed ``srgplus_`` — JWTs have three dot-separated
            # base64url segments. Prefix check first (cheap), JWT verify
            # second (only when prefix doesn't match).
            if bearer.startswith("srgplus_"):
                api_key = bearer
            else:
                try:
                    api_key = oauth.verify_access_token(bearer)
                except oauth.OAuthError:
                    api_key = None

        if not api_key:
            await _send_json(
                send,
                401,
                {
                    "error": "missing_api_key",
                    "message": (
                        "Provide your SRG+ workspace API key via "
                        "'X-API-Key' header, 'Authorization: Bearer srgplus_...', "
                        "or an OAuth Bearer access token from /oauth/token."
                    ),
                },
                extra_headers=[_www_authenticate_header()],
            )
            return

        with _base_client.use_api_key(api_key):
            await _session_manager.handle_request(scope, receive, send)


mcp_endpoint = _MCPEndpoint()


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with _session_manager.run():
        yield


# CORS strategy:
# - /mcp accepts cross-origin POST WITHOUT cookies — wildcard origin is safe
#   here and necessary for arbitrary MCP clients in arbitrary browsers.
# - OAuth endpoints are browser-driven via claude.ai's wizard. We allow the
#   anthropic origins explicitly (wildcard + credentials would be rejected by
#   browsers even though we don't set cookies — being explicit is cleaner).
#
# We use a single CORS middleware with a wildcard since none of our endpoints
# set credentials. The OAuth endpoints render HTML/redirect/JSON — claude.ai's
# wizard runs in the browser and follows redirects, no preflight needed for
# top-level navigations. The CORS preflight only matters for the JSON
# endpoints (/oauth/register, /oauth/token, /oauth/revoke) — and for those,
# claude.ai sends Origin: https://claude.ai which * accepts.
_CORS_ALLOW_ORIGINS = ["*"]
_CORS_ALLOW_HEADERS = ["content-type", "authorization", "x-api-key", "mcp-session-id"]
_CORS_EXPOSE_HEADERS = ["mcp-session-id", "www-authenticate"]


app = Starlette(
    routes=[
        Route("/health", endpoint=health, methods=["GET"]),
        Route(
            "/mcp",
            endpoint=mcp_endpoint,
            methods=["GET", "POST", "DELETE"],
        ),
        *oauth.get_routes(),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=_CORS_ALLOW_ORIGINS,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=_CORS_ALLOW_HEADERS,
            expose_headers=_CORS_EXPOSE_HEADERS,
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
