"""The root endpoint: https://mcp.srgplus.com IS the connector address.

POST / speaks MCP (core profile); GET / keeps the branding page; the
un-suffixed protected-resource doc advertises the root identity while the
path-suffixed docs keep their verified shapes.
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.asyncio
async def test_root_post_requires_auth(client):
    response = await client.post("/", json={})
    assert response.status_code == 401
    assert "www-authenticate" in response.headers


@pytest.mark.asyncio
async def test_root_post_serves_core_profile(client):
    response = await client.post(
        "/",
        headers={
            "X-API-Key": "srgplus_fake",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 200
    tools = {t["name"] for t in response.json()["result"]["tools"]}
    assert len(tools) == 11
    assert "list_workspaces" in tools
    assert "delete_channel" not in tools  # full set stays on /mcp only


@pytest.mark.asyncio
async def test_root_get_still_serves_branding_page(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "SRG+ MCP" in response.text


@pytest.mark.asyncio
async def test_unsuffixed_resource_doc_advertises_root(client):
    issuer = os.environ["OAUTH_ISSUER"].rstrip("/")
    root_doc = (await client.get("/.well-known/oauth-protected-resource")).json()
    mcp_doc = (
        await client.get("/.well-known/oauth-protected-resource/mcp")
    ).json()
    core_doc = (
        await client.get("/.well-known/oauth-protected-resource/mcp/core")
    ).json()
    assert root_doc["resource"] == issuer
    assert mcp_doc["resource"].endswith("/mcp")  # legacy claude.ai shape
    assert core_doc["resource"].endswith("/mcp/core")
