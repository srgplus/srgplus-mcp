"""OAuth 2.1 error types and helpers.

Errors follow RFC 6749 §5.2 — JSON body with ``error`` and optional
``error_description``. We never include the exact reason a credential failed
(timing-safe + uniform messages); see the security checklist.
"""

from __future__ import annotations

from typing import Any


class OAuthError(Exception):
    """Base class for all OAuth-layer errors.

    ``code`` is the RFC 6749 error code (e.g. ``invalid_grant``,
    ``invalid_request``). ``status`` is the HTTP status to return.
    ``description`` is a *uniform* message safe to send to the client — never
    interpolate user input into it (avoid leaking which check failed).
    """

    code: str = "server_error"
    status: int = 500
    description: str = "An unexpected error occurred."

    def __init__(
        self,
        description: str | None = None,
        *,
        code: str | None = None,
        status: int | None = None,
    ) -> None:
        if description is not None:
            self.description = description
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status
        super().__init__(self.description)

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.code, "error_description": self.description}


class InvalidRequest(OAuthError):
    code = "invalid_request"
    status = 400
    description = (
        "The request is missing a required parameter or is otherwise malformed."
    )


class InvalidClient(OAuthError):
    code = "invalid_client"
    status = 400
    description = "Client authentication failed."


class InvalidGrant(OAuthError):
    code = "invalid_grant"
    status = 400
    description = "The provided authorization grant is invalid, expired, revoked, or does not match."


class UnauthorizedClient(OAuthError):
    code = "unauthorized_client"
    status = 400
    description = "The client is not authorized to use this grant type."


class UnsupportedGrantType(OAuthError):
    code = "unsupported_grant_type"
    status = 400
    description = "The grant type is not supported."


class InvalidRedirectURI(OAuthError):
    code = "invalid_request"
    status = 400
    description = "The redirect_uri is not registered for this client."
