from srg_mcp._app import mcp
from srg_mcp._client import get_client
from mcp.types import ToolAnnotations


@mcp.tool(
    annotations=ToolAnnotations(
        title="List channels",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_channels(
    hub_profile_id: str,
    workspace_id: str,
    include_archived: bool = False,
) -> list[dict]:
    """List all channels for a hub profile.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return [
        c.model_dump(mode="json")
        for c in get_client().channels.list(
            hub_profile_id,
            include_archived=include_archived,
            workspace_id=workspace_id,
        )
    ]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get channel",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_channel(channel_id: str, workspace_id: str) -> dict:
    """Get full channel details by ID (includes categories and heading content).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return (
        get_client()
        .channels.get(channel_id, workspace_id=workspace_id)
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get channel by name",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_channel_by_name(
    hub_profile_username: str,
    channel_name: str,
    workspace_id: str,
) -> dict:
    """Get channel details by hub profile username slug and channel name slug.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return (
        get_client()
        .channels.get_by_name(
            hub_profile_username, channel_name, workspace_id=workspace_id
        )
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create channel",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_channel(
    name: str,
    hub_profile_id: str,
    workspace_id: str,
    privacy: str = "Private",
) -> str:
    """Create a new channel in a hub profile. Returns the new channel ID.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    privacy: "Private" (default) or "Public"
    """
    return get_client().channels.create(
        name=name,
        hub_profile_id=hub_profile_id,
        privacy=privacy,  # type: ignore[arg-type]
        workspace_id=workspace_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update channel",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_channel(
    channel_id: str,
    hub_profile_id: str,
    name: str,
    workspace_id: str,
    privacy: str | None = None,
    categories: list[dict] | None = None,
) -> dict | None:
    """Update a channel's name, privacy, and category order.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    privacy: "Public" or "Private"
    categories: list of {"id": "...", "order": 0} to reorder categories
    """
    from srg.schemas.channel import CategoryToReorder

    cat_objs = (
        [CategoryToReorder(id=c["id"], order=c.get("order")) for c in categories]
        if categories
        else None
    )
    return get_client().channels.update(
        channel_id=channel_id,
        hub_profile_id=hub_profile_id,
        name=name,
        privacy=privacy,  # type: ignore[arg-type]
        categories=cat_objs,
        workspace_id=workspace_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Archive channel",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def archive_channel(channel_id: str, workspace_id: str) -> dict | None:
    """Archive a channel (hidden from members, content preserved).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().channels.archive(channel_id, workspace_id=workspace_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete channel",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_channel(channel_id: str, workspace_id: str) -> str:
    """Permanently delete a channel and all its categories/sections. Irreversible.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    get_client().channels.delete(channel_id, workspace_id=workspace_id)
    return "deleted"


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create category",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_category(
    channel_id: str,
    name: str,
    workspace_id: str,
    is_pinned: bool = False,
    notifications_enabled: bool = True,
    view_type: str | None = None,
    progression_enabled: bool = False,
    cover_show: bool = True,
    expandable: bool = True,
    sections: list[dict] | None = None,
) -> str:
    """Create a new category inside a channel. Returns the new category ID.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    view_type: display view type (e.g. "Grid", "List")
    progression_enabled: track user completion progress
    cover_show: show cover images in this category
    expandable: allow the category to be collapsed
    sections: list of {"name": "...", "type": "...", "reference_ids": [...]} for initial sections
    """
    from srg.schemas.channel import (
        ChannelCategoryOptionsUpsert,
        CoverOptionsUpsert,
        ProgressionOptionsUpsert,
        SectionBaseCreate,
        ViewOptionsUpsert,
    )

    opts = ChannelCategoryOptionsUpsert(
        view=ViewOptionsUpsert(type=view_type),
        progression=ProgressionOptionsUpsert(enabled=progression_enabled),
        cover=CoverOptionsUpsert(show=cover_show),
        expandable=expandable,
    )
    sec_objs = (
        [
            SectionBaseCreate.model_validate(
                {
                    "$type": s.get("type", "Default"),
                    "name": s["name"],
                    "referenceIds": s.get("reference_ids", []),
                }
            )
            for s in sections
        ]
        if sections
        else None
    )
    return get_client().channels.create_category(
        channel_id,
        name=name,
        is_pinned=is_pinned,
        notifications_enabled=notifications_enabled,
        options=opts,
        sections=sec_objs,
        workspace_id=workspace_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update category",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_category(
    channel_id: str,
    category_id: str,
    name: str,
    workspace_id: str,
    is_pinned: bool = False,
    notifications_enabled: bool = True,
    view_type: str | None = None,
    progression_enabled: bool = False,
    cover_show: bool = True,
    expandable: bool = True,
) -> dict | None:
    """Update a category's name, pin status, notification settings, and display options.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    view_type: display view type (e.g. "Grid", "List")
    progression_enabled: track user completion progress
    cover_show: show cover images in this category
    expandable: allow the category to be collapsed
    """
    from srg.schemas.channel import (
        ChannelCategoryOptionsUpsert,
        CoverOptionsUpsert,
        ProgressionOptionsUpsert,
        ViewOptionsUpsert,
    )

    opts = ChannelCategoryOptionsUpsert(
        view=ViewOptionsUpsert(type=view_type),
        progression=ProgressionOptionsUpsert(enabled=progression_enabled),
        cover=CoverOptionsUpsert(show=cover_show),
        expandable=expandable,
    )
    return get_client().channels.update_category(
        channel_id,
        category_id,
        name=name,
        is_pinned=is_pinned,
        notifications_enabled=notifications_enabled,
        options=opts,
        workspace_id=workspace_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Archive category",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def archive_category(
    channel_id: str,
    category_id: str,
    workspace_id: str,
) -> dict | None:
    """Archive a category inside a channel.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().channels.archive_category(
        channel_id, category_id, workspace_id=workspace_id
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete category",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_category(
    channel_id: str,
    category_id: str,
    workspace_id: str,
) -> str:
    """Permanently delete a category from a channel. Irreversible.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    get_client().channels.delete_category(
        channel_id, category_id, workspace_id=workspace_id
    )
    return "deleted"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get category references",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_category_references(
    channel_id: str,
    category_id: str,
    workspace_id: str,
    page_size: int = 20,
    cursor: str | None = None,
) -> dict:
    """List content references in a category with cursor-based pagination.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns items and a cursor for the next page (null if no more pages).
    """
    page = get_client().channels.get_category_references(
        channel_id,
        category_id,
        page_size=page_size,
        cursor=cursor,
        workspace_id=workspace_id,
    )
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "cursor": page.cursor,
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get category by slugs",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_category_by_slugs(
    hub_profile_username: str,
    channel_name: str,
    category_name: str,
    workspace_id: str,
) -> dict:
    """Get category details by hub profile username, channel name, and category name slugs.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return (
        get_client()
        .channels.get_category_v2(
            hub_profile_username,
            channel_name,
            category_name,
            workspace_id=workspace_id,
        )
        .model_dump(mode="json")
    )


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create section",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_section(
    channel_id: str,
    category_id: str,
    name: str,
    workspace_id: str,
) -> str:
    """Create a new section inside a channel category. Returns the new section ID.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().channels.create_section(
        channel_id, category_id, name=name, workspace_id=workspace_id
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update section",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_section(
    channel_id: str,
    category_id: str,
    section_id: str,
    name: str,
    workspace_id: str,
) -> dict | None:
    """Rename a section inside a channel category.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().channels.update_section(
        channel_id, category_id, section_id, name=name, workspace_id=workspace_id
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete section",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_section(
    channel_id: str,
    category_id: str,
    section_id: str,
    workspace_id: str,
) -> str:
    """Permanently delete a section from a channel category. Irreversible.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    get_client().channels.delete_section(
        channel_id, category_id, section_id, workspace_id=workspace_id
    )
    return "deleted"


# ---------------------------------------------------------------------------
# Content placement
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="Add content to category",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def add_content_to_category(
    channel_id: str,
    category_id: str,
    section_id: str,
    content_ids: list[str],
    workspace_id: str,
) -> dict | None:
    """Add one or more content items to a section inside a channel category.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().channels.add_content_to_category(
        channel_id,
        category_id,
        section_id,
        contents_ids=content_ids,
        workspace_id=workspace_id,
    )
