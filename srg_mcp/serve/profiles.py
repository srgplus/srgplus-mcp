"""Tool profiles for the hosted server.

The full server exposes every tool (100+). That is the right surface for
power integrations, but too wide for everyday agent work: every client pays
for every tool schema on every session, and the wide surface mixes daily
content work with destructive admin operations. The CORE profile is the
curated daily-work subset in ``CORE_TOOL_NAMES`` (``/health`` reports its
size as ``core_tool_count``), served at ``/mcp/core`` and on ``POST /``, the
public connector address. The full set stays at ``/mcp``; existing consumers
are untouched.

CORE selection: find things (workspaces → hub profiles → channels →
content), search, read both content variants (v2 covers private-channel
memberships), create/update content, upload an asset, attach to categories,
remove a content from chosen categories only, fill a content's Featured Assets / Featured Content (named sections), read and
edit a hub profile (bio, links, avatar, cover) with PATCH semantics, create a
new hub with its channels and categories, rename a channel or category
(PATCH: only the name changes), the brand context (index + memory
page), reversible archive/restore, Drive file clean-up (archive → restore
or permanent delete, the same as the app's Drive bin), and the permanent
delete of an archived channel or category (its contents stay, SRGDEV-921), and
the ready-made preset covers (list + apply, SRGDEV-940).
Excluded on purpose: user/permission management, hard deletes of hubs and
contents, moves, the
low-level collection subcontent tools, workspace actions, the full-replace
``update_channel`` / ``update_category``, and the deprecated ``create_*_asset``
registrars.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("srgplus-mcp-serve.profiles")

CORE_TOOL_NAMES: tuple[str, ...] = (
    # Self-help — the full how-to guide ships with the connector (no separate
    # skill install needed); agents pull it on demand.
    "get_srgplus_guide",
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
    # Take a content out of ONE category, other placements stay (no reset).
    "remove_content_from_categories",
    # Featured Assets / Featured Content of a content item (the "More" menu),
    # with named sections such as "Version 1" (SRGDEV-756)
    "set_featured_assets",
    "set_featured_contents",
    "list_featured_sections",
    "reorder_featured_sections",
    "delete_featured_section",
    # Hub profile (brand page): read + PATCH edit, avatar/cover from Drive (SRGDEV-798)
    "get_hub_profile",
    "update_hub_profile",
    "set_hub_avatar",
    "set_hub_cover",
    # Structure: a new hub, then its channels, then their categories (SRGDEV-850).
    # CREATE ONLY. update_channel / update_category stay on the full /mcp until
    # they keep the fields a caller leaves out: the backend PUT replaces the
    # whole object (a category's isPinned / notificationsEnabled reset to the
    # defaults; a channel's categories list must name every category, archived
    # ones included).
    "create_hub_profile",
    "create_channel",
    "create_category",
    # Rename only (PATCH, SRGDEV-827): the name changes, nothing else resets.
    "rename_channel",
    "rename_category",
    # Media from the user's computer (no base64) + covers + Drive (SRGDEV-741)
    "create_upload",
    "complete_upload",
    "set_cover",
    "set_covers",
    # Ready-made gradient covers, no upload (SRGDEV-940)
    "list_cover_presets",
    "set_cover_preset",
    "list_drive_files",
    "get_asset",
    # Drive clean-up, same flow as the app's bin: archive (reversible) →
    # restore, or permanent delete (only of archived files, or archive_first).
    "archive_drive_files",
    "restore_drive_files",
    "delete_drive_files",
    # Brand context: the whole brand in one call + the brand memory page (SRGDEV-824/825)
    "get_brand_index",
    "get_brand_memory",
    "append_brand_memory",
    # Lifecycle — archive / restore (reversible). Hard delete of contents and
    # hubs stays OUT of the agent connector (a hub delete is app-only, JWT).
    # Channels and categories can be deleted for good once archived, same as
    # the app and the Drive bin (SRGDEV-921): only archived ones, or
    # archive_first; the contents inside are never deleted, only unlinked.
    "archive_content",
    "restore_content",
    "archive_channel",
    "restore_channel",
    "delete_channel",
    "archive_category",
    "restore_category",
    "delete_category",
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
    # clients get the SRG+ pitfalls too (the instructions string is shared),
    # and the same connector logo.
    core = FastMCP(
        "SRG+ Core",
        instructions=full_mcp.instructions,
        website_url=full_mcp._mcp_server.website_url,
        icons=full_mcp._mcp_server.icons,
    )
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
