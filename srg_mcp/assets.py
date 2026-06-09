import base64
import contextlib
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
import srg
from srg_mcp._app import mcp
from srg_mcp._client import get_client
from mcp.types import ToolAnnotations


@mcp.tool(
    annotations=ToolAnnotations(
        title="List assets",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_assets(
    hub_profile_id: str,
    workspace_id: str,
    page_size: int = 50,
    cursor: str | None = None,
    only_archived: bool = False,
    exclude_collections: list[str] | None = None,
    exclude_assets: list[str] | None = None,
    types: list[str] | None = None,
) -> dict:
    """List assets in a hub profile with cursor-based pagination.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
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
        workspace_id=workspace_id,
    )
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "cursor": page.cursor,
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Search assets",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def search_assets(
    hub_profile_id: str,
    search: str,
    workspace_id: str,
    types: list[str] | None = None,
    exclude_categories: list[str] | None = None,
    exclude_collections: list[str] | None = None,
    exclude_medias: list[str] | None = None,
) -> list[dict]:
    """Search assets in a hub profile by keyword.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    types: e.g. ["Media", "File"] or None for all types
    """
    items = get_client().assets.search(
        hub_profile_id,
        search=search,
        types=types,
        exclude_categories=exclude_categories,
        exclude_collections=exclude_collections,
        exclude_medias=exclude_medias,
        workspace_id=workspace_id,
    )
    return [item.model_dump(mode="json") for item in items]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get asset",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_asset(asset_id: str, workspace_id: str) -> dict:
    """Get full asset details by ID (Media, File, Image, Embed, or Video).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return (
        get_client()
        .assets.get(asset_id, workspace_id=workspace_id)
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update asset",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_asset(
    asset_id: str,
    name: str,
    workspace_id: str,
    read_only: bool = False,
    cover_image: str | None = None,
) -> dict:
    """Update an asset's display name, read-only flag, and optionally its cover image.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    cover_image: local file path or http(s):// URL — SDK uploads automatically.
    """
    result = get_client().assets.update(
        asset_id,
        name=name,
        read_only=read_only,
        cover_image=cover_image,
        workspace_id=workspace_id,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create embed asset",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_embed_asset(
    hub_profile_id: str,
    name: str,
    url: str,
    workspace_id: str,
    duration_in_seconds: float | None = None,
) -> dict:
    """Create an embed asset (external URL embed) in a hub profile.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    asset = srg.EmbedAssetCreate(
        name=name,
        url=url,
        duration_in_seconds=duration_in_seconds,
    )
    return (
        get_client()
        .assets.create(
            hub_profile_id=hub_profile_id, asset=asset, workspace_id=workspace_id
        )
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create media asset",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_media_asset(
    hub_profile_id: str,
    name: str,
    workspace_id: str,
    duration_in_seconds: float | None = None,
    memory_size_in_bytes: int | None = None,
) -> dict:
    """Create a media (video) asset record in a hub profile.

    DEPRECATED: registers a record only and does not upload bytes; the
    current backend requires a multipart upload init, so this call fails.
    Use `upload_asset` to create and upload in one step.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns a signed URL for uploading the actual video file.
    """
    asset = srg.MediaAssetCreate(
        name=name,
        duration_in_seconds=duration_in_seconds,
        memory_size_in_bytes=memory_size_in_bytes,
    )
    return (
        get_client()
        .assets.create(
            hub_profile_id=hub_profile_id, asset=asset, workspace_id=workspace_id
        )
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create file asset",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_file_asset(
    hub_profile_id: str,
    name: str,
    extension: str,
    memory_size_in_bytes: int,
    workspace_id: str,
) -> dict:
    """Create a file asset record in a hub profile.

    DEPRECATED: registers a record only and does not upload bytes; the
    current backend requires a multipart upload init, so this call fails.
    Use `upload_asset` to create and upload in one step.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
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
        .assets.create(
            hub_profile_id=hub_profile_id, asset=asset, workspace_id=workspace_id
        )
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create image asset",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_image_asset(
    hub_profile_id: str,
    name: str,
    extension: str,
    width: float,
    height: float,
    memory_size_in_bytes: int,
    workspace_id: str,
) -> dict:
    """Create an image asset record in a hub profile.

    DEPRECATED: registers a record only and does not upload bytes; the
    current backend requires a multipart upload init, so this call fails.
    Use `upload_asset` to create and upload in one step.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
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
        .assets.create(
            hub_profile_id=hub_profile_id, asset=asset, workspace_id=workspace_id
        )
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create video asset",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_video_asset(
    hub_profile_id: str,
    name: str,
    extension: str,
    memory_size_in_bytes: int,
    workspace_id: str,
) -> dict:
    """Create a video file asset record in a hub profile.

    DEPRECATED: registers a record only and does not upload bytes; the
    current backend requires a multipart upload init, so this call fails.
    Use `upload_asset` to create and upload in one step.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
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
        .assets.create(
            hub_profile_id=hub_profile_id, asset=asset, workspace_id=workspace_id
        )
        .model_dump(mode="json")
    )


