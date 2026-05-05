"""Dynamic Client Registration — RFC 7591.

We don't keep a clients table. The ``client_id`` we hand back is itself a
signed JWT carrying the registered metadata (``redirect_uris``,
``client_name``, ``created_at``). At /authorize and /token we decode the JWT
to recover the registration. Tampering invalidates the signature.

This makes the auth server *stateless* across instances — any Cloud Run
replica can serve any client_id without a shared DB. The trade-off: we can't
revoke a single client by deleting it from a table. If we ever need
revocation, we add a deny-list keyed on the client_id JWT's ``jti``.
"""

from __future__ import annotations

import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .errors import InvalidRequest, OAuthError
from .jwt_codec import client_registration_key, encode_hs256, random_token


# What we accept in the registration request body. We're permissive on extra
# fields (some clients send arbitrary metadata) but strict on the parts that
# matter for security.
_DEFAULT_GRANT_TYPES = ["authorization_code", "refresh_token"]
_DEFAULT_RESPONSE_TYPES = ["code"]
_DEFAULT_TOKEN_AUTH = "none"


def _parse_redirect_uris(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise InvalidRequest("redirect_uris must be a non-empty array of strings.")
    out: list[str] = []
    for uri in value:
        if not isinstance(uri, str) or not uri.strip():
            raise InvalidRequest("redirect_uris must contain non-empty string values.")
        # We require an absolute URL with a scheme. We do NOT lock the scheme
        # to https — claude.ai uses https, but local dev clients (Cursor,
        # MCP Inspector) sometimes use http://localhost. The actual security
        # check is exact-match at /authorize, not scheme filtering here.
        if "://" not in uri:
            raise InvalidRequest("redirect_uris must be absolute URIs.")
        out.append(uri)
    return out


async def register(request: Request) -> JSONResponse:
    """POST /oauth/register — open DCR, no pre-approval."""
    try:
        try:
            body = await request.json()
        except Exception as exc:  # malformed JSON
            raise InvalidRequest("Request body must be valid JSON.") from exc

        if not isinstance(body, dict):
            raise InvalidRequest("Request body must be a JSON object.")

        redirect_uris = _parse_redirect_uris(body.get("redirect_uris"))

        client_name = body.get("client_name") or "Unnamed Client"
        if not isinstance(client_name, str):
            raise InvalidRequest("client_name must be a string.")
        # Cap to a reasonable length so a malicious client can't bloat the
        # client_id JWT (which we re-emit in every authorize redirect).
        client_name = client_name[:200]

        # We accept the client's preferences but enforce our supported set.
        # Per spec we MAY narrow what they ask for; per practice claude.ai
        # sends the same defaults we do anyway.
        grant_types = body.get("grant_types") or _DEFAULT_GRANT_TYPES
        response_types = body.get("response_types") or _DEFAULT_RESPONSE_TYPES
        token_endpoint_auth_method = (
            body.get("token_endpoint_auth_method") or _DEFAULT_TOKEN_AUTH
        )

        if token_endpoint_auth_method != "none":
            # We're a public-clients-only AS for now. Reject anything else
            # explicitly so the client doesn't try and fail at /token.
            raise InvalidRequest(
                "Only 'none' token_endpoint_auth_method is supported (PKCE public clients)."
            )

        now = int(time.time())
        # The client_id JWT — short and deterministic. We embed the random
        # ``jti`` so two registrations with identical metadata still produce
        # distinct IDs (useful if we ever add a deny-list).
        client_id = encode_hs256(
            {
                "iat": now,
                "redirect_uris": redirect_uris,
                "client_name": client_name,
                "jti": random_token(16),
            },
            client_registration_key(),
        )

        return JSONResponse(
            {
                "client_id": client_id,
                "client_id_issued_at": now,
                "redirect_uris": redirect_uris,
                "grant_types": grant_types,
                "response_types": response_types,
                "token_endpoint_auth_method": token_endpoint_auth_method,
                "client_name": client_name,
            },
            status_code=201,
        )
    except OAuthError as e:
        return JSONResponse(e.to_dict(), status_code=e.status)


def decode_client_id(client_id: str) -> dict[str, Any]:
    """Decode + verify a registered client_id JWT.

    Raises ``OAuthError`` (with code ``invalid_client``) on any failure —
    callers translate that into the right HTTP response.
    """
    from .errors import InvalidClient
    from .jwt_codec import decode_hs256
    import jwt as pyjwt

    if not client_id:
        raise InvalidClient("Missing client_id.")
    try:
        payload = decode_hs256(
            client_id,
            client_registration_key(),
            require_exp=False,  # client_ids don't expire — DCR is permanent
        )
    except pyjwt.PyJWTError as e:
        # Don't leak why (expired vs malformed vs wrong-signature) — uniform
        # message, the security checklist requires this.
        raise InvalidClient("Unknown client.") from e
    redirect_uris = payload.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise InvalidClient("Unknown client.")
    return payload
