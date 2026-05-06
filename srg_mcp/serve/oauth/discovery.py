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

    Field set is kept tight to match the working OpenAI Apps SDK
    submissions (mcp.notion.com, mcp.linear.app). The OpenAI wizard's
    backend appears to use a strict-schema parser (extras → 500 / "unsupported
    OAuth config type"). Branding (logo) is conveyed via the protected-resource
    metadata + per-resource extras, not the AS metadata.
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
            "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            # OpenAI's wizard parser requires client_secret_basic and
            # client_secret_post to be advertised (matches Notion + Linear).
            # We're a public-client + PKCE provider — DCR enforces ``none`` —
            # but the metadata accepts the broader set. Real clients
            # (claude.ai, OpenAI Apps SDK) request ``none`` during DCR.
            "token_endpoint_auth_methods_supported": [
                "client_secret_basic",
                "client_secret_post",
                "none",
            ],
            # We advertise both methods to match Notion (in OpenAI Apps
            # Directory). Our token endpoint enforces S256 (OAuth 2.1
            # mandatory) — clients that try ``plain`` get rejected at the
            # token exchange. Real MCP clients (claude.ai, ChatGPT) all use
            # S256. The ``plain`` advertisement is metadata-shape only.
            "code_challenge_methods_supported": ["plain", "S256"],
            "client_id_metadata_document_supported": False,
        }
    )


async def protected_resource_metadata(request: Request) -> JSONResponse:
    """RFC 9728 — Protected Resource Metadata.

    Tells clients which AS issues tokens for this MCP endpoint. Claude.ai's
    web wizard fetches this first to bootstrap the OAuth dance.

    Field set kept minimal to match working OpenAI Apps SDK submissions
    (mcp.notion.com). Logo + scope detail belongs in the connector listing,
    not in metadata.
    """
    issuer = _issuer()
    return JSONResponse(
        {
            "resource": _resource_uri(),
            "authorization_servers": [issuer],
            "bearer_methods_supported": ["header"],
            "resource_name": "SRG+ MCP",
        }
    )
