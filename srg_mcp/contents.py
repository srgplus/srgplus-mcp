from srg_mcp._app import mcp
from srg_mcp._client import get_client
from mcp.types import ToolAnnotations


@mcp.tool(
    annotations=ToolAnnotations(
        title="List contents",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_contents(
    hub_profile_id: str,
    workspace_id: str,
    page_size: int = 50,
    cursor: str | None = None,
    only_archived: bool = False,
    types: list[str] | None = None,
    exclude_categories: list[str] | None = None,
    exclude_collections: list[str] | None = None,
    exclude_contents: list[str] | None = None,
) -> dict:
    """List content items in a hub profile with cursor-based pagination.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    types: ["Content"], ["Collection"], or None for both (default)
    Returns {"items": [...], "cursor": "..." | null}
    """
    page = get_client().contents.filter(
        hub_profile_id,
        page_size=page_size,
        cursor=cursor,
        only_archived=only_archived,
        types=types,
        exclude_categories=exclude_categories,
        exclude_collections=exclude_collections,
        exclude_contents=exclude_contents,
        workspace_id=workspace_id,
    )
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "cursor": page.cursor,
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Search contents",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def search_contents(
    hub_profile_id: str,
    search: str,
    workspace_id: str,
    only_archived: bool = False,
    types: list[str] | None = None,
    exclude_categories: list[str] | None = None,
    exclude_collections: list[str] | None = None,
    exclude_contents: list[str] | None = None,
) -> list[dict]:
    """Search content items in a hub profile by keyword.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    types: ["Content"], ["Collection"], or None for both (default)
    """
    items = get_client().contents.search(
        hub_profile_id,
        search=search,
        only_archived=only_archived,
        types=types,
        exclude_categories=exclude_categories,
        exclude_collections=exclude_collections,
        exclude_contents=exclude_contents,
        workspace_id=workspace_id,
    )
    return [item.model_dump(mode="json") for item in items]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get content",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_content(
    content_id: str,
    workspace_id: str,
    hub_profile_id: str | None = None,
) -> dict:
    """Get content item details by ID (v1 schema).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    hub_profile_id: optional, used to resolve access context
    """
    return (
        get_client()
        .contents.get(
            content_id, hub_profile_id=hub_profile_id, workspace_id=workspace_id
        )
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get content (v2)",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_content_v2(content_id: str, workspace_id: str) -> dict:
    """Get content item by ID (v2 schema).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Includes main asset, user progression, and extended metadata.
    """
    return (
        get_client()
        .contents.get_v2(content_id, workspace_id=workspace_id)
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create content",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_content(
    name: str,
    hub_profile_id: str,
    workspace_id: str,
    privacy: str = "Preview",
    details: str | None = None,
    url: str | None = None,
    main_asset_id: str | None = None,
    channels: list[str] | None = None,
    cover_image: str | None = None,
    context: list[dict] | None = None,
    categories: list[dict] | None = None,
) -> dict:
    """Create a new content item in a hub profile.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    privacy: "Preview" (default), "Private", or "Public"
    channels: list of channel IDs to place the content in
    main_asset_id: ID of the primary playable asset
    url: optional external URL to associate with the content
    cover_image: local path or http(s):// URL of the cover image (auto-upload)
    categories: category assignment objects

    context: the body — an ordered list of widget objects. Each widget MUST
    carry a "$type" discriminator (literal key, with the dollar sign). Keys are
    camelCase: the backend rejects snake_case for multi-word fields (assetId,
    hubProfileIds, referenceIds) as a silent 400, so never send asset_id etc.
    Shapes:
      • Text (markdown body):
        {"$type": "Text", "content": "<markdown, required>", "title": "<optional>"}
      • LinkList:
        {"$type": "LinkList", "title": "<optional>", "links": [
            {"$type": "CustomLink", "title": "<required, unique in list>", "url": "https://...", "extension": "<optional image ext>"},
            {"$type": "KnownLink",  "title": "<required>", "url": "https://..."}
        ]}
        (both link types use "title" + "url"; NOT "label"/"type". Max 20 links.)
      • Media: {"$type": "Media", "assetId": "<asset id, required>", "autoplay": false, "title": "<optional>"}
        (key is assetId — upload the file with upload_asset first to get the id)
      • HubProfile: {"$type": "HubProfile", "hubProfileIds": ["<hub id>", ...], "title": "<optional>"}
        (hubProfileIds is a REQUIRED array, even for a single hub)
      • ContentWidget: {"$type": "ContentWidget", "referenceType": "Content",
            "referenceIds": [{"$type": "Content", "id": "<content id>"}], "title": "<optional>"}
        (each reference is {"$type": "Content"|"Asset", "id": "..."}; referenceType matches the kind)
    A single bad widget rejects the WHOLE call with 400 (the error now names the
    rejected field). Widget title (when set) is 1-150 chars.
    """
    result = get_client().contents.create(
        name=name,
        hub_profile_id=hub_profile_id,
        privacy=privacy,  # type: ignore[arg-type]
        details=details,
        url=url,
        main_asset_id=main_asset_id,
        channels=channels,
        cover_image=cover_image,
        context=context,
        categories=categories,
        workspace_id=workspace_id,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update content",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_content(
    content_id: str,
    workspace_id: str,
    name: str | None = None,
    privacy: str | None = None,
    details: str | None = None,
    url: str | None = None,
    main_asset_id: str | None = None,
    hub_profile_id: str | None = None,
    channels: list[str] | None = None,
    cover_image: str | None = None,
    context: list[dict] | None = None,
    categories: list[dict] | None = None,
) -> dict:
    """Update a content item's metadata. Only provided fields are changed.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    privacy: "Preview", "Private", or "Public"
    channels: list of channel IDs (replaces existing placement)
    main_asset_id: ID of the primary playable asset
    url: external URL to associate with the content
    hub_profile_id: the owning hub profile. Optional — when omitted it is
        resolved automatically from the content, so you normally do not pass it.
    cover_image: local path or http(s):// URL of the cover image (auto-upload)
    categories: category assignment objects (REPLACES existing — to append,
        read the content first and send the full list back)

    context: the body — REPLACES the existing widget list. Same widget shapes
    as create_content, camelCase keys: "Text"{content}; "LinkList"{links:[{$type,
    title,url}]}; "Media"{assetId,autoplay}; "HubProfile"{hubProfileIds:[...]};
    "ContentWidget"{referenceType,referenceIds:[{$type,id}]}. To append to the
    current body, read it first (get_content_v2) and send the existing widgets
    plus the new ones.
    """
    # The PUT route needs the owning hub profile. Resolve it from the content
    # when the caller didn't pass it, so updates don't fail with a bare 400.
    if hub_profile_id is None:
        hub_profile_id = get_client().contents.get_v2(
            content_id, workspace_id=workspace_id
        ).hub_profile_id

    result = get_client().contents.update(
        content_id,
        name=name,
        privacy=privacy,  # type: ignore[arg-type]
        details=details,
        url=url,
        main_asset_id=main_asset_id,
        hub_profile_id=hub_profile_id,
        channels=channels,
        cover_image=cover_image,
        context=context,
        categories=categories,
        workspace_id=workspace_id,
    )
    return result.model_dump(mode="json")


def _post_content_lifecycle(content_id: str, workspace_id: str, action: str) -> None:
    """POST /api/v1/contents/{id}/{archive|restore}.

    Prefers the SDK method when the installed srgplus exposes it; falls back
    to the authenticated HTTP client so the tool works before the SDK bump.
    """
    contents = get_client().contents
    method = getattr(contents, action, None)
    if callable(method):
        method(content_id, workspace_id=workspace_id)
    else:  # pragma: no cover - exercised only on older SDK builds
        contents._get_http(workspace_id).post(f"/api/v1/contents/{content_id}/{action}")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Archive content",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def archive_content(content_id: str, workspace_id: str) -> str:
    """Archive a content item (hidden from listings, fully reversible).

    The platform has no hard delete for content — archiving is how you remove
    a content item from view; use restore_content to bring it back.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    _post_content_lifecycle(content_id, workspace_id, "archive")
    return "archived"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Restore content",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def restore_content(content_id: str, workspace_id: str) -> str:
    """Restore a previously archived content item.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    _post_content_lifecycle(content_id, workspace_id, "restore")
    return "restored"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Add content to categories",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def add_content_to_categories(
    content_id: str,
    channel_id: str,
    category_ids: list[str],
    workspace_id: str,
) -> str:
    """Add a content item to one or more channel categories.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    content_id:   ID of the content item
    channel_id:   ID of the channel
    category_ids: IDs of the categories inside that channel to add the content to
    """
    from srg.schemas.content import ContentChannelUpsert

    get_client().contents.add_to_categories(
        content_id,
        channels_categories=[
            ContentChannelUpsert(channel_id=channel_id, category_ids=category_ids)
        ],
        workspace_id=workspace_id,
    )
    return "added"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Remove content from categories",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def remove_content_from_categories(
    content_id: str,
    channel_id: str,
    category_ids: list[str],
    workspace_id: str,
) -> str:
    """Remove a content item from one or more channel categories.

    The content item itself is not deleted.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    content_id:   ID of the content item
    channel_id:   ID of the channel
    category_ids: IDs of the categories to remove the content from
    """
    from srg.schemas.content import ContentChannelUpsert

    get_client().contents.remove_from_categories(
        content_id,
        channels_categories=[
            ContentChannelUpsert(channel_id=channel_id, category_ids=category_ids)
        ],
        workspace_id=workspace_id,
    )
    return "removed"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Move content",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def move_content(
    content_id: str,
    channel_id: str,
    category_id: str,
    section_id: str,
    workspace_id: str,
) -> str:
    """Move a content item to a different category section within a channel.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    content_id:  ID of the content item to move
    channel_id:  ID of the channel containing the target category
    category_id: ID of the destination category
    section_id:  ID of the destination section within that category
    """
    get_client().contents.move(
        content_id,
        channel_id=channel_id,
        category_id=category_id,
        section_id=section_id,
        workspace_id=workspace_id,
    )
    return "moved"


