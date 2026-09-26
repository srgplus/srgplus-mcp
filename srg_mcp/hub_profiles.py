"""Hub profile (brand) tools.

Reads and edits go through the SDK's authenticated client (``_raw``) against
the PATCH / If-Match / from-asset routes (SRGDEV-798), so a caller that
changes one field can never wipe the rest of the profile. The legacy full
``PUT /hub-profiles/{id}`` is not exposed: it clears widgets and buttons that
are left out and turns a Private hub Public.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import srg.exceptions
from mcp.types import ToolAnnotations

from srg_mcp import _images, _raw
from srg_mcp._app import mcp
from srg_mcp._client import get_client

_VISIBILITY = {0: "Public", 1: "Private", "Public": "Public", "Private": "Private"}
_VISIBILITY_CODE = {"public": 0, "private": 1}

# Backend limits (HubProfileValidator / UpdateProfileValidator, SRGDEV-798).
_MAX_LINKS = 20
_LIST_PAGE_MAX = 200

# Same wait as set_cover: a just-uploaded Drive image is "still uploading" for a
# second or two while Content-Hub marks it ready.
_STILL_UPLOADING_RETRY_DELAYS = (1, 1, 2, 2, 3, 3, 4, 4, 5)

# Host → platform label for links (display only; SRG+ stores title + url).
_PLATFORMS = (
    ("instagram.com", "instagram"),
    ("tiktok.com", "tiktok"),
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("facebook.com", "facebook"),
    ("fb.com", "facebook"),
    ("x.com", "x"),
    ("twitter.com", "x"),
    ("threads.net", "threads"),
    ("threads.com", "threads"),
    ("linkedin.com", "linkedin"),
    ("pinterest.com", "pinterest"),
    ("snapchat.com", "snapchat"),
    ("twitch.tv", "twitch"),
    ("discord.gg", "discord"),
    ("discord.com", "discord"),
    ("t.me", "telegram"),
    ("telegram.me", "telegram"),
    ("wa.me", "whatsapp"),
    ("whatsapp.com", "whatsapp"),
    ("spotify.com", "spotify"),
    ("music.apple.com", "apple_music"),
    ("podcasts.apple.com", "apple_podcasts"),
    ("soundcloud.com", "soundcloud"),
    ("github.com", "github"),
    ("patreon.com", "patreon"),
    ("substack.com", "substack"),
    ("vimeo.com", "vimeo"),
    ("calendly.com", "calendly"),
    ("amazon.com", "amazon"),
    ("etsy.com", "etsy"),
    ("srgplus.com", "srgplus"),
)

# Shared by the tool docs and the guide, so image advice stays in one place.
HUB_IMAGE_RULES = """\
Avatar: square (1:1), at least 400x400, 1024x1024 recommended. It is shown as a
circle (96-160 px on the web, 100-146 pt in the apps), so keep the subject inside
the middle ~70% and leave the corners empty.
Cover: 3:1 recommended, 2400x800 (at least 1500x500). It is center-cropped to fill:
about 3.3:1 on a wide web page, 2.3:1 on a phone browser, 2.76:1 on iPad/Mac and
1.85:1 on iPhone. Safe area: keep logos and text in the middle ~60% of the width
and ~90% of the height (for 2400x800: x 460-1940, y 40-760). In the Apple apps the
round avatar overlaps the cover's lower-left corner (bottom ~35% of the height,
from ~20% to ~40% of the width on a 3:1 cover), so keep that corner free; on the
web the avatar sits below the cover. Formats: PNG, JPG, WEBP, GIF."""


def _visibility(value: Any) -> str | None:  # noqa: ANN401
    return _VISIBILITY.get(value) if value is not None else None


def _platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for domain, name in _PLATFORMS:
        if host == domain or host.endswith("." + domain):
            return name
    return "website"


def _image(data: dict | None) -> dict | None:
    """Avatar / cover read shape → {url, extension, width, height, ...} or None."""
    if not data or not data.get("details"):
        return None
    details = data["details"]
    image = {
        "url": details.get("url"),
        "extension": details.get("extension"),
        "width": data.get("width"),
        "height": data.get("height"),
        "source_asset_id": data.get("sourceAssetId"),
        "modified": data.get("modified"),
    }
    return {k: v for k, v in image.items() if v is not None}


def _link_out(link: dict) -> dict:
    icon = link.get("iconUrl")
    row = {
        "$type": link.get("$type"),
        "id": link.get("id"),
        "title": link.get("title"),
        "url": link.get("url"),
        "platform": _platform(link.get("url") or ""),
    }
    if isinstance(icon, dict) and icon.get("url"):
        row["icon_url"] = icon["url"]
    return row


def _profile_out(data: dict) -> dict:
    """GET /hub-profiles/{id} → the compact agent-facing shape."""
    widgets = data.get("widgets") or []
    link_list = next((w for w in widgets if w.get("$type") == "LinkList"), None)
    others = [
        {"$type": w.get("$type"), "id": w.get("id"), "title": w.get("title")}
        for w in widgets
        if w is not link_list
    ]
    user_name = data.get("userName")
    out = {
        "id": data.get("id"),
        "name": data.get("name"),
        "sub_name": data.get("subName"),
        "user_name": user_name,
        "description": data.get("description"),
        "primary_url": data.get("primaryUrl"),
        "visibility": _visibility(data.get("availabilityLevel")),
        "profile_url": f"https://srgplus.com/{user_name}" if user_name else None,
        "avatar": _image(data.get("avatar")),
        "cover": _image(data.get("cover")),
        "links": [_link_out(link) for link in (link_list or {}).get("links") or []],
        "links_widget_id": (link_list or {}).get("id"),
        "buttons": data.get("buttons") or [],
        "other_widgets": others,
        "workspace_id": data.get("workspaceId"),
        "drive_id": data.get("driveId"),
        "created": None if str(data.get("created") or "").startswith("0001-") else data.get("created"),
        "modified": data.get("modified"),
        "version": data.get("version"),
    }
    return out


def _link_in(link: dict) -> dict:
    """Agent link → backend LinkBaseUpdate. KnownLink by default (icon from the site)."""
    if not isinstance(link, dict):
        raise ValueError('Each link must be {"title": "...", "url": "https://..."}.')
    title = (link.get("title") or "").strip()
    url = (link.get("url") or "").strip()
    if not title or not url:
        raise ValueError(f"Each link needs a title and a url; got {link!r}.")
    if len(title) > 100:
        raise ValueError(f"Link title {title!r} is longer than 100 characters.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    kind = link.get("$type") or "KnownLink"
    if kind not in ("KnownLink", "CustomLink"):
        raise ValueError(f'Link $type must be "KnownLink" or "CustomLink", not {kind!r}.')
    out: dict = {"$type": kind, "title": title, "url": url}
    if link.get("id"):
        out["id"] = link["id"]
    return out


def _links_in(links: list[dict]) -> list[dict]:
    rows = [_link_in(link) for link in links]
    if len(rows) > _MAX_LINKS:
        raise ValueError(f"A profile can have at most {_MAX_LINKS} links; got {len(rows)}.")
    titles = [r["title"] for r in rows]
    dupes = sorted({t for t in titles if titles.count(t) > 1})
    if dupes:
        raise ValueError(f"Link titles must be unique; repeated: {dupes}.")
    return rows


def _if_match(expected_version: int | None) -> dict | None:
    return None if expected_version is None else {"If-Match": f'"{int(expected_version)}"'}


def _get(hub_profile_id: str, workspace_id: str) -> dict:
    return _raw.call(workspace_id, "GET", f"/api/v1/hub-profiles/{hub_profile_id}") or {}


def _still_uploading(exc: srg.exceptions.APIStatusError) -> bool:
    return isinstance(exc, srg.exceptions.BadRequestError) and (
        "still uploading" in f"{exc.message} {exc.body}".lower()
    )


def _signed(response: dict, key: str) -> tuple[str | None, dict | None]:
    signed = response.get(key) or {}
    if isinstance(signed, str):
        return signed, None
    return signed.get("url"), signed.get("metadataHeaders")


def _upload_param(image: _images.CoverImage) -> dict:
    return {
        "extension": image.extension,
        "generateSignedUrl": True,
        "width": image.width,
        "height": image.height,
    }




@mcp.tool(
    annotations=ToolAnnotations(
        title="List hub profiles",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_hub_profiles(
    workspace_id: str,
    search: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict:
    """List the hub profiles (brands) of a workspace as compact rows:
    id, name, user_name, has_avatar.

    search: optional, case-insensitive match on name or user_name.
    page_size: rows per page (default 50, max 200). When more exist the
        result has a `cursor`; pass it back for the next page.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns {"items": [...], "total": n, "cursor": str | None}. For bio,
    avatar/cover URLs, links and `version` call get_hub_profile.
    """
    rows = _raw.call(workspace_id, "GET", f"/api/v1/workspaces/{workspace_id}/hub-profiles") or []
    needle = (search or "").strip().lower()
    items = [
        {
            "id": row.get("id"),
            "name": row.get("name"),
            "user_name": row.get("userName"),
            "has_avatar": bool((row.get("avatar") or {}).get("details")),
        }
        for row in rows
        if not needle
        or needle in (row.get("name") or "").lower()
        or needle in (row.get("userName") or "").lower()
    ]
    try:
        start = int(cursor) if cursor else 0
    except ValueError:
        raise ValueError("cursor must be the value returned by the previous call.") from None
    size = max(1, min(int(page_size), _LIST_PAGE_MAX))
    page = items[start : start + size]
    nxt = start + size
    return {"items": page, "total": len(items), "cursor": str(nxt) if nxt < len(items) else None}

@mcp.tool(
    annotations=ToolAnnotations(
        title="List managed hub profiles",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_managed_hub_profiles(workspace_id: str) -> list[dict]:
    """List hub profiles where the current API key user has Admin or Editor role.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return [
        p.model_dump(mode="json")
        for p in get_client().hub_profiles.list_managed(workspace_id=workspace_id)
    ]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get hub profile",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_hub_profile(hub_profile_id: str, workspace_id: str) -> dict:
    """Read a hub profile (brand page srgplus.com/<user_name>) in full.

    Returns name, sub_name (the line under the name), user_name, description
    (the bio), primary_url (website), visibility, avatar and cover
    ({url, extension, width, height, source_asset_id} or null when not set),
    links ([{$type, id, title, url, platform}], the profile's link list),
    buttons, other_widgets (id/type/title only), created, modified and
    `version`. Pass `version` as expected_version to update_hub_profile /
    set_hub_avatar / set_hub_cover to get a 409 instead of overwriting
    someone else's edit. Image URLs are signed and expire after ~7 days.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return _profile_out(_get(hub_profile_id, workspace_id))

@mcp.tool(
    annotations=ToolAnnotations(
        title="Get hub profile by username",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_hub_profile_by_username(username: str, workspace_id: str) -> dict:
    """Get hub profile details by its URL username/slug.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return (
        get_client()
        .hub_profiles.get_by_username(username, workspace_id=workspace_id)
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Filter hub profiles",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def filter_hub_profiles(
    ids: list[str],
    workspace_id: str,
    availability_level: str | None = None,
) -> list[dict]:
    """Batch-fetch lightweight hub profile data for a list of IDs.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    availability_level: "Public" or "Private" to filter by visibility
    """
    return [
        p.model_dump(mode="json")
        for p in get_client().hub_profiles.filter(
            ids=ids,
            availability_level=availability_level,  # type: ignore[arg-type]
            workspace_id=workspace_id,
        )
    ]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create hub profile",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_hub_profile(
    name: str,
    user_name: str,
    workspace_id: str,
    sub_name: str | None = None,
    description: str | None = None,
    primary_url: str | None = None,
    availability_level: str = "Public",
    app_clip_on: bool = False,
    widgets: list[dict] | None = None,
    buttons: list[dict] | None = None,
) -> dict:
    """Create a new hub profile in a workspace.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    availability_level: "Public" (default) or "Private"
    primary_url: optional external URL shown on the profile
    app_clip_on: enable iOS App Clip
    widgets: profile widget configuration objects
    buttons: action buttons, each
        {"title": "...", "logic": {"type": "...", "url": "..."}}
    """
    from srg.schemas.hub_profile import ActionButtonLogicUpsert, ActionButtonUpsert

    btn_objs = (
        [
            ActionButtonUpsert(
                title=b["title"],
                logic=ActionButtonLogicUpsert(**b["logic"]),
            )
            for b in buttons
        ]
        if buttons
        else None
    )
    result = get_client().hub_profiles.create(
        name=name,
        user_name=user_name,
        sub_name=sub_name,
        description=description,
        primary_url=primary_url,
        availability_level=availability_level,  # type: ignore[arg-type]
        app_clip_on=app_clip_on,
        workspace_id=workspace_id,
        widgets=widgets,
        buttons=btn_objs,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update hub profile",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_hub_profile(
    hub_profile_id: str,
    workspace_id: str,
    name: str | None = None,
    user_name: str | None = None,
    sub_name: str | None = None,
    description: str | None = None,
    bio: str | None = None,
    primary_url: str | None = None,
    visibility: str | None = None,
    links: list[dict] | None = None,
    buttons: list[dict] | None = None,
    avatar_image: str | None = None,
    cover_image: str | None = None,
    expected_version: int | None = None,
) -> dict:
    """Edit a hub profile. Only the fields you pass change; everything you
    omit (avatar, cover, links, buttons, other widgets, visibility, user_name)
    keeps its stored value.

    name: 2-150 chars. user_name: the URL slug srgplus.com/<user_name>, 2-150
        chars of letters, digits, "-", "_", "."; stored lowercased; 400 if taken.
    sub_name: the short line under the name (max 150).
    description / bio: the profile bio (same field; pass either), 10-1000 chars.
    primary_url: the website link. visibility: "Public" or "Private".
    Pass "" to clear sub_name, description or primary_url.
    links: the profile's link list, [{"title": "Instagram", "url": "https://..."}]
        (max 20, unique titles). KnownLink by default (SRG+ fetches the site
        icon); {"$type": "CustomLink", ...} for a plain link. The list you pass
        REPLACES the whole link list — to add one, get_hub_profile first,
        append, and send the full list back (keep each link's `id` to keep it).
        [] removes the link list. Other widgets are never touched.
    buttons: REPLACES all action buttons (max 3), each
        {"title": "...", "logic": {"$type": "OpenLink", "url": "https://..."}}.
    avatar_image / cover_image: a public http(s) image URL; downloaded and
        stored. "" removes the avatar / cover. For a file already in the
        hub's Drive use set_hub_avatar / set_hub_cover instead (no download).
    expected_version: the `version` from get_hub_profile → 409 (nothing
        written) if someone changed the profile since.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns {"id", "version", "updated_fields", "profile"} (the fresh profile).
    """
    if bio is not None and description is not None and bio != description:
        raise ValueError("bio and description are the same field; pass only one.")
    body: dict = {}
    for key, value in (
        ("name", name),
        ("userName", user_name),
        ("subName", sub_name),
        ("description", description if description is not None else bio),
        ("primaryUrl", primary_url),
    ):
        if value is not None:
            body[key] = value
    if visibility is not None:
        code = _VISIBILITY_CODE.get(str(visibility).strip().lower())
        if code is None:
            raise ValueError('visibility must be "Public" or "Private".')
        body["availabilityLevel"] = code
    if links is not None:
        body["links"] = _links_in(links)
    if buttons is not None:
        body["buttons"] = buttons

    # Download images BEFORE writing, so a bad URL fails with nothing changed.
    images: dict[str, _images.CoverImage] = {}
    for key, source in (("avatar", avatar_image), ("cover", cover_image)):
        if source == "":
            body[key] = {"extension": None, "generateSignedUrl": True}  # remove the image
        elif source:
            images[key] = _images.load(source, _images.HUB_IMAGE_EXTENSIONS)
            body[key] = _upload_param(images[key])
    if not body:
        raise ValueError("Nothing to update: pass at least one field.")

    response = _raw.call(
        workspace_id,
        "PATCH",
        f"/api/v1/hub-profiles/{hub_profile_id}",
        json=body,
        headers=_if_match(expected_version),
    ) or {}
    for key, image in images.items():
        url, headers = _signed(response, f"{key}SignedUrl")
        if not url:
            raise RuntimeError(f"SRG+ did not return an upload URL for the {key}; nothing was uploaded.")
        try:
            _images.put_signed(url, image, headers)
        except Exception as exc:  # noqa: BLE001 - report which part failed
            raise RuntimeError(
                f"The other fields WERE updated, but uploading the {key} failed: {exc}. "
                f"Retry with {key}_image only."
            ) from exc

    fields = sorted(
        {"userName": "user_name", "subName": "sub_name", "primaryUrl": "primary_url",
         "availabilityLevel": "visibility"}.get(k, k)
        for k in body
    )
    profile = _profile_out(_get(hub_profile_id, workspace_id))
    return {
        "id": hub_profile_id,
        "version": response.get("version", profile.get("version")),
        "updated_fields": fields,
        "profile": profile,
    }


