"""Token endpoint + revocation.

POST /oauth/token — exchange authorization_code for access/refresh tokens, or
exchange refresh_token for a new access/refresh pair (rotation).

POST /oauth/revoke — RFC 7009. Adds the token's ``jti`` to the in-memory
deny-list. Returns 200 unconditionally per the spec.

All JWTs we issue carry standard claims:
    iss = OAUTH_ISSUER
    aud = "<issuer>/mcp"   (the protected resource)
    iat, exp, jti
    sub = stable per-api_key user identifier (sha256 of the api_key)
    scope = "mcp:full"
    token_type = "Bearer" | "refresh"
    api_key_encrypted = AES-GCM blob, decrypted only at /mcp request time

We deliberately re-encrypt the api_key on every token mint so that an attacker
who somehow leaks one nonce doesn't get to decrypt every future token.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any

import jwt as pyjwt
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .dcr import decode_client_id
from .errors import (
    InvalidGrant,
    InvalidRequest,
    OAuthError,
    UnsupportedGrantType,
)
from .jwt_codec import (
    constant_time_eq,
    decode_hs256,
    decrypt_api_key,
    encode_hs256,
    encrypt_api_key,
    random_token,
    token_signing_key,
)
from .pkce import verify as pkce_verify
from .store import is_code_used, is_token_revoked, mark_code_used, revoke_token

logger = logging.getLogger("srgplus-mcp-serve.oauth")


_ACCESS_TTL = 3600           # 1h
_REFRESH_TTL = 30 * 24 * 3600  # 30d


def _issuer() -> str:
    return os.environ.get("OAUTH_ISSUER", "https://mcp.srgplus.com").rstrip("/")


def _audience() -> str:
    return os.environ.get("OAUTH_RESOURCE", _issuer() + "/mcp")


def _subject_for(api_key: str) -> str:
    """Stable per-api_key user identifier — never the api_key itself."""
    return "u_" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:32]


def _mint_pair(api_key: str, scope: str = "mcp:full") -> dict[str, Any]:
    """Build a fresh access_token + refresh_token pair for this api_key."""
    now = int(time.time())
    sub = _subject_for(api_key)
    iss = _issuer()
    aud = _audience()

    access_payload = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "scope": scope,
        "token_type": "Bearer",
        "api_key_encrypted": encrypt_api_key(api_key),
        "iat": now,
        "exp": now + _ACCESS_TTL,
        "jti": random_token(16),
    }
    refresh_payload = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "scope": scope,
        "token_type": "refresh",
        "api_key_encrypted": encrypt_api_key(api_key),
        "iat": now,
        "exp": now + _REFRESH_TTL,
        "jti": random_token(16),
    }
    return {
        "access_token": encode_hs256(access_payload, token_signing_key()),
        "token_type": "Bearer",
        "expires_in": _ACCESS_TTL,
        "refresh_token": encode_hs256(refresh_payload, token_signing_key()),
        "scope": scope,
    }


# ---------- /oauth/token --------------------------------------------------


async def token(request: Request) -> Response:
    """Handle authorization_code and refresh_token grants."""
    try:
        form = await request.form()
        grant_type = form.get("grant_type", "")
        # Trace what the client is sending — useful when diagnosing why a
        # client (claude.ai etc.) reaches /authorize but never /token.
        # We log presence-only flags to avoid leaking the code or verifier.
        logger.info(
            "oauth.token.request grant_type=%s has_code=%s has_verifier=%s "
            "has_client_id=%s has_redirect_uri=%s has_refresh=%s",
            grant_type or "(missing)",
            bool(form.get("code")),
            bool(form.get("code_verifier")),
            bool(form.get("client_id")),
            bool(form.get("redirect_uri")),
            bool(form.get("refresh_token")),
        )

        if grant_type == "authorization_code":
            return _handle_code_grant(form)
        elif grant_type == "refresh_token":
            return _handle_refresh_grant(form)
        else:
            raise UnsupportedGrantType()
    except OAuthError as e:
        logger.info("oauth.token.error error=%s status=%d", e.code, e.status)
        return JSONResponse(e.to_dict(), status_code=e.status, headers={"Cache-Control": "no-store"})


def _handle_code_grant(form) -> Response:
    code = form.get("code", "")
    client_id = form.get("client_id", "")
    redirect_uri = form.get("redirect_uri", "")
    code_verifier = form.get("code_verifier", "")

    if not code:
        raise InvalidRequest("code is required.")
    if not client_id:
        raise InvalidRequest("client_id is required.")
    if not redirect_uri:
        raise InvalidRequest("redirect_uri is required.")
    if not code_verifier:
        raise InvalidRequest("code_verifier is required.")

    # Step 1: verify the client_id is real (decoder raises on bad signatures).
    decode_client_id(client_id)

    # Step 2: decode the code JWT.
    try:
        code_payload = decode_hs256(code, token_signing_key())
    except pyjwt.PyJWTError as e:
        raise InvalidGrant("Authorization code is invalid or expired.") from e

    # Step 3: one-time-use check. Add to deny-list before returning so a
    # double-submit can't slip past the check.
    code_id = code_payload.get("code", "")
    if not isinstance(code_id, str) or not code_id:
        raise InvalidGrant("Authorization code is invalid or expired.")
    if is_code_used(code_id):
        raise InvalidGrant("Authorization code has already been used.")
    mark_code_used(code_id)

    # Step 4: client_id must match (timing-safe).
    if not constant_time_eq(code_payload.get("client_id", ""), client_id):
        raise InvalidGrant("Authorization code is invalid or expired.")

    # Step 5: redirect_uri must match what was sent at /authorize.
    if not constant_time_eq(code_payload.get("redirect_uri", ""), redirect_uri):
        raise InvalidGrant("Authorization code is invalid or expired.")

    # Step 6: PKCE — recompute S256(verifier), timing-safe compare.
    if code_payload.get("code_challenge_method") != "S256":
        raise InvalidGrant("Authorization code is invalid or expired.")
    if not pkce_verify(code_payload.get("code_challenge", ""), code_verifier):
        raise InvalidGrant("Authorization code is invalid or expired.")

    # Step 7: decrypt api_key, mint the token pair.
    try:
        api_key = decrypt_api_key(code_payload.get("api_key_encrypted", ""))
    except Exception as e:
        raise InvalidGrant("Authorization code is invalid or expired.") from e

    pair = _mint_pair(api_key, scope=code_payload.get("scope") or "mcp:full")
    return JSONResponse(pair, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def _handle_refresh_grant(form) -> Response:
    refresh_token = form.get("refresh_token", "")
    client_id = form.get("client_id", "")
    if not refresh_token:
        raise InvalidRequest("refresh_token is required.")

    # client_id is technically optional for public clients but we accept and
    # validate when given (some clients always send it).
    if client_id:
        decode_client_id(client_id)

    iss = _issuer()
    aud = _audience()
    try:
        payload = decode_hs256(
            refresh_token,
            token_signing_key(),
            issuer=iss,
            audience=aud,
        )
    except pyjwt.PyJWTError as e:
        raise InvalidGrant("Refresh token is invalid or expired.") from e

    if payload.get("token_type") != "refresh":
        raise InvalidGrant("Refresh token is invalid or expired.")

    jti = payload.get("jti", "")
    if not isinstance(jti, str) or not jti:
        raise InvalidGrant("Refresh token is invalid or expired.")
    if is_token_revoked(jti):
        raise InvalidGrant("Refresh token is invalid or expired.")

    # Rotate: invalidate the old refresh token so a stolen one can only be
    # used once. (RFC 6749 §10.4 recommends rotation; OAuth 2.1 mandates it
    # for public clients.)
    revoke_token(jti)

    try:
        api_key = decrypt_api_key(payload.get("api_key_encrypted", ""))
    except Exception as e:
        raise InvalidGrant("Refresh token is invalid or expired.") from e

    pair = _mint_pair(api_key, scope=payload.get("scope") or "mcp:full")
    return JSONResponse(pair, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


# ---------- /oauth/revoke -------------------------------------------------


async def revoke(request: Request) -> Response:
    """RFC 7009 — accept any token, revoke if recognized, always return 200.

    Per spec we MUST NOT leak whether the token was valid. We try to decode
    with token_signing_key, and if the JWT is well-formed we add its jti to
    the deny-list. Anything else is silently a no-op.
    """
    try:
        form = await request.form()
    except Exception:
        return Response(status_code=200)
    candidate = form.get("token", "")
    if not candidate:
        return Response(status_code=200)
    try:
        # We don't enforce iss/aud here — the spec wants tolerant revocation,
        # and a slightly mismatched audience shouldn't make the user's revoke
        # silently fail.
        payload = decode_hs256(candidate, token_signing_key(), require_exp=False)
        jti = payload.get("jti")
        if isinstance(jti, str) and jti:
            revoke_token(jti)
    except pyjwt.PyJWTError:
        pass
    return Response(status_code=200, headers={"Cache-Control": "no-store"})


# ---------- Access-token verification (called by /mcp) -------------------


def verify_access_token(token: str) -> str:
    """Verify a Bearer JWT issued by us; return the wrapped api_key.

    Raises ``OAuthError`` on any verification failure.
    """
    if not token:
        raise InvalidGrant("Missing access token.")

    iss = _issuer()
    aud = _audience()
    try:
        payload = decode_hs256(token, token_signing_key(), issuer=iss, audience=aud)
    except pyjwt.PyJWTError as e:
        raise InvalidGrant("Invalid or expired access token.") from e

    if payload.get("token_type") != "Bearer":
        raise InvalidGrant("Invalid or expired access token.")

    jti = payload.get("jti", "")
    if not isinstance(jti, str) or not jti:
        raise InvalidGrant("Invalid or expired access token.")
    if is_token_revoked(jti):
        raise InvalidGrant("Invalid or expired access token.")

    try:
        return decrypt_api_key(payload.get("api_key_encrypted", ""))
    except Exception as e:
        raise InvalidGrant("Invalid or expired access token.") from e