# ---------------------------------------------------------------------------
# Content sections (for collections)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create content section",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_content_section(
    content_id: str,
    category_name: str,
    name: str,
    workspace_id: str,
) -> dict | None:
    """Create a section inside a collection content item's category.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    category_name: the name slug of the category (e.g. "week-1")
    """
    return get_client().contents.create_section(
        content_id, category_name, name=name, workspace_id=workspace_id
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update content section",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_content_section(
    content_id: str,
    category_name: str,
    section_id: str,
    name: str,
    workspace_id: str,
) -> dict | None:
    """Rename a section inside a collection content item's category.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().contents.update_section(
        content_id,
        category_name,
        section_id,
        name=name,
        workspace_id=workspace_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete content section",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_content_section(
    content_id: str,
    category_name: str,
    section_id: str,
    workspace_id: str,
) -> str:
    """Delete a section from a collection content item's category. Irreversible.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    get_client().contents.delete_section(
        content_id, category_name, section_id, workspace_id=workspace_id
    )
    return "deleted"


# ---------------------------------------------------------------------------
# Collection references — the sub-content that makes a content a Collection
#
# BACKGROUND
# A "Collection" is not a separate entity type — it is a regular Content item
# whose inner "Content" category contains at least one reference.  References
# are other Content items nested inside the collection, similar to subtopics,
# lessons, or chapters inside a course.  The server sets ContentType=Collection
# automatically once the first reference is added.
#
# STRUCTURE
#   Collection (Content item)
#   └── ContentCategory  (category_name = "Content")
#       ├── Section A  ← named group of references (e.g. "Chapter 1")
#       │   ├── reference → Content item
#       │   └── reference → Content item
#       └── Section B
#           └── reference → Content item
#
# TYPICAL WORKFLOW
#   1. create_content(...)              → creates the container (plain content)
#   2. create_content_section(...)      → adds a section to group the sub-items
#   3. add_subcontent(...)              → links existing content as sub-items
#      → the container is now a Collection
#   4. get_subcontent(...)              → lists the nested content (paginated)
#   5. move_subcontent(...)             → reorders a sub-item within the section
#   6. delete_subcontent(...)           → removes a sub-item (does not delete it)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="Add subcontent",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def add_subcontent(
    content_id: str,
    category_name: str,
    section_id: str,
    subcontent_ids: list[str],
    workspace_id: str,
) -> str:
    """Link existing content items as subcontent inside a collection section.

    Subcontent is the nested content that lives inside a Collection — think
    lessons inside a course, or chapters inside a module.  A Content item
    automatically becomes a Collection once it has at least one subcontent item.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    content_id:     ID of the collection (the parent content item)
    category_name:  "Content" for nested content items, "Asset" for nested assets
    section_id:     ID of the section to add the subcontent into
                    (create a section first with create_content_section if needed)
    subcontent_ids: list of content IDs to link as subcontent (one or more)
    """
    get_client().contents.add_subcontent(
        content_id,
        category_name,
        section_id,
        subcontent_ids=subcontent_ids,
        workspace_id=workspace_id,
    )
    return "added"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get subcontent",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_subcontent(
    content_id: str,
    category_name: str,
    workspace_id: str,
    page_size: int = 50,
    cursor: str | None = None,
    order: str = "Asc",
) -> dict:
    """List the subcontent items nested inside a collection, page by page.

    Returns the content items linked as subcontent inside the given collection's
    category.  Each item includes its id, name, cover, privacy, progression,
    and the section it belongs to.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    content_id:    ID of the collection (the parent content item)
    category_name: "Content" (nested content items) or "Asset" (nested assets)
    page_size:     items per page (default 50)
    cursor:        opaque cursor from a previous response; omit for first page
    order:         "Asc" (default) or "Desc"

    Returns {"items": [...], "cursor": "..." | null}
    """
    page = get_client().contents.get_subcontent(
        content_id,
        category_name,
        page_size=page_size,
        cursor=cursor,
        order=order,
        workspace_id=workspace_id,
    )
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "cursor": page.cursor,
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete subcontent",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_subcontent(
    content_id: str,
    category_name: str,
    section_id: str,
    subcontent_id: str,
    workspace_id: str,
) -> str:
    """Unlink a subcontent item from a collection section.

    Removes the link between the collection and the subcontent item.  The
    subcontent item itself is NOT deleted — it continues to exist as a
    standalone content item.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    content_id:    ID of the collection (the parent content item)
    category_name: "Content" or "Asset"
    section_id:    ID of the section that currently contains the subcontent item
    subcontent_id: ID of the subcontent item to unlink
    """
    get_client().contents.delete_subcontent(
        content_id,
        category_name,
        section_id,
        subcontent_id,
        workspace_id=workspace_id,
    )
    return "deleted"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Move subcontent",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def move_subcontent(
    content_id: str,
    category_name: str,
    section_id: str,
    subcontent_id: str,
    workspace_id: str,
    previous_subcontent_id: str | None = None,
) -> str:
    """Reorder a subcontent item within a collection section.

    Moves the item to the position immediately AFTER previous_subcontent_id.
    Pass previous_subcontent_id=None to move the item to the very first
    position in the section.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    content_id:             ID of the collection (the parent content item)
    category_name:          "Content" or "Asset"
    section_id:             ID of the section containing the subcontent item
    subcontent_id:          ID of the subcontent item to reorder
    previous_subcontent_id: ID of the item that should come directly before the
                            moved item; None places it first in the section
    """
    get_client().contents.move_subcontent(
        content_id,
        category_name,
        section_id,
        subcontent_id=subcontent_id,
        previous_subcontent_id=previous_subcontent_id,
        workspace_id=workspace_id,
    )
    return "moved"


# ---------------------------------------------------------------------------
# Progressions
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update content progression",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def patch_content_progression(
    content_id: str,
    status: str,
    workspace_id: str,
) -> dict:
    """Update the current user's progression status for a content item.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    status: "NotStarted", "Incomplete", or "Completed"
    """
    result = get_client().contents.patch_content_progression(
        content_id,
        status=status,  # type: ignore[arg-type]
        workspace_id=workspace_id,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update media progression",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def patch_media_progression(
    media_id: str,
    last_watched_time: int,
    workspace_id: str,
) -> dict | None:
    """Update the current user's last watched position in a media asset (seconds).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Call periodically during playback to enable resume functionality.
    """
    return get_client().contents.patch_media_progression(
        media_id, last_watched_time=last_watched_time, workspace_id=workspace_id
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get progression stats",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_progression_stats(
    workspace_id: str,
    collection_id: str | None = None,
) -> dict:
    """Get completion statistics for the current user.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Pass collection_id to scope to a specific collection.
    Returns total content count and how many the user has completed.
    """
    result = get_client().contents.get_progression_stats(
        collection_id=collection_id, workspace_id=workspace_id
    )
    return result.model_dump(mode="json")
