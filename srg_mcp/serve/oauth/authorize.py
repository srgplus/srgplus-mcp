"""Authorization endpoint — GET renders consent, POST issues a code.

Flow:
1. claude.ai redirects the browser to GET /oauth/authorize?... with PKCE
   challenge + redirect_uri. We render a branded consent page asking the
   user to paste their SRG+ API key(s). A CSRF token is embedded in the form.
2. User pastes one or more API keys (one per line or comma-separated) and
   submits. We POST back to /oauth/authorize. We validate CSRF, validate the
   keys against SRG+ (live call), and store them as a comma-joined string
   encrypted with AES-GCM inside an authorization-code JWT. We redirect the
   browser back to claude.ai's redirect_uri with ``?code=<jwt>&state=...``.

Open-redirect prevention: ``redirect_uri`` MUST exactly match one of the
client's registered URIs (parsed component-by-component, not string
suffix). Mismatches render a 400 page — we never redirect to an
unrecognized URI.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import jinja2
import markupsafe
import srg
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from .dcr import decode_client_id
from .errors import InvalidRedirectURI, InvalidRequest, OAuthError
from .jwt_codec import (
    encode_hs256,
    encrypt_api_key,
    random_token,
    token_signing_key,
)
from .store import make_csrf_token, verify_csrf_token


def _issuer() -> str:
    return os.environ.get("OAUTH_ISSUER", "https://mcp.srgplus.com").rstrip("/")


logger = logging.getLogger("srgplus-mcp-serve.oauth")


# Code TTL — 10 min is comfortably above the consent → claude.ai → /token
# round-trip latency for any sane client.
_CODE_TTL = 600

_TEMPLATE_DIR = Path(__file__).parent
_jinja = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html"]),  # auto-escape user input
    keep_trailing_newline=False,
)


def _redirect_uri_matches(requested: str, registered: list[str]) -> bool:
    """Exact-match check on the redirect_uri.

    We compare *parsed* URLs component-by-component to defeat tricks like
    ``https://claude.ai.attacker.com`` masquerading as a suffix of
    ``https://claude.ai``. Both URIs are normalized to lowercase scheme/host
    so case differences don't break legitimate clients.
    """
    if not requested:
        return False
    req = urlparse(requested)
    if not req.scheme or not req.netloc:
        return False
    for reg in registered:
        r = urlparse(reg)
        if (
            req.scheme.lower() == r.scheme.lower()
            and req.netloc.lower() == r.netloc.lower()
            and req.path == r.path
            and req.params == r.params
            and req.query == r.query
            and req.fragment == r.fragment
        ):
            return True
    return False


def _validate_oauth_params(
    *,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    code_challenge: str,
    code_challenge_method: str,
) -> dict:
    """Run the validation that's shared between GET and POST.

    Returns the decoded client metadata dict on success. Raises ``OAuthError``
    on any failure (caller picks how to render the error).
    """
    if response_type != "code":
        raise InvalidRequest("response_type must be 'code'.")
    if code_challenge_method != "S256":
        raise InvalidRequest("code_challenge_method must be 'S256'.")
    if not code_challenge:
        raise InvalidRequest("code_challenge is required.")
    if not redirect_uri:
        raise InvalidRequest("redirect_uri is required.")

    # decode_client_id raises InvalidClient on bad/unknown client_id.
    client = decode_client_id(client_id)
    registered = client.get("redirect_uris") or []
    if not _redirect_uri_matches(redirect_uri, registered):
        raise InvalidRedirectURI(
            "redirect_uri does not match a registered URI for this client."
        )
    return client


def _render_consent(
    *,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    code_challenge: str,
    code_challenge_method: str,
    state: str,
    scope: str,
    client_name: str,
    error: str | None = None,
) -> HTMLResponse:
    csrf_token = make_csrf_token()
    template = _jinja.get_template("consent.html")
    html = template.render(
        csrf_token=csrf_token,
        client_id=client_id,
        redirect_uri=redirect_uri,
        response_type=response_type,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        state=state,
        scope=scope,
        client_name=client_name,
        error=error,
    )
    # CSP form-action: must allow the client's redirect_uri origin, otherwise
    # the browser blocks the post-submit 302 from us → client. (We saw this
    # break claude.ai's flow: POST 302 fired, browser refused to follow the
    # cross-origin redirect, no /token call ever happened.) Server-side we
    # already restrict redirect_uri to registered values, so this only ever
    # whitelists URLs we'd already redirect to.
    parsed_redirect = urlparse(redirect_uri)
    redirect_origin = (
        f"{parsed_redirect.scheme}://{parsed_redirect.netloc}"
        if parsed_redirect.scheme and parsed_redirect.netloc
        else ""
    )
    form_action = f"'self' {redirect_origin}".strip()
    csp = f"default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action {form_action}"
    # Defensive headers: never let consent pages get cached or framed.
    return HTMLResponse(
        html,
        status_code=200,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": csp,
            "Referrer-Policy": "no-referrer",
        },
    )


def _error_html(message: str, status: int = 400) -> HTMLResponse:
    """Static, branded error page used when we can't safely redirect.

    Used specifically for redirect_uri mismatches and unknown client_id —
    where redirecting back would either leak info or hand control to an
    attacker-controlled URL.
    """
    safe = markupsafe.escape(message)
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>SRG+ — Authorization error</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0b0d10;color:#f5f7fa;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}main{{max-width:480px;padding:32px;text-align:center}}h1{{color:#ef4444}}p{{color:#8b95a3}}</style>
</head><body><main><h1>Authorization error</h1><p>{safe}</p></main></body></html>""",
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


