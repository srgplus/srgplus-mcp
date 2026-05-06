"""OAuth 2.1 layer for the hosted MCP server.

Public API exposed to ``serve.main``:

* :func:`get_routes` — Starlette route list to mount on the app
* :func:`verify_access_token` — used by the /mcp endpoint to convert an
  OAuth Bearer JWT into the underlying SRG+ workspace api_key
* :class:`OAuthError` — base exception for callers to catch

Internal modules (``dcr``, ``authorize``, ``token``, ``discovery``,
``jwt_codec``, ``pkce``, ``store``, ``errors``) are not part of the public
API and may move/rename across versions.

Spec coverage:
* RFC 8414 — Authorization Server Metadata
* RFC 9728 — Protected Resource Metadata
* RFC 7591 — Dynamic Client Registration
* RFC 7636 — PKCE (S256 only)
* RFC 7009 — Token Revocation
* OAuth 2.1 (draft-ietf-oauth-v2-1) — public client / PKCE-mandatory profile
"""

from __future__ import annotations

from starlette.routing import Route

from .authorize import authorize_get, authorize_post
from .dcr import register
from .discovery import (
    authorization_server_metadata,
    protected_resource_metadata,
)
from .errors import (
    InvalidClient,
    InvalidGrant,
    InvalidRequest,
    OAuthError,
)
from .token import revoke, token, verify_access_token

__all__ = [
    "OAuthError",
    "InvalidClient",
    "InvalidGrant",
    "InvalidRequest",
    "verify_access_token",
    "get_routes",
]


def get_routes() -> list[Route]:
    """Return the Starlette routes for the OAuth layer.

    Mount these alongside the existing /mcp + /health routes in serve.main.
    """
    return [
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=authorization_server_metadata,
            methods=["GET"],
        ),
        # Path-suffix variant per RFC 8414 §3.1 — strictly only mandated when
        # the issuer URL itself has a path component (ours doesn't), but some
        # MCP clients construct it anyway by mirroring RFC 9728 §3.1. Cheap
        # defensive route; same handler.
        Route(
            "/.well-known/oauth-authorization-server/{path:path}",
            endpoint=authorization_server_metadata,
            methods=["GET"],
        ),
        # OpenAI Apps SDK MCP wizard discovery probes
        # ``/.well-known/openid-configuration`` (and a path-suffixed variant)
        # as part of its OAuth-config-type detection. Verified via Cloud Run
        # access logs 2026-05-06 — the OpenAI scanner (Python aiohttp from
        # Azure-hosted IPs) hits ``oauth-protected-resource/mcp`` →
        # ``oauth-authorization-server`` (both 200) and then
        # ``openid-configuration`` (was 404 before this route). The 404
        # caused the wizard to reject the server with "OAuth discovery
        # returned unsupported OAuth config type", blocking Save MCP details.
        # We serve our OAuth 2.1 metadata at both shapes — the OpenAI
        # discoverer accepts the same payload as a valid config.
        Route(
            "/.well-known/openid-configuration",
            endpoint=authorization_server_metadata,
            methods=["GET"],
        ),
        Route(
            "/.well-known/openid-configuration/{path:path}",
            endpoint=authorization_server_metadata,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-protected-resource",
            endpoint=protected_resource_metadata,
            methods=["GET"],
        ),
        # RFC 9728 §3.1: clients construct the discovery URL by inserting
        # ``/.well-known/oauth-protected-resource`` between the resource's
        # host and path. For ``https://mcp.srgplus.com/mcp`` that's
        # ``https://mcp.srgplus.com/.well-known/oauth-protected-resource/mcp``.
        # We serve identical metadata at both shapes — the path suffix is
        # ignored. claude.ai's MCP client tries the path-suffixed URL first;
        # without this route it 404s and the connector flow stalls.
        Route(
            "/.well-known/oauth-protected-resource/{path:path}",
            endpoint=protected_resource_metadata,
            methods=["GET"],
        ),
        Route("/oauth/register", endpoint=register, methods=["POST"]),
        Route("/oauth/authorize", endpoint=authorize_get, methods=["GET"]),
        Route("/oauth/authorize", endpoint=authorize_post, methods=["POST"]),
        Route("/oauth/token", endpoint=token, methods=["POST"]),
        Route("/oauth/revoke", endpoint=revoke, methods=["POST"]),
    ]
