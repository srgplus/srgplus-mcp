"""PKCE S256 verification (RFC 7636 §4.6).

The client picks a random ``code_verifier`` and sends ``code_challenge =
BASE64URL-NO-PAD(SHA256(verifier))`` to /authorize. At /token they send the
raw verifier; we recompute the challenge and compare timing-safely.
"""

from __future__ import annotations

import base64
import hashlib
import hmac


def s256(verifier: str) -> str:
    """Compute the PKCE S256 challenge from a verifier.

    BASE64URL with no padding, per RFC 7636.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verify(challenge: str, verifier: str) -> bool:
    """Timing-safe check: did this verifier produce this challenge?"""
    if not challenge or not verifier:
        return False
    expected = s256(verifier)
    return hmac.compare_digest(expected, challenge)
