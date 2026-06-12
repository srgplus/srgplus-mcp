"""OAuth discovery endpoints — RFC 8414 + RFC 9728.

Both endpoints are unauthenticated (per spec) and return JSON metadata.
``issuer`` is derived from the ``OAUTH_ISSUER`` env var (default
``https://mcp.srgplus.com``) so we can run on localhost in dev/tests without
hardcoding the prod URL.
"""

from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import JSONResponse


def _issuer() -> str:
    """The canonical OAuth issuer URL — used to mint absolute endpoint URLs.

    Defaults to the prod hostname; tests override via env var or by using a
    fully-qualified host header.
    """
    return os.environ.get("OAUTH_ISSUER", "https://mcp.srgplus.com").rstrip("/")


def _resource_uri() -> str:
    """The MCP endpoint URI advertised in protected-resource metadata."""
    return os.environ.get("OAUTH_RESOURCE", _issuer() + "/mcp")


# Branding assets advertised in discovery so MCP clients (claude.ai web,
# Cursor, etc.) can render the SRG+ mark next to the connector instead of a
# default globe. The 512px PNG is the highest-quality variant we ship — it
# scales down crisply for cards/avatars and stays tiny on the wire (~125 KB).
_LOGO_FILENAME = "icon-512.png"
_DOCUMENTATION_URL = "https://github.com/srgplus/srgplus-mcp"


def _logo_uri() -> str:
    return f"{_issuer()}/static/{_LOGO_FILENAME}"


async def authorization_server_metadata(request: Request) -> JSONResponse:
    """RFC 8414 — Authorization Server Metadata.

    Public clients only (no token_endpoint_auth_method beyond ``none``); PKCE
    S256 mandatory; both ``authorization_code`` and ``refresh_token`` grants
    are supported.
    """
    issuer = _issuer()
    return JSONResponse(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "revocation_endpoint": f"{issuer}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["mcp:full"],
            # RFC 9207 — we include ``iss`` in every authorization response
            # so clients can detect AS mix-up attacks.
            "authorization_response_iss_parameter_supported": True,
            # Branding. RFC 8414 doesn't define a logo field, so we advertise
            # the icon under both common conventions:
            # - ``op_logo_uri`` — the ``op_*`` extension namespace from the
            #   OpenID Connect Discovery family (read by some MCP clients).
            # - ``logo_uri`` — the field name from RFC 7591 client metadata,
            #   which Anthropic Console and other connector catalogs reuse
            #   when scraping AS metadata for an icon.
            "op_logo_uri": _logo_uri(),
            "logo_uri": _logo_uri(),
            "service_documentation": _DOCUMENTATION_URL,
        }
    )


async def protected_resource_metadata(request: Request) -> JSONResponse:
    """RFC 9728 — Protected Resource Metadata.

    Tells clients which AS issues tokens for this MCP endpoint. Claude.ai's
    web wizard fetches this first to bootstrap the OAuth dance.

    RFC 9728 §3.3: the advertised ``resource`` must match the endpoint the
    client connects to. The core profile gets its own identity at
    ``/mcp/core``; every other suffix keeps the legacy default — the exact
    claude.ai-verified shape for ``/mcp`` (see the PR #29/#30 reverts before
    changing anything here).
    """
    issuer = _issuer()
    suffix = (request.path_params.get("path") or "").strip("/")
    resource = issuer + "/mcp/core" if suffix == "mcp/core" else _resource_uri()
    return JSONResponse(
        {
            "resource": resource,
            "authorization_servers": [issuer],
            "scopes_supported": ["mcp:full"],
            "bearer_methods_supported": ["header"],
            "resource_documentation": _DOCUMENTATION_URL,
            # Branding — same logo URI advertised on the AS metadata so a
            # client that only fetches the protected-resource doc still has
            # the icon URL. Both conventions exposed (see AS metadata above).
            "op_logo_uri": _logo_uri(),
            "logo_uri": _logo_uri(),
        }
    )
