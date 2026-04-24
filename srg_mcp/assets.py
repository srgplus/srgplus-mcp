import srg
from srg_mcp._app import mcp
from srg_mcp._client import get_client


@mcp.tool()
def list_assets(
    hub_profile_id: str,
    page_size: int = 50,
    cursor: str | None = None,
    only_archived: bool = False,
    exclude_collections: list[str] | None = None,
    exclude_assets: list[str] | None = None,
    types: list[str] | None = None,
) -> dict:
    """List assets in a hub profile with cursor-based pagination.

    types: e.g. ["Media", "File", "Image", "Embed", "Video"] or None for all
    Returns {"items": [...], "cursor": "..." | null}
    """
    page = get_client().assets.filter(
        hub_profile_id,
        page_size=page_size,
        cursor=cursor,
        only_archived=only_archived,
        types=types,
        exclude_collections=exclude_collections,
        exclude_assets=exclude_assets,
    )
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "cursor": page.cursor,
    }


@mcp.tool()
def search_assets(
    hub_profile_id: str,
    search: str,
    types: list[str] | None = None,
    exclude_categories: list[str] | None = None,
    exclude_collections: list[str] | None = None,
    exclude_medias: list[str] | None = None,
) -> list[dict]:
    """Search assets in a hub profile by keyword.

    types: e.g. ["Media", "File"] or None for all types
    """
    items = get_client().assets.search(
        hub_profile_id,
        search=search,
        types=types,
        exclude_categories=exclude_categories,
        exclude_collections=exclude_collections,
        exclude_medias=exclude_medias,
    )
    return [item.model_dump(mode="json") for item in items]


@mcp.tool()
def get_asset(asset_id: str) -> dict:
    """Get full asset details by ID (Media, File, Image, Embed, or Video)."""
    return get_client().assets.get(asset_id).model_dump(mode="json")


@mcp.tool()
def update_asset(
    asset_id: str,
    name: str,
    read_only: bool = False,
    cover_image: str | None = None,
) -> dict:
    """Update an asset's display name, read-only flag, and optionally its cover image.

    cover_image: local file path or http(s):// URL — SDK uploads automatically.
    """
    result = get_client().assets.update(
        asset_id, name=name, read_only=read_only, cover_image=cover_image
    )
    return result.model_dump(mode="json")


@mcp.tool()
def create_embed_asset(
    hub_profile_id: str,
    name: str,
    url: str,
    duration_in_seconds: float | None = None,
) -> dict:
    """Create an embed asset (external URL embed) in a hub profile."""
    asset = srg.EmbedAssetCreate(
        name=name,
        url=url,
        duration_in_seconds=duration_in_seconds,
    )
    return (
        get_client()
        .assets.create(hub_profile_id=hub_profile_id, asset=asset)
        .model_dump(mode="json")
    )


@mcp.tool()
def create_media_asset(
    hub_profile_id: str,
    name: str,
    duration_in_seconds: float | None = None,
    memory_size_in_bytes: int | None = None,
) -> dict:
    """Create a media (video) asset record in a hub profile.

    Returns a signed URL for uploading the actual video file.
    """
    asset = srg.MediaAssetCreate(
        name=name,
        duration_in_seconds=duration_in_seconds,
        memory_size_in_bytes=memory_size_in_bytes,
    )
    return (
        get_client()
        .assets.create(hub_profile_id=hub_profile_id, asset=asset)
        .model_dump(mode="json")
    )


@mcp.tool()
def create_file_asset(
    hub_profile_id: str,
    name: str,
    extension: str,
    memory_size_in_bytes: int,
) -> dict:
    """Create a file asset record in a hub profile.

    extension: without dot, e.g. "pdf"
    Returns a signed URL for uploading the actual file.
    """
    asset = srg.FileAssetCreate(
        name=name,
        extension=extension,
        memory_size_in_bytes=memory_size_in_bytes,
    )
    return (
        get_client()
        .assets.create(hub_profile_id=hub_profile_id, asset=asset)
        .model_dump(mode="json")
    )


@mcp.tool()
def create_image_asset(
    hub_profile_id: str,
    name: str,
    extension: str,
    width: float,
    height: float,
    memory_size_in_bytes: int,
) -> dict:
    """Create an image asset record in a hub profile.

    extension: without dot, e.g. "png"
    Returns a signed URL for uploading the actual image.
    """
    asset = srg.ImageAssetCreate(
        name=name,
        extension=extension,
        width=width,
        height=height,
        memory_size_in_bytes=memory_size_in_bytes,
    )
    return (
        get_client()
        .assets.create(hub_profile_id=hub_profile_id, asset=asset)
        .model_dump(mode="json")
    )


@mcp.tool()
def create_video_asset(
    hub_profile_id: str,
    name: str,
    extension: str,
    memory_size_in_bytes: int,
) -> dict:
    """Create a video file asset record in a hub profile.

    extension: without dot, e.g. "mp4"
    Returns a signed URL for uploading the actual video file.
    """
    asset = srg.VideoAssetCreate(
        name=name,
        extension=extension,
        memory_size_in_bytes=memory_size_in_bytes,
    )
    return (
        get_client()
        .assets.create(hub_profile_id=hub_profile_id, asset=asset)
        .model_dump(mode="json")
    )
