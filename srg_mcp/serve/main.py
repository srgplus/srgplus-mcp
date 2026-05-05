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
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

# Multi-tenant client strategy: each request carries its own api_key(s) —
# either a raw key in X-API-Key / Bearer, or a comma-separated string
# extracted from an OAuth JWT. ``srg_mcp._client.get_client()`` returns a
# per-key-set ``SRGClient`` (cached by the comma-joined string). Every tool
# call passes ``workspace_id`` explicitly, so a single client can serve
# multiple workspaces without any shared state issues.
import srg_mcp._client as _srg_mcp_client  # noqa: E402

# Strip any ambient SRG_API_KEY from the env so the per-request lookup never
# falls back to it. The hosted server is multi-tenant — it must never have
# a default key, every request brings its own.
os.environ.pop("SRG_API_KEY", None)

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


async def _send_json(
    send, status: int, body: dict, *, extra_headers: list | None = None
) -> None:
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

        # Lightweight observability: how the key was acquired + non-leaking
        # prefix. Useful when triaging "tool returns 401" reports.
        auth_path = (
            "x-api-key"
            if x_api_key
            else "bearer-raw"
            if (bearer and bearer.startswith("srgplus_"))
            else "bearer-jwt"
        )
        prefix = api_key[:12] + "..." if len(api_key) > 12 else api_key
        logger.debug(
            "mcp.auth path=%s api_key_prefix=%s api_key_len=%d",
            auth_path,
            prefix,
            len(api_key),
        )

        token = _srg_mcp_client.set_current_api_key(api_key)
        try:
            await _session_manager.handle_request(scope, receive, send)
        finally:
            _srg_mcp_client.reset_current_api_key(token)


mcp_endpoint = _MCPEndpoint()


# ----------------------------------------------------------------- Static assets
#
# We ship a small set of branding assets (logo PNGs + favicon) so claude.ai's
# Custom Connector card and any browser tab that loads /oauth/authorize show
# the SRG+ mark instead of a default globe. Files live in ``serve/static/``
# and are bundled into the wheel via ``[tool.hatch.build.targets.wheel.force-include]``.
#
# A whitelist (rather than ``StaticFiles``) is used here because:
# - Only a handful of files exist; enumerating them is trivial.
# - It eliminates path traversal as a concern — a request for an unknown
#   filename returns 404 without ever touching the filesystem.
# - Each file gets an explicit content-type without relying on extension
#   sniffing.
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_FILES: dict[str, str] = {
    "icon.png": "image/png",
    "icon-32.png": "image/png",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
    "favicon.ico": "image/vnd.microsoft.icon",
}
# Browsers and CDNs cache aggressively for branding assets — 24h is fine; if
# we re-skin we'll bump the URL or the version.
_STATIC_CACHE_CONTROL = "public, max-age=86400"


def _static_response(filename: str) -> Response:
    """Serve a whitelisted static asset, or 404."""
    media_type = _STATIC_FILES.get(filename)
    if media_type is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    path = _STATIC_DIR / filename
    if not path.is_file():
        # Should never happen in a properly built wheel, but fail safe rather
        # than 500ing if someone deleted the file from the install.
        return JSONResponse({"error": "not_found"}, status_code=404)
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": _STATIC_CACHE_CONTROL,
            # CORSMiddleware already adds Access-Control-Allow-Origin: * to
            # responses for cross-origin GETs, but FileResponse goes through
            # the same middleware chain so claude.ai can <img src=...> us
            # without preflight.
        },
    )


async def favicon(request: Request) -> Response:
    return _static_response("favicon.ico")


async def static_asset(request: Request) -> Response:
    return _static_response(request.path_params["filename"])


# Root-level icon aliases.
#
# Connector UIs (claude.ai's "Custom connector" detail panel, OpenAI Apps SDK,
# ChatGPT Connectors, the MCP Registry preview, awesome-mcp directory crawlers,
# etc.) probe a handful of conventional paths to find a logo before falling
# back to a generic placeholder. Browsers do the same for tab/share icons.
#
# We alias them to the matching ``serve/static/`` asset so every probe hits
# the SRG+ mark instead of 404. Sizes:
#   /apple-touch-icon.png             → 192x192 (iOS-friendly; iOS scales down)
#   /apple-touch-icon-precomposed.png → 192x192 (legacy iOS, same file)
#   /apple-icon.png                   → 192x192 (Android variant)
#   /logo.png                         → 512x512 (PWA / connector cards)
#   /icon.png                         → 1024x1024 (high-res default)
_ROOT_ICON_ALIASES: dict[str, str] = {
    "/apple-touch-icon.png": "icon-192.png",
    "/apple-touch-icon-precomposed.png": "icon-192.png",
    "/apple-icon.png": "icon-192.png",
    "/logo.png": "icon-512.png",
    "/icon.png": "icon.png",
}


