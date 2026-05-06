"""Tests for the static-asset routes added in 0.4.1.

We ship a small whitelist of branding files (icon PNGs + favicon.ico) and
advertise the 512px logo URL in OAuth discovery. These tests cover:

* /favicon.ico → 200 with image/vnd.microsoft.icon and a non-empty body.
* /static/icon.png (and the resized variants) → 200 with image/png.
* Path traversal attempts via /static/<garbage> → 404 (whitelist check).
* Discovery metadata advertises ``op_logo_uri`` pointing at our static dir.

The ``client`` and ``_lifespan`` fixtures live in ``conftest.py`` — shared
with ``test_oauth.py`` so the MCP session manager only runs once.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------- favicon.ico


@pytest.mark.asyncio
async def test_favicon_ico_served(client):
    r = await client.get("/favicon.ico")
    assert r.status_code == 200
    # The whitelist sets a precise content-type — make sure we didn't fall
    # back to the generic ``application/octet-stream`` extension sniff.
    assert r.headers["content-type"] == "image/vnd.microsoft.icon"
    # Browser caching directive must be present so we don't burn bandwidth.
    assert "max-age=86400" in r.headers["cache-control"]
    # ICO files start with the 6-byte ``00 00 01 00`` icon header — a quick
    # smoke check that we're returning real binary data, not an error page.
    assert r.content[:4] == b"\x00\x00\x01\x00"
    assert len(r.content) > 100


# ---------------------------------------------------------- /static PNG variants


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename",
    ["icon.png", "icon-32.png", "icon-192.png", "icon-512.png"],
)
async def test_static_icon_png_variants(client, filename):
    r = await client.get(f"/static/{filename}")
    assert r.status_code == 200, f"{filename} returned {r.status_code}"
    assert r.headers["content-type"] == "image/png"
    assert "max-age=86400" in r.headers["cache-control"]
    # PNG magic number — guards against accidentally serving a JSON error.
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


# ----------------------------------------------------------- Whitelist / 404


@pytest.mark.asyncio
async def test_static_path_traversal_returns_404(client):
    """A request that tries to climb out of /static must NOT leak files.

    With ``StaticFiles`` this would be the canonical exploit; our whitelist
    rejects anything that isn't a known filename, so the path never reaches
    ``open()``.
    """
    # httpx normalises ``../`` segments in URLs the same way browsers do
    # before they hit the network, so we have to construct the raw path.
    r = await client.get("/static/..%2Foauth%2Fconsent.html")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_static_unknown_filename_returns_404(client):
    r = await client.get("/static/totally-not-a-file.png")
    assert r.status_code == 404


# ------------------------------------------------------- Discovery branding


@pytest.mark.asyncio
async def test_authorization_server_metadata_minimal_field_set(client):
    """AS metadata kept tight — extras break OpenAI's strict-schema parser
    ("unsupported OAuth config type" 500). Branding lives in the connector
    listing + protected-resource extras, not in AS metadata."""
    r = await client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    body = r.json()
    assert "op_logo_uri" not in body
    assert "logo_uri" not in body
    assert "service_documentation" not in body
    assert "scopes_supported" not in body


@pytest.mark.asyncio
async def test_protected_resource_metadata_minimal_field_set(client):
    """Protected-resource trimmed to match Notion/Linear minimal shape."""
    r = await client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    body = r.json()
    assert body["resource_name"] == "SRG+ MCP"
    assert "op_logo_uri" not in body
    assert "logo_uri" not in body
    assert "resource_documentation" not in body
