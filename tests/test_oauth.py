"""End-to-end tests for the OAuth 2.1 layer added in SRGDEV-26.

We use ``httpx.ASGITransport`` to drive the full Starlette app in-process
(no real socket/uvicorn) and ``respx`` to mock the SRG+ HTTP API at the
``/api/v1/...`` boundary so we don't need a live workspace API key.

Coverage:

* Discovery (RFC 8414, RFC 9728) — JSON shape & required fields
* DCR (RFC 7591) — happy path, malformed body, redirect_uris validation
* Authorize GET — consent rendering, open-redirect rejection
* Authorize POST — CSRF enforcement, valid api_key issues code, invalid
  api_key re-renders consent
* Token endpoint — code exchange, replay rejection, PKCE failure
* Token endpoint — refresh_token grant + rotation (old refresh denied)
* Revocation endpoint — always 200, revoked access token rejected at /mcp
* /mcp endpoint — accepts X-API-Key, srgplus_ Bearer, OAuth Bearer JWT;
  rejects revoked OAuth tokens; emits WWW-Authenticate on 401
* CORS preflight from ``https://claude.ai``
"""

from __future__ import annotations

import base64
import hashlib
import os
import re

import httpx
import pytest
import respx

# OAuth env defaults are set in conftest.py BEFORE the app is imported.
# Re-stating them here is harmless — ``setdefault`` is idempotent.
os.environ.setdefault("OAUTH_ISSUER", "http://localhost:8090")
os.environ.setdefault(
    "OAUTH_CLIENT_REGISTRATION_KEY", "test-client-reg-key-for-pytest-only-please"
)
os.environ.setdefault(
    "OAUTH_TOKEN_SIGNING_KEY", "test-token-signing-key-for-pytest-only-please"
)
os.environ.setdefault(
    "OAUTH_API_KEY_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"x" * 32).decode()
)

from srg_mcp.serve.oauth import store as store_module  # noqa: E402


REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _consent_csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m is not None, "csrf_token not found in consent HTML"
    return m.group(1)


# ------------------------------------------------------------------ Fixtures
#
# ``_lifespan`` and ``client`` live in conftest.py — shared with test_static
# so the StreamableHTTPSessionManager only runs once per session.


@pytest.fixture(autouse=True)
def reset_state():
    """Clear all in-memory caches between tests."""
    store_module.code_deny_list.clear()
    store_module.token_deny_list.clear()
    yield