def _set_image_from_asset(
    target: str,
    hub_profile_id: str,
    asset_id: str,
    workspace_id: str,
    expected_version: int | None,
) -> dict:
    delays = iter(_STILL_UPLOADING_RETRY_DELAYS)
    while True:
        try:
            data = _raw.call(
                workspace_id,
                "POST",
                f"/api/v1/hub-profiles/{hub_profile_id}/{target}/from-asset",
                json={"assetId": asset_id},
                headers=_if_match(expected_version),
            ) or {}
            break
        except srg.exceptions.APIStatusError as exc:
            delay = next(delays, None)
            if delay is None or not _still_uploading(exc):
                raise
            time.sleep(delay)
    return {
        "id": hub_profile_id,
        "version": data.get("version"),
        target: _image(data.get("image")),
        "asset_id": asset_id,
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Set hub avatar from a Drive image",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def set_hub_avatar(
    hub_profile_id: str,
    asset_id: str,
    workspace_id: str,
    expected_version: int | None = None,
) -> dict:
    """Use an image that is already in THIS hub's Drive as the profile avatar.

    asset_id: an Image asset of the same hub (from complete_upload or
        list_drive_files(types=["Image"])). An asset of another hub is refused
        with 404. The image is copied, so the avatar stays if the Drive file is
        deleted later. Right after an upload it may need a few seconds to be
        ready; this tool waits. Everything else on the profile is kept.
    expected_version: the `version` from get_hub_profile → 409 if stale.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns {"id", "version", "avatar": {url, extension, width, height,
    source_asset_id}, "asset_id"}.
    Image: square (1:1), at least 400x400, 1024x1024 recommended; PNG, JPG,
    WEBP or GIF. It is shown as a circle, so keep the subject in the middle
    ~70% and the corners empty.
    """
    return _set_image_from_asset("avatar", hub_profile_id, asset_id, workspace_id, expected_version)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Set hub cover from a Drive image",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def set_hub_cover(
    hub_profile_id: str,
    asset_id: str,
    workspace_id: str,
    expected_version: int | None = None,
) -> dict:
    """Use an image that is already in THIS hub's Drive as the profile cover
    (the banner at the top of srgplus.com/<user_name>).

    asset_id: an Image asset of the same hub; another hub's asset is refused
        with 404. Copied, waits for a just-uploaded image, keeps every other
        field, like set_hub_avatar.
    expected_version: the `version` from get_hub_profile → 409 if stale.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns {"id", "version", "cover": {url, extension, width, height,
    source_asset_id}, "asset_id"}.
    Image: 3:1, 2400x800 recommended (at least 1500x500); PNG, JPG, WEBP or
    GIF. It is center-cropped (about 1.85:1 on iPhone up to 3.3:1 on a wide
    web page): keep logos and text in the middle ~60% of the width. In the
    Apple apps the round avatar covers the lower-left corner (bottom ~35%,
    ~20-40% of the width), so keep it free. Full rules: get_srgplus_guide().
    """
    return _set_image_from_asset("cover", hub_profile_id, asset_id, workspace_id, expected_version)

