"""State for the OAuth layer.

CSRF is **stateless** (HMAC-signed token carrying its own timestamp), so it
verifies on any Cloud Run instance — required because the consent page GET
and the form POST can land on different instances behind the load balancer.

Authorization-code and access/refresh-token deny-lists are still process-local
TTL caches. They protect against replay within a single instance; cross-
instance replay is a known limitation that needs Redis to fix properly. Worst
case is a replay window equal to the JWT TTL (10 min for codes, 1 hour for
access tokens). Tracked as a follow-up.
"""

from __future__ import annotations

import base64
import hmac
import secrets
import struct
import time

from cachetools import TTLCache

from .jwt_codec import token_signing_key

# CSRF token TTL — 10 min is generous (the consent page rarely takes that
# long) without being so long that a stolen token stays useful.
_CSRF_TTL = 600

# Authorization-code one-time-use deny-list. Keyed by the random ``code``
# field embedded in the code JWT. 10 min matches the code's ``exp``.
_CODE_DENY_TTL = 600
_CODE_DENY_MAX = 10_000

# Revoked access/refresh-token deny-list. Keyed by ``jti``. Refresh tokens
# live 30 days; access tokens 1 hour.
_TOKEN_DENY_TTL = 30 * 24 * 3600
_TOKEN_DENY_MAX = 100_000


code_deny_list: TTLCache[str, bool] = TTLCache(
    maxsize=_CODE_DENY_MAX, ttl=_CODE_DENY_TTL
)
token_deny_list: TTLCache[str, bool] = TTLCache(
    maxsize=_TOKEN_DENY_MAX, ttl=_TOKEN_DENY_TTL
)


# ---------- CSRF (stateless, HMAC-signed) --------------------------------
#
# Format: ``b64url(nonce) . b64url(ts_be8) . b64url(hmac_sha256(nonce||ts))``
# where ``nonce`` is 16 random bytes and ``ts`` is the unix-seconds issue time
# as an 8-byte big-endian uint64. Verification recomputes the HMAC and checks
# the timestamp is within ``_CSRF_TTL``. No server state required, so it works
# across an arbitrary number of Cloud Run instances.
#
# Trade-off vs. one-shot tokens: a CSRF token can be replayed within its TTL.
# That's acceptable here because (a) it's only delivered over TLS to the
# authenticated user's browser, (b) the form also requires a valid API key,
# and (c) the redirect_uri is whitelisted per client_id, so a successful
# replay still hands the auth code to the legitimate client.


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_csrf_token() -> str:
    """Mint a stateless CSRF token. Caller embeds in the consent form."""
    nonce = secrets.token_bytes(16)
    ts = struct.pack(">Q", int(time.time()))
    sig = hmac.new(token_signing_key(), nonce + ts, "sha256").digest()[:16]
    return f"{_b64u(nonce)}.{_b64u(ts)}.{_b64u(sig)}"


def verify_csrf_token(token: str) -> bool:
    """Return True iff ``token`` was issued by ``make_csrf_token`` recently."""
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    try:
        nonce = _b64u_decode(parts[0])
        ts_bytes = _b64u_decode(parts[1])
        sig = _b64u_decode(parts[2])
    except Exception:
        return False
    if len(nonce) != 16 or len(ts_bytes) != 8 or len(sig) != 16:
        return False
    expected = hmac.new(token_signing_key(), nonce + ts_bytes, "sha256").digest()[:16]
    if not hmac.compare_digest(sig, expected):
        return False
    (ts,) = struct.unpack(">Q", ts_bytes)
    age = int(time.time()) - int(ts)
    if age < 0 or age > _CSRF_TTL:
        return False
    return True


def is_code_used(code_id: str) -> bool:
    return code_id in code_deny_list


def mark_code_used(code_id: str) -> None:
    code_deny_list[code_id] = True


def is_token_revoked(jti: str) -> bool:
    return jti in token_deny_list


def revoke_token(jti: str) -> None:
    token_deny_list[jti] = True