@pytest.fixture
def srg_mock():
    """Mock SRG+ HTTP calls.

    ``SRGClient(api_key=...)`` calls ``GET /api/v1/workspaces`` on
    construction to bootstrap the workspace_id — that's the auth probe used
    by the consent page to validate api_keys.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r".+/api/v1/workspaces.*").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": "ws_test", "name": "Test"}],
            )
        )
        mock.get(url__regex=r".+/api/v\d/.*").mock(
            return_value=httpx.Response(200, json={})
        )
        yield mock


# ----------------------------------------------------------------- Helpers


async def _register(c: httpx.AsyncClient) -> str:
    r = await c.post(
        "/oauth/register",
        json={"redirect_uris": [REDIRECT_URI], "client_name": "Claude.ai"},
    )
    return r.json()["client_id"]


async def _full_authorize_flow(
    c: httpx.AsyncClient, *, verifier: str
) -> tuple[str, str]:
    """Run register → /authorize GET → /authorize POST and return (client_id, code)."""
    client_id = await _register(c)
    challenge = _s256(verifier)
    r = await c.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "x",
        },
    )
    csrf = _consent_csrf(r.text)
    r = await c.post(
        "/oauth/authorize",
        data={
            "csrf_token": csrf,
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "x",
            "scope": "mcp:full",
            "api_key": "srgplus_validkey",
        },
    )
    assert r.status_code == 302, (
        f"authorize_flow expected 302, got {r.status_code}: {r.text[:200]}"
    )
    from urllib.parse import parse_qs, urlparse

    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    return client_id, code


# --------------------------------------------------------------- Discovery


@pytest.mark.asyncio
async def test_authorization_server_metadata(client):
    r = await client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    body = r.json()
    assert body["issuer"] == "http://localhost:8090"
    assert body["authorization_endpoint"].endswith("/oauth/authorize")
    assert body["token_endpoint"].endswith("/oauth/token")
    assert body["registration_endpoint"].endswith("/oauth/register")
    assert body["revocation_endpoint"].endswith("/oauth/revoke")
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert "authorization_code" in body["grant_types_supported"]
    assert "refresh_token" in body["grant_types_supported"]
    assert body["token_endpoint_auth_methods_supported"] == ["none"]
    assert "mcp:full" in body["scopes_supported"]


@pytest.mark.asyncio
async def test_authorization_server_metadata_path_suffix(client):
    """ChatGPT's MCP connector probes ``/.well-known/oauth-authorization-server/mcp``;
    we serve identical metadata there so the wizard doesn't reject the server with
    "OAuth discovery returned unsupported OAuth config type" (regression: PR #6
    added the path-suffix variant for protected-resource only)."""
    r = await client.get("/.well-known/oauth-authorization-server/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["issuer"] == "http://localhost:8090"
    assert body["authorization_endpoint"].endswith("/oauth/authorize")
    assert body["code_challenge_methods_supported"] == ["S256"]


@pytest.mark.asyncio
async def test_protected_resource_metadata(client):
    r = await client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"].endswith("/mcp")
    assert "http://localhost:8090" in body["authorization_servers"]
    assert body["bearer_methods_supported"] == ["header"]


@pytest.mark.asyncio
async def test_protected_resource_metadata_path_suffix(client):
    """RFC 9728 §3.1 path-suffix variant — same metadata as the bare URL."""
    r = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"].endswith("/mcp")
    assert "http://localhost:8090" in body["authorization_servers"]


# ----------------------------------------------------------------- DCR


@pytest.mark.asyncio
async def test_dcr_happy_path(client):
    r = await client.post(
        "/oauth/register",
        json={
            "redirect_uris": [REDIRECT_URI],
            "client_name": "Claude.ai",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["client_id"]
    assert body["redirect_uris"] == [REDIRECT_URI]
    assert body["client_name"] == "Claude.ai"
    assert body["token_endpoint_auth_method"] == "none"
    # client_id is a JWT — three dot-separated base64url segments
    assert body["client_id"].count(".") == 2


@pytest.mark.asyncio
async def test_dcr_rejects_missing_redirect_uris(client):
    r = await client.post("/oauth/register", json={"client_name": "x"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_dcr_rejects_relative_redirect_uri(client):
    r = await client.post(
        "/oauth/register",
        json={"redirect_uris": ["/relative/path"], "client_name": "x"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_dcr_rejects_non_none_auth_method(client):
    r = await client.post(
        "/oauth/register",
        json={
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "client_secret_basic",
        },
    )
    assert r.status_code == 400


# ---------------------------------------------------------- Authorize GET


@pytest.mark.asyncio
async def test_authorize_get_renders_consent(client):
    client_id = await _register(client)
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": _s256("verifier-x" * 5),
            "code_challenge_method": "S256",
            "state": "abc123",
        },
    )
    assert r.status_code == 200
    assert "Connect to SRG+" in r.text
    assert "csrf_token" in r.text
    assert "Claude.ai" in r.text
    assert r.headers.get("x-frame-options") == "DENY"


@pytest.mark.asyncio
async def test_authorize_get_rejects_unregistered_redirect_uri(client):
    client_id = await _register(client)
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://attacker.example/cb",
            "response_type": "code",
            "code_challenge": "AAAA",
            "code_challenge_method": "S256",
        },
    )
    # Static error page — NEVER a redirect to an unregistered URI.
    assert r.status_code == 400
    assert "Authorization error" in r.text
    assert "Location" not in r.headers


@pytest.mark.asyncio
async def test_authorize_get_rejects_substring_redirect_uri(client):
    """``https://claude.ai.attacker.com`` must not match ``https://claude.ai/...``."""
    client_id = await _register(client)
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://claude.ai.attacker.com/api/mcp/auth_callback",
            "response_type": "code",
            "code_challenge": "AAAA",
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_authorize_get_rejects_unknown_client_id(client):
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": "not.a.valid.jwt",
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": "AAAA",
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_authorize_get_rejects_plain_pkce(client):
    client_id = await _register(client)
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": "AAAA",
            "code_challenge_method": "plain",  # not allowed
        },
    )
    assert r.status_code == 400


# ---------------------------------------------------------- Authorize POST


