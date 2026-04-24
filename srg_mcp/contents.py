from srg_mcp._app import mcp
from srg_mcp._client import get_client


@mcp.tool()
def list_contents(
    hub_profile_id: str,
    page_size: int = 50,
    cursor: str | None = None,
    only_archived: bool = False,
    types: list[str] | None = None,
    exclude_categories: list[str] | None = None,
    exclude_collections: list[str] | None = None,
    exclude_contents: list[str] | None = None,
) -> dict:
    """List content items in a hub profile with cursor-based pagination.

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
    )
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "cursor": page.cursor,
    }


@mcp.tool()
def search_contents(
    hub_profile_id: str,
    search: str,
    only_archived: bool = False,
    types: list[str] | None = None,
    exclude_categories: list[str] | None = None,
    exclude_collections: list[str] | None = None,
    exclude_contents: list[str] | None = None,
) -> list[dict]:
    """Search content items in a hub profile by keyword.

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
    )
    return [item.model_dump(mode="json") for item in items]


@mcp.tool()
def get_content(content_id: str, hub_profile_id: str | None = None) -> dict:
    """Get content item details by ID (v1 schema).

    hub_profile_id: optional, used to resolve access context
    """
    return (
        get_client()
        .contents.get(content_id, hub_profile_id=hub_profile_id)
        .model_dump(mode="json")
    )


@mcp.tool()
def get_content_v2(content_id: str) -> dict:
    """Get content item by ID (v2 schema).

    Includes main asset, user progression, and extended metadata.
    """
    return get_client().contents.get_v2(content_id).model_dump(mode="json")


@mcp.tool()
def create_content(
    name: str,
    hub_profile_id: str,
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

    privacy: "Preview" (default), "Private", or "Public"
    channels: list of channel IDs to place the content in
    main_asset_id: ID of the primary playable asset
    url: optional external URL to associate with the content
    cover_image: local path or http(s):// URL of the cover image (auto-upload)
    context: additional context widget objects
    categories: category assignment objects
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
    )
    return result.model_dump(mode="json")


@mcp.tool()
def update_content(
    content_id: str,
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

    privacy: "Preview", "Private", or "Public"
    channels: list of channel IDs (replaces existing placement)
    main_asset_id: ID of the primary playable asset
    url: external URL to associate with the content
    hub_profile_id: required if the content belongs to a specific profile
    cover_image: local path or http(s):// URL of the cover image (auto-upload)
    context: context widget objects (replaces existing)
    categories: category assignment objects (replaces existing)
    """
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
    )
    return result.model_dump(mode="json")


@mcp.tool()
def add_content_to_categories(
    content_id: str,
    channel_id: str,
    category_ids: list[str],
) -> str:
    """Add a content item to one or more channel categories.

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
    )
    return "added"


@mcp.tool()
def remove_content_from_categories(
    content_id: str,
    channel_id: str,
    category_ids: list[str],
) -> str:
    """Remove a content item from one or more channel categories.

    The content item itself is not deleted.

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
    )
    return "removed"


@mcp.tool()
def move_content(
    content_id: str,
    channel_id: str,
    category_id: str,
    section_id: str,
) -> str:
    """Move a content item to a different category section within a channel.

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
    )
    return "moved"


# ---------------------------------------------------------------------------
# Content sections (for collections)
# ---------------------------------------------------------------------------


@mcp.tool()
def create_content_section(
    content_id: str, category_name: str, name: str
) -> dict | None:
    """Create a section inside a collection content item's category.

    category_name: the name slug of the category (e.g. "week-1")
    """
    return get_client().contents.create_section(content_id, category_name, name=name)


@mcp.tool()
def update_content_section(
    content_id: str,
    category_name: str,
    section_id: str,
    name: str,
) -> dict | None:
    """Rename a section inside a collection content item's category."""
    return get_client().contents.update_section(
        content_id, category_name, section_id, name=name
    )


