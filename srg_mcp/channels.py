from urllib.parse import quote

from srg_mcp import _raw
from srg_mcp._app import mcp
from srg_mcp._client import get_client
from mcp.types import ToolAnnotations


def _hub_profile_id(channel_id: str, workspace_id: str) -> str:
    """Id of the hub profile that owns ``channel_id``.

    The archive/restore endpoints need it (without it they answer a bare 400,
    SRGDEV-856), but GET /api/v2/channels/{id} only carries the hub's user
    name, so the hub is looked up by that name. Works for archived channels.
    """
    channel = _raw.call(workspace_id, "GET", f"/api/v2/channels/{channel_id}") or {}
    user_name = channel.get("hubProfileUserName")
    hub = (
        _raw.call(
            workspace_id,
            "GET",
            f"/api/v1/hub-profiles/username/{quote(user_name, safe='')}",
        )
        if user_name
        else None
    ) or {}
    hub_profile_id = hub.get("id")
    if not hub_profile_id:
        raise ValueError(
            f"Could not find the hub profile of channel {channel_id}; "
            "re-check the channel id with list_channels."
        )
    return hub_profile_id


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

    A new channel starts with one category, "New Content"; add more with
    create_category.
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
        title="Rename channel",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def rename_channel(channel_id: str, name: str, workspace_id: str) -> str:
    """Rename a channel. ONLY the name changes: its categories (order and
    archive state), privacy and everything else keep their values.

    name: the new name, 1-50 characters, no `/` or `\\`, unique within the
        hub (a taken name fails with 409).
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    _raw.call(
        workspace_id, "PATCH", f"/api/v1/channels/{channel_id}", json={"name": name}
    )
    return "renamed"


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
    return _archive_channel(channel_id, workspace_id)


def _archive_channel(channel_id: str, workspace_id: str) -> dict | None:
    return _raw.call(
        workspace_id,
        "POST",
        f"/api/v1/channels/{channel_id}/archive",
        params={"hubProfileId": _hub_profile_id(channel_id, workspace_id)},
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Restore channel",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def restore_channel(channel_id: str, workspace_id: str) -> str:
    """Restore a previously archived channel.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    _raw.call(
        workspace_id,
        "POST",
        f"/api/v1/channels/{channel_id}/restore",
        params={"hubProfileId": _hub_profile_id(channel_id, workspace_id)},
    )
    return "restored"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Permanently delete channel",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def delete_channel(channel_id: str, workspace_id: str, archive_first: bool = False) -> str:
    """PERMANENTLY delete a channel with all its categories. Cannot be undone.

    The contents in it are NOT deleted: they only lose their place in this
    channel and stay in the hub, in Drive and in any other channel. A content
    placed nowhere else shows up in get_brand_index as not in any category.
    Two ways, same result as the app:
    - Two steps (safer): archive_channel first, check, then call this. Only an
      archived channel is deleted; a live one fails with 409 and is kept.
    - One step: archive_first=True archives and then deletes in this call
      (for a channel the user clearly asked to remove for good).
    Confirm the channel with the user before calling. Needs the hub owner or
    admin rights (the same as archive). The channel's name and link are freed.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    if archive_first:
        _archive_channel(channel_id, workspace_id)
    _raw.call(workspace_id, "DELETE", f"/api/v1/channels/{channel_id}")
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
        title="Rename category",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def rename_category(
    channel_id: str,
    category_id: str,
    name: str,
    workspace_id: str,
) -> str:
    """Rename a category. ONLY the name changes: its contents and their order,
    pin, notifications, display options and archive state keep their values.

    name: the new name, 1-50 characters, unique within the channel (archived
        categories count too; a taken name fails with 409). Emoji are fine.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Use this instead of creating a new category and moving the contents.
    """
    _raw.call(
        workspace_id,
        "PATCH",
        f"/api/v1/channels/{channel_id}/categories/{category_id}",
        json={"name": name},
    )
    return "renamed"


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
    return _archive_category(channel_id, category_id, workspace_id)


def _archive_category(channel_id: str, category_id: str, workspace_id: str) -> dict | None:
    # The only one of the four that reads hubProfileId from a JSON body; the
    # other archive/restore endpoints take it as a query parameter.
    return _raw.call(
        workspace_id,
        "POST",
        f"/api/v1/channels/{channel_id}/{category_id}/archive",
        json={"hubProfileId": _hub_profile_id(channel_id, workspace_id)},
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Restore category",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def restore_category(
    channel_id: str,
    category_id: str,
    workspace_id: str,
) -> str:
    """Restore a previously archived category inside a channel.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    _raw.call(
        workspace_id,
        "POST",
        f"/api/v1/channels/{channel_id}/{category_id}/restore",
        params={"hubProfileId": _hub_profile_id(channel_id, workspace_id)},
    )
    return "restored"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Permanently delete category",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def delete_category(
    channel_id: str,
    category_id: str,
    workspace_id: str,
    archive_first: bool = False,
) -> str:
    """PERMANENTLY delete a category from its channel. Cannot be undone.

    The contents in it are NOT deleted: they only lose their place in this
    category and stay in the hub, in Drive and in any other category. A content
    placed nowhere else shows up in get_brand_index as not in any category.
    Two ways, same result as the app:
    - Two steps (safer): archive_category first, check, then call this. Only an
      archived category is deleted; a live one fails with 409 and is kept.
    - One step: archive_first=True archives and then deletes in this call.
    Confirm the category with the user before calling. Needs the hub owner or
    admin rights. To take ONE content out of a category, use
    remove_content_from_categories instead.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    if archive_first:
        _archive_category(channel_id, category_id, workspace_id)
    _raw.call(
        workspace_id, "DELETE", f"/api/v1/channels/{channel_id}/categories/{category_id}"
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