@pytest.mark.asyncio
async def test_authorize_post_valid_key_redirects_with_code(client, srg_mock):
    verifier = "test-verifier-" + ("x" * 50)
    challenge = _s256(verifier)
    client_id = await _register(client)
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "state-xyz",
        },
    )
    csrf = _consent_csrf(r.text)
    r = await client.post(
        "/oauth/authorize",
        data={
            "csrf_token": csrf,
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "state-xyz",
            "scope": "mcp:full",
            "api_key": "srgplus_validkey",
        },
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(REDIRECT_URI)
    assert "code=" in loc
    assert "state=state-xyz" in loc


@pytest.mark.asyncio
async def test_authorize_post_invalid_csrf_rerenders(client, srg_mock):
    client_id = await _register(client)
    r = await client.post(
        "/oauth/authorize",
        data={
            "csrf_token": "fake-token",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": "AAAA",
            "code_challenge_method": "S256",
            "state": "x",
            "scope": "mcp:full",
            "api_key": "srgplus_validkey",
        },
    )
    assert r.status_code == 200
    assert "Connect to SRG+" in r.text
    assert "expired" in r.text.lower()


@pytest.mark.asyncio
async def test_authorize_post_csrf_is_stateless_across_instances(client, srg_mock):
    """A CSRF token issued by one instance must verify on another.

    We simulate the multi-instance case by clearing process-local state
    between the GET (consent page) and POST (form submit). Pre-fix this
    rendered the token unverifiable because it lived in an in-memory cache;
    with HMAC-signed stateless tokens, verification works regardless.
    """
    client_id = await _register(client)
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": _s256("v" * 50),
            "code_challenge_method": "S256",
            "state": "x",
        },
    )
    csrf = _consent_csrf(r.text)
    # Simulate the POST landing on a different Cloud Run instance: any
    # process-local caches that existed for the GET are gone.
    store_module.code_deny_list.clear()
    store_module.token_deny_list.clear()
    r1 = await client.post(
        "/oauth/authorize",
        data={
            "csrf_token": csrf,
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": _s256("v" * 50),
            "code_challenge_method": "S256",
            "state": "x",
            "scope": "mcp:full",
            "api_key": "srgplus_validkey",
        },
    )
    assert r1.status_code == 302


