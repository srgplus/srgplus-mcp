"""The /mcp/core curated profile: exact tool list, untouched full set,
shared (wrapped) tool objects, auth wiring, and RFC 9728 resource echo."""

from __future__ import annotations

import pytest

from srg_mcp.serve.profiles import CORE_TOOL_NAMES, build_core_mcp


EXPECTED_CORE = {
    "list_workspaces",
    "list_hub_profiles",
    "list_channels",
    "get_channel",
    "search_contents",
    "get_content",
    "get_content_v2",
    "create_content",
    "update_content",
    "upload_asset",
    "add_content_to_categories",
    "archive_content",
    "restore_content",
    "archive_channel",
    "archive_category",
    "archive_hub_profile",
    "restore_hub_profile",
}


def test_core_list_is_exactly_the_curated_set():
    # The deliberate, reviewed surface — a tool added/removed from the core
    # profile must show up as a diff in THIS test, not just in profiles.py.
    assert set(CORE_TOOL_NAMES) == EXPECTED_CORE


@pytest.mark.asyncio
async def test_core_mcp_serves_only_core_tools():
    from srg_mcp.serve.main import core_mcp

    names = {t.name for t in await core_mcp.list_tools()}
    assert names == EXPECTED_CORE


@pytest.mark.asyncio
async def test_full_mcp_unchanged_and_superset():
    from srg_mcp._app import mcp

    names = {t.name for t in await mcp.list_tools()}
    assert len(names) >= 90  # full surface still loaded
    assert EXPECTED_CORE <= names
    # Hard-delete tools exist on the full surface but are intentionally kept
    # OUT of the agent core profile (archive-only); deletes are manual-only.
    for hard_delete in ("delete_channel", "delete_category", "delete_hub_profile",
                        "delete_permission_group"):
        assert hard_delete in names, f"{hard_delete} should stay on full /mcp"
        assert hard_delete not in EXPECTED_CORE, f"{hard_delete} must NOT be in core"
    # Archive stays available in core (reversible).
    assert {"archive_content", "archive_channel", "archive_hub_profile"} <= EXPECTED_CORE


def test_core_tools_share_wrapped_functions():
    from srg_mcp._app import mcp
    from srg_mcp.serve.main import core_mcp

    full_tools = mcp._tool_manager._tools
    for name, tool in core_mcp._tool_manager._tools.items():
        assert tool is full_tools[name]  # same object, same schema
        assert getattr(tool.fn, "_srg_error_wrapped", False)


def test_build_core_mcp_fails_loudly_on_missing_tool():
    from mcp.server.fastmcp import FastMCP

    with pytest.raises(RuntimeError, match="unknown tools"):
        build_core_mcp(FastMCP("empty"))


@pytest.mark.asyncio
async def test_core_route_requires_auth(client):
    response = await client.post("/mcp/core", json={})
    assert response.status_code == 401
    assert "www-authenticate" in response.headers


@pytest.mark.asyncio
async def test_protected_resource_metadata_echoes_core_path(client):
    legacy = (
        await client.get("/.well-known/oauth-protected-resource/mcp")
    ).json()
    core = (
        await client.get("/.well-known/oauth-protected-resource/mcp/core")
    ).json()
    assert legacy["resource"].endswith("/mcp")  # claude.ai-verified shape
    assert core["resource"].endswith("/mcp/core")
    assert core["authorization_servers"] == legacy["authorization_servers"]