def _make_root_icon_handler(filename: str):
    async def handler(request: Request) -> Response:
        return _static_response(filename)

    handler.__name__ = f"icon_alias_{filename.replace('.', '_').replace('-', '_')}"
    return handler


# Minimal HTML index served at /. Some connector caches and link-preview crawlers
# parse <link rel="icon"> / <meta property="og:image"> off the root page rather
# than probing well-known paths, so we expose both. Keep this page small — it's
# only there for branding metadata, not for human users (humans go to srgplus.com).
_ROOT_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SRG+ MCP</title>
  <meta name="description" content="MCP server for SRG+ — manage hubs, channels, content, assets, users, and workspaces from any MCP-aware AI agent.">
  <link rel="icon" type="image/png" sizes="32x32" href="/static/icon-32.png">
  <link rel="icon" type="image/png" sizes="192x192" href="/static/icon-192.png">
  <link rel="icon" type="image/png" sizes="512x512" href="/static/icon-512.png">
  <link rel="apple-touch-icon" sizes="192x192" href="/apple-touch-icon.png">
  <link rel="shortcut icon" href="/favicon.ico">
  <link rel="manifest" href="/manifest.webmanifest">
  <meta name="theme-color" content="#000000">
  <meta property="og:title" content="SRG+ MCP">
  <meta property="og:description" content="MCP server for SRG+ — manage hubs, channels, content, assets, users, and workspaces from any MCP-aware AI agent.">
  <meta property="og:image" content="https://mcp.srgplus.com/static/icon-512.png">
  <meta property="og:url" content="https://mcp.srgplus.com/">
  <meta property="og:type" content="website">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:image" content="https://mcp.srgplus.com/static/icon-512.png">
</head>
<body style="font-family:system-ui,-apple-system,sans-serif;max-width:640px;margin:48px auto;padding:0 16px;color:#222;">
  <h1>SRG+ MCP</h1>
  <p>Hosted MCP endpoint for the <a href="https://srgplus.com">SRG+</a> platform.</p>
  <p>Connect any MCP-aware AI agent (Claude, Cursor, Cline, ChatGPT) to <code>https://mcp.srgplus.com/mcp</code>.</p>
  <p>Source &amp; docs: <a href="https://github.com/srgplus/srgplus-mcp">github.com/srgplus/srgplus-mcp</a></p>
</body>
</html>
"""


async def root_index(request: Request) -> Response:
    return Response(
        _ROOT_INDEX_HTML,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "public, max-age=300"},
    )


# Web App Manifest — the W3C-standard place for app icons. Chrome, Edge,
# Safari, claude.ai's PWA layer, and many connector-directory crawlers
# (Anthropic Console catalog, MCP Registry index, awesome-mcp scrapers)
# read this file to resolve an app's name + icon set. Serving it at the
# canonical filename and as ``/.well-known/`` covers both common probes.
_MANIFEST = {
    "name": "SRG+ MCP",
    "short_name": "SRG+",
    "description": (
        "MCP server for SRG+ — manage hubs, channels, content, assets, "
        "users, and workspaces from any MCP-aware AI agent."
    ),
    "id": "srgplus-mcp",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#000000",
    "theme_color": "#000000",
    "icons": [
        {
            "src": "/static/icon-32.png",
            "sizes": "32x32",
            "type": "image/png",
        },
        {
            "src": "/static/icon-192.png",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any maskable",
        },
        {
            "src": "/static/icon-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any maskable",
        },
        {
            "src": "/static/icon.png",
            "sizes": "1024x1024",
            "type": "image/png",
            "purpose": "any",
        },
    ],
}


async def manifest(request: Request) -> Response:
    return JSONResponse(
        _MANIFEST,
        headers={
            "Content-Type": "application/manifest+json",
            "Cache-Control": "public, max-age=3600",
        },
    )


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
        Route("/", endpoint=root_index, methods=["GET"]),
        Route("/health", endpoint=health, methods=["GET"]),
        Route(
            "/mcp",
            endpoint=mcp_endpoint,
            methods=["GET", "POST", "DELETE"],
        ),
        Route(
            "/connect",
            endpoint=mcp_endpoint,
            methods=["GET", "POST", "DELETE"],
        ),
        Route("/favicon.ico", endpoint=favicon, methods=["GET"]),
        Route("/static/{filename}", endpoint=static_asset, methods=["GET"]),
        Route("/manifest.webmanifest", endpoint=manifest, methods=["GET"]),
        # Some directories probe under .well-known/; serve the same manifest
        # there so we hit both common conventions.
        Route("/.well-known/manifest.json", endpoint=manifest, methods=["GET"]),
        *(
            Route(path, endpoint=_make_root_icon_handler(filename), methods=["GET"])
            for path, filename in _ROOT_ICON_ALIASES.items()
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
    logging.getLogger("mcp.server.streamable_http").setLevel(logging.WARNING)
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
    logger.info("srgplus-mcp-serve listening on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