@pytest.mark.asyncio
async def test_authorize_post_invalid_api_key_rerenders(client):
    """When SRG+ rejects the api_key, re-render consent with uniform error."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r".+/api/v1/workspaces.*").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        client_id = await _register(client)
        r = await client.get(
            "/oauth/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "code_challenge": _s256("v" * 50),
                "code_challenge_method": "S256",
                "state": "x",
            },
        )
        csrf = _consent_csrf(r.text)
        r = await client.post(
            "/oauth/authorize",
            data={
                "csrf_token": csrf,
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "code_challenge": _s256("v" * 50),
                "code_challenge_method": "S256",
                "state": "x",
                "scope": "mcp:full",
                "api_key": "srgplus_badkey",
            },
        )
    assert r.status_code == 200
    assert "Invalid API key" in r.text


# --------------------------------------------------------------- /oauth/token


@pytest.mark.asyncio
async def test_token_code_exchange(client, srg_mock):
    verifier = "verifier-" + ("v" * 50)
    client_id, code = await _full_authorize_flow(client, verifier=verifier)
    r = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert body["scope"] == "mcp:full"
    assert body["access_token"]
    assert body["refresh_token"]
    assert "no-store" in r.headers.get("cache-control", "")


@pytest.mark.asyncio
async def test_token_code_replay_rejected(client, srg_mock):
    verifier = "verifier-" + ("v" * 50)
    client_id, code = await _full_authorize_flow(client, verifier=verifier)
    r1 = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert r1.status_code == 200
    r2 = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert r2.status_code == 400
    assert r2.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_token_bad_pkce_verifier(client, srg_mock):
    verifier = "verifier-" + ("v" * 50)
    client_id, code = await _full_authorize_flow(client, verifier=verifier)
    r = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": "wrong-verifier-" + ("z" * 40),
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_token_redirect_uri_mismatch(client, srg_mock):
    verifier = "verifier-" + ("v" * 50)
    client_id, code = await _full_authorize_flow(client, verifier=verifier)
    r = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://other.example/cb",
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_token_unsupported_grant(client):
    r = await client.post(
        "/oauth/token",
        data={"grant_type": "password", "username": "x", "password": "y"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


@pytest.mark.asyncio
async def test_refresh_token_grant_rotates(client, srg_mock):
    verifier = "verifier-" + ("v" * 50)
    client_id, code = await _full_authorize_flow(client, verifier=verifier)
    r = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    first = r.json()
    old_refresh = first["refresh_token"]

    r = await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": old_refresh,
            "client_id": client_id,
        },
    )
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != old_refresh

    # Reusing the OLD refresh must fail (rotation enforced)
    r = await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": old_refresh,
            "client_id": client_id,
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


# -------------------------------------------------------------- /oauth/revoke


@pytest.mark.asyncio
async def test_revoke_returns_200_for_anything(client):
    r = await client.post("/oauth/revoke", data={})
    assert r.status_code == 200
    r = await client.post("/oauth/revoke", data={"token": "garbage"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_revoke_marks_access_token_invalid(client, srg_mock):
    verifier = "verifier-" + ("v" * 50)
    client_id, code = await _full_authorize_flow(client, verifier=verifier)
    r = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    access = r.json()["access_token"]

    r = await client.post("/oauth/revoke", data={"token": access})
    assert r.status_code == 200

    r = await client.post(
        "/mcp",
        headers={
            "authorization": f"Bearer {access}",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        content="{}",
    )
    assert r.status_code == 401


# ----------------------------------------------------------------- /mcp


@pytest.mark.asyncio
async def test_mcp_unauthenticated_includes_www_authenticate(client):
    r = await client.post(
        "/mcp",
        headers={
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        content="{}",
    )
    assert r.status_code == 401
    auth = r.headers.get("www-authenticate", "")
    assert "Bearer" in auth
    assert "as_uri=" in auth
    assert "/.well-known/oauth-authorization-server" in auth


@pytest.mark.asyncio
async def test_mcp_unauthenticated_tools_list_for_descriptor_scan(client):
    r = await client.post(
        "/mcp",
        headers={
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        content='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}',
    )
    assert r.status_code == 200
    body = r.json()
    assert "result" in body
    assert "tools" in body["result"]
    assert len(body["result"]["tools"]) > 0


@pytest.mark.asyncio
async def test_mcp_unauthenticated_tool_call_still_requires_auth(client):
    r = await client.post(
        "/mcp",
        headers={
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        content=(
            '{"jsonrpc":"2.0","id":1,"method":"tools/call",'
            '"params":{"name":"list_workspaces","arguments":{}}}'
        ),
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_api_key"


@pytest.mark.asyncio
async def test_mcp_x_api_key_backward_compat(client):
    """Header path: tools/list should succeed against the SDK, even with a
    fake key (the SDK only calls the network on actual tool invocation)."""
    r = await client.post(
        "/mcp",
        headers={
            "x-api-key": "srgplus_legacy_header",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        content='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}',
    )
    assert r.status_code == 200
    body = r.json()
    assert "result" in body
    assert "tools" in body["result"]
    assert len(body["result"]["tools"]) > 0


@pytest.mark.asyncio
async def test_mcp_bearer_srgplus_backward_compat(client):
    """Bearer with raw srgplus_ key — Cursor/Cline path."""
    r = await client.post(
        "/mcp",
        headers={
            "authorization": "Bearer srgplus_legacy_bearer",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        content='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}',
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_mcp_oauth_bearer_jwt_works(client, srg_mock):
    """Full claude.ai path: DCR → authorize → token → /mcp with JWT."""
    verifier = "verifier-" + ("v" * 50)
    client_id, code = await _full_authorize_flow(client, verifier=verifier)
    r = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    access = r.json()["access_token"]
    r = await client.post(
        "/mcp",
        headers={
            "authorization": f"Bearer {access}",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        content='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}',
    )
    assert r.status_code == 200
    body = r.json()
    assert "result" in body
    assert "tools" in body["result"]


@pytest.mark.asyncio
async def test_mcp_invalid_jwt_returns_401(client):
    r = await client.post(
        "/mcp",
        headers={
            "authorization": "Bearer not.a.valid.jwt.at.all",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        content="{}",
    )
    assert r.status_code == 401


# ----------------------------------------------------------------- CORS


@pytest.mark.asyncio
async def test_cors_preflight_from_claude_ai(client):
    r = await client.options(
        "/oauth/token",
        headers={
            "origin": "https://claude.ai",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") in ("*", "https://claude.ai")
    methods = r.headers.get("access-control-allow-methods", "")
    assert "POST" in methods


@pytest.mark.asyncio
async def test_cors_preflight_for_mcp(client):
    r = await client.options(
        "/mcp",
        headers={
            "origin": "https://claude.ai",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type, authorization",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") in ("*", "https://claude.ai")