async def authorize_get(request: Request) -> Response:
    qs = request.query_params
    try:
        client = _validate_oauth_params(
            client_id=qs.get("client_id", ""),
            redirect_uri=qs.get("redirect_uri", ""),
            response_type=qs.get("response_type", ""),
            code_challenge=qs.get("code_challenge", ""),
            code_challenge_method=qs.get("code_challenge_method", ""),
        )
    except OAuthError as e:
        # Per OAuth 2.1 §4.1.2.1: we MUST NOT redirect when the client_id or
        # redirect_uri is invalid. Render an error page in-place.
        return _error_html(e.description, status=e.status)

    return _render_consent(
        client_id=qs.get("client_id", ""),
        redirect_uri=qs.get("redirect_uri", ""),
        response_type=qs.get("response_type", "code"),
        code_challenge=qs.get("code_challenge", ""),
        code_challenge_method=qs.get("code_challenge_method", "S256"),
        state=qs.get("state", ""),
        scope=qs.get("scope") or "mcp:full",
        client_name=client.get("client_name") or "Unnamed Client",
    )


async def authorize_post(request: Request) -> Response:
    form = await request.form()
    csrf_token = form.get("csrf_token", "")
    client_id = form.get("client_id", "")
    redirect_uri = form.get("redirect_uri", "")
    response_type = form.get("response_type", "")
    code_challenge = form.get("code_challenge", "")
    code_challenge_method = form.get("code_challenge_method", "")
    state = form.get("state", "")
    scope = form.get("scope") or "mcp:full"
    api_key_raw = form.get("api_key", "")

    # Validate OAuth params first — same checks as GET. If they fail, render
    # the error page (do not redirect: the redirect_uri may be malicious).
    try:
        client = _validate_oauth_params(
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )
    except OAuthError as e:
        return _error_html(e.description, status=e.status)

    # CSRF is required before we'll consider the api_key. The token is
    # stateless (HMAC-signed) so it verifies on any Cloud Run instance.
    if not verify_csrf_token(csrf_token):
        # Issue a fresh CSRF token on the rerender so the user can retry.
        return _render_consent(
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            state=state,
            scope=scope,
            client_name=client.get("client_name") or "Unnamed Client",
            error="Your session expired. Please try again.",
        )

    # Parse comma-separated api_keys (supports one or many).
    # Normalize: strip whitespace + newlines around each key, drop empties.
    api_keys_list = [
        k.strip() for k in api_key_raw.replace("\n", ",").split(",") if k.strip()
    ]

    # Live-validate all keys against SRG+ at once. We surface a uniform
    # "Invalid API key" on failure — never leak which check failed.
    if not api_keys_list or not _validate_api_keys(api_keys_list):
        return _render_consent(
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            state=state,
            scope=scope,
            client_name=client.get("client_name") or "Unnamed Client",
            error="Invalid API key.",
        )

    # Store as comma-joined string in the JWT so multi-key entries round-trip.
    api_keys_str = ",".join(api_keys_list)

    # Mint the authorization code JWT.
    now = int(time.time())
    code_id = random_token(32)
    code_jwt = encode_hs256(
        {
            "iat": now,
            "exp": now + _CODE_TTL,
            "code": code_id,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "api_key_encrypted": encrypt_api_key(api_keys_str),
            "scope": scope,
        },
        token_signing_key(),
    )

    # Build the redirect URL. Note: we ONLY redirect to URIs we already
    # validated against the registered list — that's the open-redirect
    # guarantee.
    #
    # ``iss`` (RFC 9207) is included so the client can detect mix-up attacks
    # where a code from a malicious AS is replayed at a legitimate AS. Some
    # MCP clients (claude.ai's web wizard included) treat a missing ``iss``
    # as "unknown AS" and silently abandon the token-exchange step.
    params = {"code": code_jwt, "iss": _issuer()}
    if state:
        params["state"] = state
    sep = "&" if urlparse(redirect_uri).query else "?"
    location = f"{redirect_uri}{sep}{urlencode(params)}"

    logger.info(
        "oauth.authorize.success client_id=%s redirect_host=%s code_len=%d state_present=%s",
        client_id[:16] + "...",
        urlparse(redirect_uri).netloc,
        len(code_jwt),
        bool(state),
    )

    # 302 (Found) is the historical OAuth choice; some legacy clients
    # mishandle 303. Either is spec-compliant.
    return RedirectResponse(
        location, status_code=302, headers={"Cache-Control": "no-store"}
    )


def _validate_api_keys(api_keys: list[str]) -> bool:
    """Live-check one or more api_keys against SRG+.

    Attempts ``SRGClient(api_keys=...)``; the constructor calls
    ``/api/v1/workspaces`` for each key and populates the registry with
    valid ones (invalid keys are silently skipped). Returns True if at
    least one key resolved to a workspace.

    We conflate all failure modes into a single False return — the
    user-visible error is uniform ("Invalid API key") to avoid leaking
    which check failed.
    """
    try:
        client = srg.SRGClient(api_keys=api_keys, timeout=10.0)
        return len(client.workspace_ids) > 0
    except Exception as exc:
        # Log the exception TYPE only — never include `exc` directly in case
        # the message embeds the api_key.
        logger.warning("API key validation failed (%s)", type(exc).__name__)
        return False