def _validate_single_source(
    source_url: str | None, base64_content: str | None
) -> None:
    """Require exactly one of ``source_url`` / ``base64_content``."""
    if (source_url is None) == (base64_content is None):
        raise ValueError("Provide exactly one of source_url or base64_content.")


def _infer_extension(
    extension: str | None, source_url: str | None, name: str
) -> str:
    """Best-effort file extension without the dot, lowercased.

    Explicit ``extension`` wins, then the URL path, then the display name.
    Returns an empty string when none can be determined.
    """
    ext = (extension or "").lstrip(".").lower()
    if not ext and source_url:
        ext = Path(urlparse(source_url).path).suffix.lstrip(".").lower()
    if not ext:
        ext = Path(name).suffix.lstrip(".").lower()
    return ext


@mcp.tool(
    annotations=ToolAnnotations(
        title="Upload asset",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def upload_asset(
    hub_profile_id: str,
    name: str,
    workspace_id: str,
    source_url: str | None = None,
    base64_content: str | None = None,
    extension: str | None = None,
    asset_type: str | None = None,
    width: float | None = None,
    height: float | None = None,
    media_type: int | None = None,
) -> dict:
    """Create an asset AND upload its bytes in one call.

    This is the real upload path: it runs the full multipart flow
    (init -> PUT parts -> finalize) and returns a ready, downloadable asset.
    Prefer this over the deprecated create_*_asset tools, which only
    register an empty record and fail against the current backend.

    Provide the file via exactly one of:
      - source_url: an http(s):// URL the server downloads, or
      - base64_content: base64-encoded bytes (best for small files).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    extension: file extension without the dot (e.g. "pdf", "png", "mp4").
        Inferred from source_url or name when omitted.
    asset_type: "Image", "Video", or "File". Auto-detected from the extension
        when omitted.
    width / height: image dimensions in pixels. Auto-detected from the file
        header for common image formats; pass explicitly otherwise.
    media_type: optional mediaType integer for Video uploads.
    """
    _validate_single_source(source_url, base64_content)
    ext = _infer_extension(extension, source_url, name)
    suffix = f".{ext}" if ext else ""

    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as tmp:
            if source_url is not None:
                with httpx.Client(timeout=300.0, follow_redirects=True) as http:
                    with http.stream("GET", source_url) as resp:
                        resp.raise_for_status()
                        for chunk in resp.iter_bytes():
                            tmp.write(chunk)
            else:
                tmp.write(base64.b64decode(base64_content or ""))

        asset = get_client().assets.upload(
            hub_profile_id=hub_profile_id,
            file=tmp_path,
            name=name,
            type=asset_type,
            width=width,
            height=height,
            media_type=media_type,
            workspace_id=workspace_id,
        )
        return asset.model_dump(mode="json")
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
