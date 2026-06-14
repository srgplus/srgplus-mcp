"""Tool profiles for the hosted server.

The full server exposes ~98 tools. That is the right surface for power
integrations, but too wide for everyday agent work: every client pays for
every tool schema on every session, and the wide surface mixes daily content
work with destructive admin operations. The CORE profile is the curated
~10-tool surface for daily content work, served at ``/mcp/core``. The full
set stays at ``/mcp`` — existing consumers are untouched.

CORE selection: find things (workspaces → hub profiles → channels →
content), search, read both content variants (v2 covers private-channel
memberships), create/update content, upload an asset, attach to categories.
Excluded on purpose: user/permission management, deletes, archives, moves,
sections/subcontent, workspace actions, and the deprecated
``create_*_asset`` registrars.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("srgplus-mcp-serve.profiles")

CORE_TOOL_NAMES: tuple[str, ...] = (
    # Read / navigate
    "list_workspaces",
    "list_hub_profiles",
    "list_channels",
    "get_channel",
    "search_contents",
    "get_content",
    "get_content_v2",
    # Create / edit content
    "create_content",
    "update_content",
    "upload_asset",
    "add_content_to_categories",
    # Lifecycle — ARCHIVE ONLY in the core profile (reversible). Hard delete is
    # intentionally kept OUT of the agent connector for now (manual-only in the
    # app); the delete_* tools still exist on the full /mcp surface for admin use.
    "archive_content",
    "restore_content",
    "archive_channel",
    "restore_channel",
    "archive_category",
    "restore_category",
    "archive_hub_profile",
    "restore_hub_profile",
)


def build_core_mcp(full_mcp: FastMCP) -> FastMCP:
    """Create the core-profile FastMCP sharing tool objects with the full one.

    Sharing the registered ``Tool`` objects (rather than re-decorating their
    functions) guarantees byte-identical schemas on both surfaces and keeps
    in-place changes — e.g. the tool error wrapper from ``_tool_errors`` —
    applied to both. Relies on the same private FastMCP internals as
    ``serve/main.py``; the ``mcp`` dependency is pinned ``<2.0`` for that.

    Raises at startup (not at first request) when a core name is missing, so
    a tool rename that forgets this list fails loudly in CI/deploy.
    """
    # Carry the same server-level guidance onto the core surface so /mcp/core
    # clients get the SRG+ pitfalls too (the instructions string is shared).
    core = FastMCP("SRG+ Core", instructions=full_mcp.instructions)
    full_tools = full_mcp._tool_manager._tools
    missing = [name for name in CORE_TOOL_NAMES if name not in full_tools]
    if missing:
        raise RuntimeError(
            f"core profile references unknown tools: {missing} — "
            "did a tool rename land without updating CORE_TOOL_NAMES?"
        )
    for name in CORE_TOOL_NAMES:
        core._tool_manager._tools[name] = full_tools[name]
    logger.info("core profile ready: %d tools", len(CORE_TOOL_NAMES))
    return core