@mcp.tool()
def delete_content_section(
    content_id: str,
    category_name: str,
    section_id: str,
) -> str:
    """Delete a section from a collection content item's category. Irreversible."""
    get_client().contents.delete_section(content_id, category_name, section_id)
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
#   3. add_content_references(...)      → links existing content as sub-items
#      → the container is now a Collection
#   4. get_content_references(...)      → lists the nested content (paginated)
#   5. move_content_reference(...)      → reorders a sub-item within the section
#   6. delete_content_reference(...)    → removes a sub-item (does not delete it)
# ---------------------------------------------------------------------------


@mcp.tool()
def add_subcontent(
    content_id: str,
    category_name: str,
    section_id: str,
    subcontent_ids: list[str],
) -> str:
    """Link existing content items as subcontent inside a collection section.

    Subcontent is the nested content that lives inside a Collection — think
    lessons inside a course, or chapters inside a module.  A Content item
    automatically becomes a Collection once it has at least one subcontent item.

    Multiple IDs can be passed in a single call; they are added in the order
    given.  The items must already exist as standalone content — this call only
    creates the link, it does not move or copy them.

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
    )
    return "added"


@mcp.tool()
def get_subcontent(
    content_id: str,
    category_name: str,
    page_size: int = 50,
    cursor: str | None = None,
    order: str = "Asc",
) -> dict:
    """List the subcontent items nested inside a collection, page by page.

    Returns the content items linked as subcontent inside the given collection's
    category.  Each item includes its id, name, cover, privacy, progression,
    and the section it belongs to.

    Use the returned cursor to fetch the next page.  cursor=None means you are
    on the last page.

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
    )
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "cursor": page.cursor,
    }


@mcp.tool()
def delete_subcontent(
    content_id: str,
    category_name: str,
    section_id: str,
    subcontent_id: str,
) -> str:
    """Unlink a subcontent item from a collection section.

    Removes the link between the collection and the subcontent item.  The
    subcontent item itself is NOT deleted — it continues to exist as a
    standalone content item.

    If all subcontent is removed, the collection reverts to a plain Content item.

    content_id:    ID of the collection (the parent content item)
    category_name: "Content" or "Asset"
    section_id:    ID of the section that currently contains the subcontent item
    subcontent_id: ID of the subcontent item to unlink
    """
    get_client().contents.delete_subcontent(
        content_id, category_name, section_id, subcontent_id
    )
    return "deleted"


@mcp.tool()
def move_subcontent(
    content_id: str,
    category_name: str,
    section_id: str,
    subcontent_id: str,
    previous_subcontent_id: str | None = None,
) -> str:
    """Reorder a subcontent item within a collection section.

    Moves the item to the position immediately AFTER previous_subcontent_id.
    Pass previous_subcontent_id=None to move the item to the very first
    position in the section.

    Only the display order changes — no content is created, deleted, or moved
    to a different section.

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
    )
    return "moved"


# ---------------------------------------------------------------------------
# Progressions
# ---------------------------------------------------------------------------


@mcp.tool()
def patch_content_progression(content_id: str, status: str) -> dict:
    """Update the current user's progression status for a content item.

    status: "NotStarted", "Incomplete", or "Completed"
    """
    result = get_client().contents.patch_content_progression(
        content_id,
        status=status,  # type: ignore[arg-type]
    )
    return result.model_dump(mode="json")


@mcp.tool()
def patch_media_progression(media_id: str, last_watched_time: int) -> dict | None:
    """Update the current user's last watched position in a media asset (seconds).

    Call periodically during playback to enable resume functionality.
    """
    return get_client().contents.patch_media_progression(
        media_id, last_watched_time=last_watched_time
    )


@mcp.tool()
def get_progression_stats(collection_id: str | None = None) -> dict:
    """Get completion statistics for the current user.

    Pass collection_id to scope to a specific collection.
    Returns total content count and how many the user has completed.
    """
    result = get_client().contents.get_progression_stats(collection_id=collection_id)
    return result.model_dump(mode="json")