@mcp.tool(
    annotations=ToolAnnotations(
        title="Archive hub profile",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def archive_hub_profile(hub_profile_id: str, workspace_id: str) -> dict | None:
    """Archive a hub profile (hidden from listings, content preserved).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().hub_profiles.archive(hub_profile_id, workspace_id=workspace_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Restore hub profile",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def restore_hub_profile(hub_profile_id: str, workspace_id: str) -> dict | None:
    """Restore a previously archived hub profile.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().hub_profiles.restore(hub_profile_id, workspace_id=workspace_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete hub profile",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_hub_profile(hub_profile_id: str, workspace_id: str) -> str:
    """Permanently delete a hub profile and all its data. Irreversible.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    get_client().hub_profiles.delete(hub_profile_id, workspace_id=workspace_id)
    return "deleted"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Join hub profile",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def join_hub_profile(hub_profile_id: str, workspace_id: str) -> dict | None:
    """Join a public hub profile as the current API key user.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().hub_profiles.join(hub_profile_id, workspace_id=workspace_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Move hub profile to workspace",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def move_hub_profile_to_workspace(
    hub_profile_id: str, workspace_id: str
) -> dict | None:
    """Transfer a hub profile to a different workspace (preserves content)."""
    return get_client().hub_profiles.move_to_workspace(hub_profile_id, workspace_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Enable hub profile community",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def turn_on_hub_profile_community(
    hub_profile_id: str, workspace_id: str
) -> dict | None:
    """Enable community features for a hub profile (posts, comments, reactions).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().hub_profiles.turn_on_community(
        hub_profile_id, workspace_id=workspace_id
    )
