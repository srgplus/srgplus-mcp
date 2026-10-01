from typing import Any
from urllib.parse import quote

from srg_mcp import _raw
from srg_mcp._app import mcp
from srg_mcp._category_options import settings_of, with_changes
from srg_mcp._client import get_client
from mcp.types import ToolAnnotations

_LINK = "https://srgplus.com/{user}/channels/{slug}"
_PRIVACY = {"public": "Public", "private": "Private"}


def _hub_profile_id(channel_id: str, workspace_id: str, channel: dict | None = None) -> str:
    """Id of the hub profile that owns ``channel_id``.

    The archive/restore endpoints need it (without it they answer a bare 400,
    SRGDEV-856), but GET /api/v2/channels/{id} only carries the hub's user
    name, so the hub is looked up by that name. Works for archived channels.
    ``channel``: that GET's answer when the caller already has it.
    """
    if channel is None:
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


def _channel(channel_id: str, workspace_id: str) -> dict:
    channel = _raw.call(workspace_id, "GET", f"/api/v2/channels/{channel_id}")
    if not isinstance(channel, dict) or not channel.get("id"):
        raise ValueError(f"Channel {channel_id} was not found; list_channels gives the ids.")
    return channel


def _category(channel: dict, category_id: str) -> dict:
    """The channel's category with this id, or with this exact name when only one has it."""
    categories = channel.get("categories") or []
    wanted = str(category_id).strip()
    for category in categories:
        if str(category.get("id", "")).lower() == wanted.lower():
            return category
    named = [c for c in categories if str(c.get("name", "")).strip().casefold() == wanted.casefold()]
    if len(named) == 1:
        return named[0]
    names = ", ".join(f"{c.get('name')!r} ({c.get('id')})" for c in categories)
    if named:
        raise ValueError(f"Several categories are called {wanted!r}; pass the id. Its categories: {names}.")
    raise ValueError(
        f"Category {category_id} is not in channel {channel.get('name')!r}. Its categories: {names or 'none'}."
    )


def channel_link(channel: dict) -> str | None:
    """srgplus.com/<user>/channels/<slug>; a channel with no slug yet is reached by its name
    (the apps link it the same way)."""
    user = channel.get("hubProfileUserName")
    key = channel.get("slug") or channel.get("name")
    return _LINK.format(user=user, slug=quote(str(key), safe="")) if user and key else None


def icon_out(icon: dict | None) -> dict | None:
    """A channel icon as the tools take it (None: the plain "#")."""
    if not icon:
        return None
    out: dict[str, Any] = {"kind": icon.get("kind"), "color": icon.get("color")}
    for key, name in (("symbol", "symbol"), ("emoji", "emoji"), ("assetId", "photo_asset_id"), ("url", "url")):
        if icon.get(key):
            out[name] = icon[key]
    return out


def write_category(
    channel_id: str,
    category: dict,
    workspace_id: str,
    *,
    name: str | None = None,
    pinned: bool | None = None,
    notifications: bool | None = None,
    email: bool | None = None,
    options: dict | None = None,
) -> dict:
    """PUT one category with every field as read, except the given ones. Returns what was sent.

    The endpoint replaces the whole category (an omitted isPinned unpins it, options reset),
    so every field goes back as read.
    """
    if pinned and category.get("isArchived"):
        # The backend unpins the channel's other categories first, so pinning an archived
        # one would leave the channel with no visible pinned category.
        raise ValueError(
            f"Category {category.get('name')!r} is archived; restore it first (restore_category), then pin it."
        )
    body: dict[str, Any] = {
        "name": category.get("name") if name is None else name,
        "isPinned": bool(category.get("isPinned")) if pinned is None else bool(pinned),
    }
    # A flag the read did not carry is left out rather than guessed: the backend then
    # keeps the stored email flag (and uses its default for notifications).
    for key, value in (("notificationsEnabled", notifications), ("emailEnabled", email)):
        if value is not None:
            body[key] = bool(value)
        elif key in category:
            body[key] = bool(category[key])
    body["options"] = options if options is not None else with_changes(category.get("options"))
    _raw.call(
        workspace_id, "PUT", f"/api/v1/channels/{channel_id}/categories/{category['id']}", json=body
    )
    return body


