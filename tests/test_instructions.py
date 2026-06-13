"""Server-level instructions: present on both the full and core surfaces,
and surfaced over the wire in the MCP initialize response."""

from __future__ import annotations

import json

import pytest


def test_full_and_core_share_instructions():
    from srg_mcp._app import mcp
    from srg_mcp.serve.main import core_mcp

    assert mcp.instructions and "SRG+" in mcp.instructions
    # The load-bearing pitfalls must be present so every client gets them.
    for marker in ("workspace_id", "update_content", "upload_asset", "get_content_v2"):
        assert marker in mcp.instructions
    assert core_mcp.instructions == mcp.instructions


@pytest.mark.asyncio
async def test_initialize_returns_instructions(client):
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    resp = await client.post(
        "/mcp",
        headers={
            "X-API-Key": "srgplus_fake",
            "Accept": "application/json, text/event-stream",
        },
        json=body,
    )
    assert resp.status_code == 200
    # stateless StreamableHTTP answers initialize as an SSE frame; pull the JSON.
    text = resp.text
    payload = None
    for line in text.splitlines():
        if line.startswith("data:"):
            payload = json.loads(line[len("data:"):].strip())
            break
    if payload is None:
        payload = resp.json()
    instructions = payload["result"]["instructions"]
    assert "SRG+" in instructions and "update_content" in instructions
