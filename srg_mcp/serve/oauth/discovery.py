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
            "token_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256"],
            "client_id_metadata_document_supported": False,
        }
    )


async def openid_configuration_metadata(request: Request) -> JSONResponse:
    """OIDC Discovery 1.0 — served at ``/.well-known/openid-configuration``.

    OpenAI's Apps SDK MCP wizard runs strict OIDC parsing on this response.
    OIDC Discovery 1.0 §3 requires (in addition to OAuth fields):

    * ``jwks_uri`` (REQUIRED — pyoidc-style validators reject otherwise)
    * ``subject_types_supported``
    * ``id_token_signing_alg_values_supported``

    Missing any of these triggers "OAuth discovery returned unsupported OAuth
    config type" in the wizard. We don't issue id_tokens (OAuth 2.1 only),
    but we serve an empty JWKS at ``/.well-known/jwks.json`` so strict
    validators get a parseable response.
    """
    issuer = _issuer()
    return JSONResponse(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "revocation_endpoint": f"{issuer}/oauth/revoke",
            "jwks_uri": f"{issuer}/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["mcp:full"],
            "authorization_response_iss_parameter_supported": True,
            # OIDC Discovery 1.0 required fields. We claim subject_types and
            # an id_token signing alg even though we don't issue id_tokens —
            # validators only check presence on this endpoint.
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "op_logo_uri": _logo_uri(),
            "logo_uri": _logo_uri(),
            "service_documentation": _DOCUMENTATION_URL,
        }
    )


async def jwks_metadata(request: Request) -> JSONResponse:
    """Empty JWKS — we don't sign id_tokens, so no keys to publish.

    Required to be reachable so OIDC validators that resolve ``jwks_uri``
    don't fail with a network error during OAuth-config-type detection.
    """
    return JSONResponse({"keys": []})


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
