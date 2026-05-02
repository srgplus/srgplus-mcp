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
        }
    )


async def protected_resource_metadata(request: Request) -> JSONResponse:
    """RFC 9728 — Protected Resource Metadata.

    Tells clients which AS issues tokens for this MCP endpoint. Claude.ai's
    web wizard fetches this first to bootstrap the OAuth dance.
    """
    issuer = _issuer()
    return JSONResponse(
        {
            "resource": _resource_uri(),
            "authorization_servers": [issuer],
            "scopes_supported": ["mcp:full"],
            "bearer_methods_supported": ["header"],
            "resource_documentation": "https://github.com/srgplus/srgplus-mcp",
        }
    )
