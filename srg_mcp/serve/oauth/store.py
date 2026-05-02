"""In-memory state for the OAuth layer.

Cloud Run runs as multiple instances behind a load balancer. We deliberately
choose **process-local in-memory state** for short-lived items (CSRF tokens,
authorization-code one-time-use deny-lists, revoked-token deny-lists) — these
items have a 10-minute TTL and the auth flow tolerates an instance flap by
forcing the user to re-consent. Instances rarely cycle mid-flow in practice.

The signed JWT pieces (client_id, code, access_token, refresh_token) are
*stateless* — they verify on any instance via the shared HMAC key (must be
provided via env var in prod). The deny-lists are the only thing an instance
flap can drop, and the worst case is a replay window equal to the JWT TTL.

If we ever want to harden this further, swap the LRU-TTL caches in this module
for Redis backed by GCP Memorystore — the public API doesn't change.
"""
from __future__ import annotations

from cachetools import TTLCache

# CSRF tokens — issued at GET /oauth/authorize, consumed at POST. 10 min TTL
# is generous (consent page rarely takes that long) and the cache size cap
# (10000) prevents a memory exhaustion DoS via /authorize spam.
_CSRF_TTL = 600
_CSRF_MAX = 10_000

# Authorization-code one-time-use deny-list. Keyed by the random ``code``
# field embedded in the code JWT (NOT the JWT itself — the random code is the
# stable identity). 10 min matches the code's ``exp`` so we don't need to keep
# entries longer than the code is verifiable.
_CODE_DENY_TTL = 600
_CODE_DENY_MAX = 10_000

# Revoked access/refresh-token deny-list. Keyed by ``jti``. Refresh tokens
# live 30 days, so size this large enough to absorb steady-state revocations.
# 1 hour TTL on access tokens means we only need to keep an access-token jti
# in the deny-list for at most 1 hour after issue. Refresh tokens are kept
# for 30 days max.
_TOKEN_DENY_TTL = 30 * 24 * 3600  # 30 days — covers refresh_token max lifetime
_TOKEN_DENY_MAX = 100_000


csrf_tokens: TTLCache[str, str] = TTLCache(maxsize=_CSRF_MAX, ttl=_CSRF_TTL)
code_deny_list: TTLCache[str, bool] = TTLCache(maxsize=_CODE_DENY_MAX, ttl=_CODE_DENY_TTL)
token_deny_list: TTLCache[str, bool] = TTLCache(maxsize=_TOKEN_DENY_MAX, ttl=_TOKEN_DENY_TTL)


def remember_csrf(token: str) -> None:
    csrf_tokens[token] = "1"


def consume_csrf(token: str) -> bool:
    """Return True iff the token was registered; consumes it (one-shot)."""
    if not token:
        return False
    try:
        # Pop returns the value if present; KeyError otherwise.
        csrf_tokens.pop(token)
        return True
    except KeyError:
        return False


def is_code_used(code_id: str) -> bool:
    return code_id in code_deny_list


def mark_code_used(code_id: str) -> None:
    code_deny_list[code_id] = True


def is_token_revoked(jti: str) -> bool:
    return jti in token_deny_list


def revoke_token(jti: str) -> None:
    token_deny_list[jti] = True