def settings_after(category: dict, sent: dict) -> dict:
    """A category's id, name and settings as written by write_category."""
    return {
        "category_id": category["id"],
        "name": sent["name"],
        **settings_of(
            {
                **category,
                "isPinned": sent["isPinned"],
                "notificationsEnabled": sent.get("notificationsEnabled", category.get("notificationsEnabled")),
                "emailEnabled": sent.get("emailEnabled", category.get("emailEnabled")),
                "options": sent["options"],
            }
        ),
    }


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
    """List all channels for a hub profile, in their order in the apps.

    Each channel has its id, name, categories, privacy, is_archived, its link (slug and the
    full srgplus.com link) and its icon (None: the plain "#").
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    from srg.schemas.channel import Channel

    rows = _raw.call(
        workspace_id,
        "GET",
        f"/api/v1/channels/{hub_profile_id}",
        params={"includeArchived": str(include_archived).lower()},
    ) or []
    return [
        {
            **Channel.model_validate(row).model_dump(mode="json"),
            "privacy": row.get("privacy"),
            "is_archived": bool(row.get("isArchived")),
            "slug": row.get("slug"),
            "link": channel_link(row),
            "icon": icon_out(row.get("icon")),
        }
        for row in rows
        if isinstance(row, dict)
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

    Also the channel's link (slug and the full srgplus.com link), its icon (None: the plain
    "#"), and per category its `settings` in the words update_category_settings takes
    (pinned, view grid/list/scroll, card_size, open_view, cover_ratio, notifications, ...).
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    from srg.schemas.channel import HubProfileChannelV2

    raw = _channel(channel_id, workspace_id)
    out = HubProfileChannelV2.model_validate(raw).model_dump(mode="json")
    settings = {str(c.get("id")): settings_of(c) for c in raw.get("categories") or []}
    for category in out.get("categories") or []:
        category["settings"] = settings.get(str(category.get("id")))
    return {
        **out,
        "is_archived": bool(raw.get("isArchived")),
        "slug": raw.get("slug"),
        "link": channel_link(raw),
        "icon": icon_out(raw.get("icon")),
    }


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
    workspace_id: str,
    name: str | None = None,
    privacy: str | None = None,
    categories: list[Any] | None = None,
) -> dict | None:
    """Update a channel's name, privacy and category order in one call.

    Prefer the one-thing tools: rename_channel (name), reorder_categories (order),
    set_channel_icon / set_channel_slug (look). Only what you pass changes: the name,
    privacy and category order keep their stored values when left out, and every
    category keeps its archive state.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    privacy: "Public" or "Private"
    categories: the categories in the new order: ids, or {"id": "...", "order": 0} objects
        (sorted by order). Listed ones come first, the others keep their order after them.
    """
    if privacy is not None:
        privacy = _PRIVACY.get(str(privacy).strip().lower())
        if privacy is None:
            raise ValueError('privacy must be "Public" or "Private".')
    channel = _channel(channel_id, workspace_id)
    stored = channel.get("categories") or []
    active = [c for c in stored if not c.get("isArchived")]
    archived = [c for c in stored if c.get("isArchived")]
    ids = {str(c["id"]).lower(): c["id"] for c in active}
    if categories:
        entries = [c if isinstance(c, dict) else {"id": c} for c in categories]
        if any("order" in e and e["order"] is not None for e in entries):
            entries = sorted(entries, key=lambda e: (e.get("order") is None, e.get("order") or 0))
        listed = [str(e.get("id") or e.get("categoryId") or "").strip().lower() for e in entries]
        unknown = [i for i in listed if i not in ids]
        if unknown:
            raise ValueError(
                f"Not active categories of this channel: {', '.join(unknown)}. get_channel lists them."
            )
        wanted = list(dict.fromkeys(ids[i] for i in listed))
    else:
        wanted = []
    order = wanted + [c["id"] for c in active if c["id"] not in wanted]
    body: dict[str, Any] = {
        "channelId": channel["id"],
        "hubProfileId": hub_profile_id,
        # Unchanged, the backend keeps it byte for byte (and the link with it).
        "name": channel.get("name") if name is None else name,
        "categories": [{"categoryId": i, "isArchived": False} for i in order]
        + [{"categoryId": c["id"], "isArchived": True} for c in archived],
    }
    if privacy is not None:
        body["privacy"] = privacy
    return _raw.call(workspace_id, "PUT", "/api/v1/channels", json=body)


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
    archive state), privacy, icon and everything else keep their values.

    name: the new name, 1-50 characters, no `/` or `\\`, unique within the
        hub (a taken name fails with 409). Emoji are fine.
    The channel's link (slug) follows the new name unless it was set by hand
    (set_channel_slug); the old link keeps working.
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
    Confirm the channel with the user before calling. Only the hub owner or
    an admin can delete (editors can archive, not delete); others get 403.
    The channel's name and link are freed.
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
    cover_show: bool | None = None,
    expandable: bool = True,
    sections: list[dict] | None = None,
    card_size: str | None = None,
    open_view: str | None = None,
    cover_ratio: str | None = None,
) -> str:
    """Create a new category inside a channel. Returns the new category ID.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    is_pinned: pin it to the top of the channel (the channel's other pinned category is unpinned)
    view_type: how it shows on the channel page: "grid", "list" or "scroll" (default: scroll,
        a horizontal row of cards)
    card_size: "large" (default) or "small" cards, for the grid and list views
    open_view: how it shows when opened (See all): "grid" (default) or "list"
    cover_ratio: card cover shape, width:height: "16:9", "9:16", "3:2", "2:3", "5:4", "4:5",
        "square" or "original" (default)
    progression_enabled: track user completion progress
    expandable: allow the category to be opened (enlarged)
    cover_show: no longer used (covers always show); ignored
    sections: list of {"name": "...", "type": "...", "reference_ids": [...]} for initial sections
    Change any of these later with update_category_settings.
    """
    options = with_changes(
        None,
        view=view_type or None,
        card_size=card_size,
        open_view=open_view,
        cover_ratio=cover_ratio,
        progression=bool(progression_enabled),
        expandable=bool(expandable),
    )
    body = {
        "name": name,
        "isPinned": bool(is_pinned),
        "notificationsEnabled": bool(notifications_enabled),
        "options": options,
        "sections": [
            {
                "$type": s.get("type", "Default"),
                "name": s["name"],
                "referenceIds": s.get("reference_ids", []),
            }
            for s in sections or []
        ],
    }
    data = _raw.call(workspace_id, "POST", f"/api/v1/channels/{channel_id}/categories", json=body)
    if isinstance(data, dict):
        return data.get("id", "")
    return str(data or "")


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
    workspace_id: str,
    name: str | None = None,
    is_pinned: bool | None = None,
    notifications_enabled: bool | None = None,
    view_type: str | None = None,
    progression_enabled: bool | None = None,
    cover_show: bool | None = None,
    expandable: bool | None = None,
) -> dict:
    """Update a category's name, pin status, notifications and display options.

    Prefer update_category_settings (any setting, nothing else changes) and rename_category.
    Only what you pass changes; everything left out keeps its stored value.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    view_type: "grid", "list" or "scroll"
    progression_enabled: track user completion progress
    expandable: allow the category to be opened (enlarged)
    cover_show: no longer used (covers always show); ignored
    Returns the category's settings after the change.
    """
    category = _category(_channel(channel_id, workspace_id), category_id)
    options = with_changes(
        category.get("options"),
        view=view_type or None,
        progression=progression_enabled,
        expandable=expandable,
    )
    sent = write_category(
        channel_id,
        category,
        workspace_id,
        name=name,
        pinned=is_pinned,
        notifications=notifications_enabled,
        options=options,
    )
    return settings_after(category, sent)


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
    Confirm the category with the user before calling. Only the hub owner or
    an admin can delete (others get 403). To take ONE content out of a category, use
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
