"""JWT signing/verification + AES-GCM api_key encryption.

Three independent secrets are loaded from env on first use:

* ``OAUTH_CLIENT_REGISTRATION_KEY`` — HMAC-SHA256 key used to sign DCR
  ``client_id`` JWTs. (Stateless DCR — the client_id IS the registration.)
* ``OAUTH_TOKEN_SIGNING_KEY`` — HMAC-SHA256 key used to sign authorization
  codes, access tokens, and refresh tokens.
* ``OAUTH_API_KEY_ENCRYPTION_KEY`` — 32-byte AES-256-GCM key used to encrypt
  the user's SRG+ workspace API key inside JWT payloads.

Each secret is independent so a leak of one doesn't compromise the others.
In dev, missing secrets are filled with random per-process values and a
warning is logged — sessions die when the process restarts. In prod, these
must be set via GCP Secret Manager.
"""
from __future__ import annotations

import base64
import hmac
import logging
import os
import secrets
from typing import Any

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("srgplus-mcp-serve.oauth")


_CLIENT_REG_KEY: bytes | None = None
_TOKEN_SIGN_KEY: bytes | None = None
_API_KEY_ENC_KEY: bytes | None = None


def _load_or_generate(env_name: str, *, byte_length: int = 32) -> bytes:
    """Load a secret from env; if absent, generate one and warn loudly.

    The generated value lives only in process memory — restarts invalidate
    every JWT/encrypted blob signed under it. That's intentional for dev: a
    forgetful operator gets a clear "tokens broke after deploy" signal rather
    than a silent acceptance of weak keys.
    """
    raw = os.environ.get(env_name, "").strip()
    if raw:
        # Accept either a base64url-encoded value or a raw string. We detect
        # base64url by trying to decode and checking length; everything else
        # is treated as raw UTF-8.
        try:
            decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
            if len(decoded) >= byte_length:
                return decoded[:byte_length] if byte_length == 32 else decoded
        except Exception:
            pass
        # Fall through: HMAC-SHA256 happily accepts any-length keys >=16
        # bytes; AES-256-GCM needs exactly 32 bytes — caller checks.
        return raw.encode("utf-8")
    generated = secrets.token_bytes(byte_length)
    logger.warning(
        "%s not set — generated an ephemeral %d-byte key. "
        "Existing sessions will break on process restart. "
        "Set this via GCP Secret Manager in production.",
        env_name,
        byte_length,
    )
    return generated


def client_registration_key() -> bytes:
    global _CLIENT_REG_KEY
    if _CLIENT_REG_KEY is None:
        _CLIENT_REG_KEY = _load_or_generate("OAUTH_CLIENT_REGISTRATION_KEY")
    return _CLIENT_REG_KEY


def token_signing_key() -> bytes:
    global _TOKEN_SIGN_KEY
    if _TOKEN_SIGN_KEY is None:
        _TOKEN_SIGN_KEY = _load_or_generate("OAUTH_TOKEN_SIGNING_KEY")
    return _TOKEN_SIGN_KEY


def api_key_encryption_key() -> bytes:
    """Return a 32-byte AES-256-GCM key.

    If the env var holds a base64url value, we decode it; otherwise we hash
    the raw bytes through SHA-256 to derive a 32-byte key. AES-GCM rejects
    anything other than 16/24/32 bytes — this normalizes safely.
    """
    global _API_KEY_ENC_KEY
    if _API_KEY_ENC_KEY is None:
        raw = _load_or_generate("OAUTH_API_KEY_ENCRYPTION_KEY", byte_length=32)
        if len(raw) == 32:
            _API_KEY_ENC_KEY = raw
        else:
            import hashlib

            _API_KEY_ENC_KEY = hashlib.sha256(raw).digest()
    return _API_KEY_ENC_KEY


# ---------- JWT helpers --------------------------------------------------


def encode_hs256(payload: dict[str, Any], key: bytes) -> str:
    return jwt.encode(payload, key, algorithm="HS256")


def decode_hs256(
    token: str,
    key: bytes,
    *,
    issuer: str | None = None,
    audience: str | None = None,
    require_exp: bool = True,
) -> dict[str, Any]:
    """Decode + verify HS256 JWT with full claim validation.

    ``aud`` and ``iss`` are checked when given. ``exp`` is required by
    default. ``iat`` is required to detect malformed tokens.

    Raises ``jwt.PyJWTError`` (or a subclass) on any failure; callers should
    catch and convert to ``InvalidGrant`` / ``InvalidClient`` as appropriate.
    """
    options = {
        "require": ["iat"] + (["exp"] if require_exp else []),
        "verify_signature": True,
        "verify_exp": require_exp,
        "verify_iat": True,
        "verify_aud": audience is not None,
        "verify_iss": issuer is not None,
    }
    return jwt.decode(
        token,
        key,
        algorithms=["HS256"],
        issuer=issuer,
        audience=audience,
        options=options,
    )


# ---------- AES-GCM api_key encryption -----------------------------------


def encrypt_api_key(api_key: str) -> str:
    """Encrypt the SRG+ workspace api_key for embedding in a JWT.

    Output format: ``base64url(nonce || ciphertext_with_tag)``. A fresh
    12-byte random nonce per call — never reused. AES-GCM's authenticated
    encryption guarantees both confidentiality and integrity.
    """
    if not api_key:
        raise ValueError("api_key must be non-empty")
    aes = AESGCM(api_key_encryption_key())
    nonce = secrets.token_bytes(12)
    ct = aes.encrypt(nonce, api_key.encode("utf-8"), associated_data=None)
    blob = nonce + ct
    return base64.urlsafe_b64encode(blob).rstrip(b"=").decode("ascii")


def decrypt_api_key(blob: str) -> str:
    """Inverse of ``encrypt_api_key``. Raises on tamper or wrong key."""
    if not blob:
        raise ValueError("blob must be non-empty")
    padded = blob + "=" * (-len(blob) % 4)
    raw = base64.urlsafe_b64decode(padded)
    if len(raw) < 13:
        raise ValueError("ciphertext too short")
    nonce, ct = raw[:12], raw[12:]
    aes = AESGCM(api_key_encryption_key())
    pt = aes.decrypt(nonce, ct, associated_data=None)
    return pt.decode("utf-8")


# ---------- Convenience ---------------------------------------------------


def random_token(byte_length: int = 32) -> str:
    """URL-safe random string for csrf/code/jti."""
    return secrets.token_urlsafe(byte_length)


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
