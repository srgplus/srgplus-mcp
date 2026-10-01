"""Channel look and order, category settings: one thing at a time, everything else kept.

What the apps' Edit Channel / Edit Category screens change, by voice or by an agent:

    PUT    /api/v1/channels/{id}/icon        {kind, symbol | emoji | assetId, color}  (SRGDEV-948)
    DELETE /api/v1/channels/{id}/icon        back to the plain "#"
    PATCH  /api/v1/channels/{id}             {slug}  the link name (SRGDEV-805b)
    POST   /api/v1/channels/{id}/move        {previousChannelId}  the hub's channel order
    PUT    /api/v1/channels                  {channelId, hubProfileId, name, categories:[{categoryId, isArchived}]}
                                             the category order; must list EVERY category with its archive flag
    PUT    /api/v1/channels/{id}/categories/{categoryId}
                                             {name, isPinned, notificationsEnabled, emailEnabled, options}
                                             a full replace, so the tools read the category first and send
                                             every field back with only the asked change

Pinning a category unpins the channel's other one (one pinned category per channel).
"""

from __future__ import annotations

import re
from typing import Any

import srg.exceptions
from mcp.types import ToolAnnotations

from srg_mcp import _raw
from srg_mcp._app import mcp
from srg_mcp._category_options import settings_of, with_changes
from srg_mcp.channels import (
    _category,
    _channel,
    _hub_profile_id,
    channel_link,
    icon_out,
    settings_after,
    write_category,
)

_OBJECT_ID = re.compile(r"^[0-9a-fA-F]{24}$")
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SLUG_MAX = 50
_EMOJI_MAX = 32

# The 12 colours the apps offer for a channel icon (Apple Reminders); blue is the default.
COLORS = {
    "red": "#FF3B30",
    "orange": "#FF9500",
    "yellow": "#FFCC00",
    "green": "#34C759",
    "mint": "#00C7BE",
    "teal": "#00C7BE",
    "cyan": "#5AC8FA",
    "light blue": "#5AC8FA",
    "sky": "#5AC8FA",
    "blue": "#007AFF",
    "indigo": "#5856D6",
    "purple": "#AF52DE",
    "violet": "#AF52DE",
    "pink": "#FF2D55",
    "brown": "#A2845E",
    "gray": "#8E8E93",
    "grey": "#8E8E93",
}
DEFAULT_COLOR = "#007AFF"
COLOR_NAMES = ("red", "orange", "yellow", "green", "mint", "cyan", "blue", "indigo", "purple", "pink", "brown", "gray")
# The SF Symbols the apps' Icon page offers (any SF Symbol name works).
APP_SYMBOLS = (
    "star.fill", "heart.fill", "bolt.fill", "flame.fill", "leaf.fill", "moon.fill",
    "sun.max.fill", "cloud.fill", "drop.fill", "snowflake", "pawprint.fill", "fish.fill",
    "house.fill", "building.2.fill", "cart.fill", "bag.fill", "gift.fill", "creditcard.fill",
    "book.fill", "graduationcap.fill", "pencil", "paintbrush.fill", "camera.fill", "video.fill",
    "music.note", "headphones", "mic.fill", "gamecontroller.fill", "film.fill", "theatermasks.fill",
    "airplane", "car.fill", "bicycle", "figure.run", "dumbbell.fill", "sportscourt.fill",
    "briefcase.fill", "hammer.fill", "wrench.and.screwdriver.fill", "lightbulb.fill", "megaphone.fill", "bell.fill",
    "flag.fill", "globe", "map.fill", "mappin.and.ellipse", "person.2.fill", "chart.bar.fill",
)
_HASH_SYMBOL = "number"  # the apps' coloured "#"


# ---- channel icon ----------------------------------------------------------------------


def _color(value: str) -> str:
    named = COLORS.get(" ".join(str(value).strip().lower().split()))
    if named:
        return named
    match = _HEX.match(str(value).strip())
    if not match:
        raise ValueError(f"color must be #RRGGBB or one of {', '.join(COLOR_NAMES)}; got {value!r}.")
    return f"#{match.group(1).upper()}"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Set channel icon",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def set_channel_icon(
    channel_id: str,
    workspace_id: str,
    symbol: str | None = None,
    emoji: str | None = None,
    photo_asset_id: str | None = None,
    color: str | None = None,
) -> dict:
    """Set a channel's icon, the picture before its name in the apps (Apple Reminders style).
    Only the icon changes.

    Pass exactly ONE of:
    - symbol: one of the SF Symbols the apps offer, drawn on the colour:
      star.fill, heart.fill, bolt.fill, flame.fill, leaf.fill, moon.fill, sun.max.fill,
      cloud.fill, drop.fill, snowflake, pawprint.fill, fish.fill, house.fill, building.2.fill,
      cart.fill, bag.fill, gift.fill, creditcard.fill, book.fill, graduationcap.fill, pencil,
      paintbrush.fill, camera.fill, video.fill, music.note, headphones, mic.fill,
      gamecontroller.fill, film.fill, theatermasks.fill, airplane, car.fill, bicycle,
      figure.run, dumbbell.fill, sportscourt.fill, briefcase.fill, hammer.fill,
      wrench.and.screwdriver.fill, lightbulb.fill, megaphone.fill, bell.fill, flag.fill, globe,
      map.fill, mappin.and.ellipse, person.2.fill, chart.bar.fill. "#" gives a coloured "#".
      Another name is refused (the apps would draw an empty circle): pick the closest or
      use an emoji.
    - emoji: exactly one emoji drawn on the colour, e.g. "🚀".
    - photo_asset_id: the id of an uploaded image in THIS hub's Drive (list_drive_files, or
      create_upload → complete_upload first), shown as a round photo.
    color: "#RRGGBB" or an app colour: red, orange, yellow, green, mint, cyan, blue, indigo,
        purple, pink, brown, gray. Left out: the channel keeps its current colour (blue if it had none).
    To go back to the plain "#", use remove_channel_icon.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    kinds = (("symbol", symbol), ("emoji", emoji), ("photo_asset_id", photo_asset_id))
    given = [name for name, value in kinds if value]
    if len(given) != 1:
        raise ValueError(
            "Pass exactly one of symbol, emoji or photo_asset_id"
            + (f" (got {', '.join(given)})." if given else ".")
        )

    body: dict[str, Any]
    if symbol:
        name = str(symbol).strip().lower()
        name = _HASH_SYMBOL if name in ("#", "hash") else name
        if name not in APP_SYMBOLS and name != _HASH_SYMBOL:
            # The apps draw the name with Image(systemName:): an unknown one shows an
            # empty circle, so only the symbols the apps offer are taken.
            raise ValueError(
                f"symbol must be one the apps offer: {', '.join(APP_SYMBOLS)}, or '#'. Got {symbol!r}; "
                "pick the closest one, or use an emoji instead."
            )
        body = {"kind": "symbol", "symbol": name}
    elif emoji:
        value = str(emoji).strip()
        if not value or len(value) > _EMOJI_MAX:
            raise ValueError(f"emoji must be exactly one emoji, got {emoji!r}.")
        body = {"kind": "emoji", "emoji": value}
    else:
        asset_id = str(photo_asset_id).strip()
        if not _OBJECT_ID.match(asset_id):
            raise ValueError(
                f"photo_asset_id must be the 24-character id of an image in this hub's Drive, got {photo_asset_id!r}."
            )
        body = {"kind": "photo", "assetId": asset_id.lower()}

    if color:
        body["color"] = _color(color)
    else:
        current = (_channel(channel_id, workspace_id).get("icon") or {}).get("color")
        if current or body["kind"] != "photo":
            body["color"] = current or DEFAULT_COLOR

    _raw.call(workspace_id, "PUT", f"/api/v1/channels/{channel_id}/icon", json=body)
    return {"channel_id": channel_id, "icon": icon_out(body)}


@mcp.tool(
    annotations=ToolAnnotations(
        title="Remove channel icon",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def remove_channel_icon(channel_id: str, workspace_id: str) -> str:
    """Remove a channel's icon: the apps show the plain "#" again. Only the icon changes
    (a photo icon's image stays in Drive).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    _raw.call(workspace_id, "DELETE", f"/api/v1/channels/{channel_id}/icon")
    return "removed"


# ---- channel link ----------------------------------------------------------------------


def _slug(value: str) -> str:
    slug = re.sub(r"[\s_]+", "-", str(value or "").strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug or len(slug) > _SLUG_MAX or not _SLUG.match(slug):
        raise ValueError(
            f"slug must be 1-{_SLUG_MAX} lower-case latin letters, digits and single dashes, "
            f"like 'video-lessons' (transliterate other letters), got {value!r}."
        )
    return slug


@mcp.tool(
    annotations=ToolAnnotations(
        title="Set channel link",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def set_channel_slug(channel_id: str, slug: str, workspace_id: str) -> dict:
    """Set a channel's link name (slug): srgplus.com/<hub user name>/channels/<slug>.
    Only the link changes; the channel's name stays.

    slug: 1-50 lower-case latin letters, digits and single dashes, e.g. "video-lessons"
        (spaces become dashes). One used by another channel of the hub (its name, link or an
        old link) fails with 409.
    By default the link follows the channel's name (rename_channel changes it, Cyrillic is
    transliterated); a link set here stays until it is set again (setting the name's own
    slug makes it follow the name again). Old links keep working.
    Returns the channel's name, slug and full link.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    value = _slug(slug)
    try:
        _raw.call(workspace_id, "PATCH", f"/api/v1/channels/{channel_id}", json={"slug": value})
    except srg.exceptions.ConflictError as exc:
        raise ValueError(
            f"The link {value!r} is taken: another channel of this hub uses it as its name, link "
            "or an old link. Nothing changed; pick another slug."
        ) from exc
    channel = _channel(channel_id, workspace_id)
    return {
        "channel_id": channel_id,
        "name": channel.get("name"),
        "slug": channel.get("slug"),
        "link": channel_link(channel),
    }


# ---- order -----------------------------------------------------------------------------


def _find(raw: Any, items: list[dict]) -> list[dict]:  # noqa: ANN401
    """Items with this id, else with this exact name (any case)."""
    key = str(raw).strip()
    by_id = [i for i in items if str(i.get("id", "")).lower() == key.lower()]
    return by_id or [i for i in items if str(i.get("name", "")).strip().casefold() == key.casefold()]


def _wanted(ids: list[str], active: list[dict], archived: list[dict], what: str, where: str) -> list[str]:
    """The listed ids (or exact names) as stored ids, in order. Unknown, repeated, ambiguous
    or archived ones fail before any write."""
    if not isinstance(ids, list) or not ids:
        raise ValueError(f"Pass the {what} ids in the new order (at least one).")
    wanted: list[str] = []
    problems: dict[str, list[str]] = {}
    for raw in ids:
        found = _find(raw, active)
        if len(found) == 1:
            if found[0]["id"] in wanted:
                problems.setdefault("listed twice", []).append(str(raw))
            else:
                wanted.append(found[0]["id"])
        elif found:
            problems.setdefault("several have this name, pass the id", []).append(str(raw))
        elif _find(raw, archived):
            problems.setdefault("archived, so not in the order (restore it first)", []).append(str(raw))
        else:
            problems.setdefault(f"not in {where}", []).append(str(raw))
    if problems:
        names = ", ".join(f"{i.get('name')!r} ({i['id']})" for i in active)
        listed = "; ".join(f"{why}: {', '.join(items)}" for why, items in problems.items())
        raise ValueError(f"Nothing was moved. {listed}. The {what}s: {names}.")
    return wanted


@mcp.tool(
    annotations=ToolAnnotations(
        title="Reorder categories",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def reorder_categories(channel_id: str, category_ids: list[str], workspace_id: str) -> dict:
    """Change the order of a channel's categories (as in Edit Channel in the apps).
    Only the order changes: names, contents, settings and archive state stay.

    category_ids: categories of this channel in the new order (ids from get_channel, or exact
        names). The listed ones come first in that order; the others keep their order after
        them. Archived categories have no place in the order (restore_category first).
    The pinned category always shows first in the apps, whatever its place.
    Returns the new order of the channel's categories.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    for attempt in (1, 2):
        channel = _channel(channel_id, workspace_id)
        categories = channel.get("categories") or []
        active = [c for c in categories if not c.get("isArchived")]
        archived = [c for c in categories if c.get("isArchived")]
        wanted = _wanted(category_ids, active, archived, "category", f"channel {channel.get('name')!r}")
        order = wanted + [c["id"] for c in active if c["id"] not in wanted]
        by_id = {c["id"]: c for c in active}
        result = {
            "channel_id": channel["id"],
            "order": [{"id": i, "name": by_id[i].get("name"), "pinned": bool(by_id[i].get("isPinned"))} for i in order],
        }
        if order == [c["id"] for c in active]:
            return {**result, "changed": False}
        body = {
            "channelId": channel["id"],
            "hubProfileId": _hub_profile_id(channel_id, workspace_id, channel=channel),
            # Unchanged, so the backend keeps it byte for byte and the link stays.
            "name": channel.get("name"),
            "categories": [{"categoryId": i, "isArchived": False} for i in order]
            + [{"categoryId": c["id"], "isArchived": True} for c in archived],
        }
        try:
            _raw.call(workspace_id, "PUT", "/api/v1/channels", json=body)
        except srg.exceptions.BadRequestError as exc:
            if "can not be added or deleted" in exc.message and attempt == 1:
                # A category was added or deleted since the read: read again once.
                continue
            raise ValueError(
                f"Nothing was moved: {exc.message}. The order is saved together with the channel's "
                "name, so a name that breaks today's rules (1-50 characters, no / or \\) has to be "
                "fixed first with rename_channel."
            ) from exc
        except srg.exceptions.ConflictError as exc:
            raise ValueError(
                f"Nothing was moved: {exc.message}. The order is saved together with the channel's "
                "name, which another channel of the hub also uses (as its name or link); rename one "
                "of them first (rename_channel)."
            ) from exc
        return {**result, "changed": True}
    raise AssertionError("unreachable")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Reorder channels",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def reorder_channels(hub_profile_id: str, channel_ids: list[str], workspace_id: str) -> dict:
    """Change the order of a hub's channels (the channel list and tabs in the apps).
    Only the order changes.

    channel_ids: channels of this hub in the new order (ids from list_channels, or exact
        names). The listed ones come first in that order; the others keep their order after
        them. Archived channels have no place in the order.
    Only the hub owner or an admin can reorder channels (others get 403).
    Returns the new order.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    channels = _raw.call(
        workspace_id, "GET", f"/api/v1/channels/{hub_profile_id}", params={"includeArchived": "true"}
    ) or []
    channels = [c for c in channels if isinstance(c, dict) and c.get("id")]
    active = [c for c in channels if not c.get("isArchived")]
    archived = [c for c in channels if c.get("isArchived")]
    wanted = _wanted(channel_ids, active, archived, "channel", "this hub")
    names = {c["id"]: c.get("name") for c in active}

    order = [c["id"] for c in active]
    moved: list[str] = []
    for index, channel_id in enumerate(wanted):
        previous = wanted[index - 1] if index else None
        position = order.index(channel_id)
        if (order[position - 1] if position else None) == previous:
            continue
        try:
            _raw.call(
                workspace_id,
                "POST",
                f"/api/v1/channels/{channel_id}/move",
                json={"previousChannelId": previous},
            )
        except srg.exceptions.APIStatusError as exc:
            done = (
                f"Already moved: {', '.join(repr(names[i]) for i in moved)}." if moved else "Nothing was moved."
            )
            if isinstance(exc, srg.exceptions.ForbiddenError):
                raise ValueError(
                    f"Only the hub owner or an admin can reorder channels (403). {done}"
                ) from exc
            raise RuntimeError(f"Moving {names[channel_id]!r} failed: {exc.message}. {done}") from exc
        moved.append(channel_id)
        order.pop(position)
        order.insert(order.index(previous) + 1 if previous else 0, channel_id)

    return {
        "hub_profile_id": hub_profile_id,
        "order": [{"id": i, "name": names[i]} for i in order],
        "moved": len(moved),
    }


# ---- category settings -----------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update category settings",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def update_category_settings(
    channel_id: str,
    category_id: str,
    workspace_id: str,
    pinned: bool | None = None,
    view: str | None = None,
    card_size: str | None = None,
    open_view: str | None = None,
    cover_ratio: str | None = None,
    expandable: bool | None = None,
    progression: bool | None = None,
    sequential: bool | None = None,
    notifications: bool | None = None,
    email: bool | None = None,
) -> dict:
    """Change a category's settings (Edit Category and its Options in the apps). ONLY the
    settings you pass change; the name, contents, sections and every other setting stay.

    pinned: True pins the category to the top of its channel (the channel's other pinned
        category is unpinned: one per channel); False unpins it.
    view: how the category shows on the channel page: "grid", "list" or "scroll" (a
        horizontal row of cards).
    card_size: "large" or "small" cards, for the grid and list views.
    open_view: how the category shows when opened (See all): "grid" or "list".
    cover_ratio: the shape of the card covers, width:height: "16:9", "9:16", "3:2", "2:3",
        "5:4", "4:5", "square" or "original" (or the apps' label with a turn, like
        "16:9 vertical" = 9:16). The same on every device.
    expandable: whether people can open (enlarge) the category.
    progression: show progress (done/not done) on its contents.
    sequential: members must finish the contents in order (turns progression on).
    notifications: push channel members when content is added. email: also email them.
    To rename use rename_category; to archive use archive_category.
    category_id: the category's id (from get_channel) or its exact name.
    Returns all the category's settings after the change, `changed` (False: it was already
    so, nothing written) and which category lost its pin.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    changes = {
        "view": view,
        "card_size": card_size,
        "open_view": open_view,
        "cover_ratio": cover_ratio,
        "expandable": expandable,
        "progression": progression,
        "sequential": sequential,
    }
    if all(v is None for v in (pinned, notifications, email, *changes.values())):
        raise ValueError(
            "Pass at least one setting to change (pinned, view, card_size, open_view, cover_ratio, "
            "expandable, progression, sequential, notifications, email); get_channel shows the current ones."
        )
    channel = _channel(channel_id, workspace_id)
    category = _category(channel, category_id)
    options = with_changes(category.get("options"), **changes)
    same = (
        options == with_changes(category.get("options"))
        and (pinned is None or bool(pinned) == bool(category.get("isPinned")))
        and (notifications is None or bool(notifications) == bool(category.get("notificationsEnabled")))
        and (email is None or bool(email) == bool(category.get("emailEnabled")))
    )
    if same:
        # Already so: no write (the category PUT would still notify every app).
        return {"category_id": category["id"], "name": category.get("name"), **settings_of(category), "changed": False}
    sent = write_category(
        channel_id,
        category,
        workspace_id,
        pinned=pinned,
        notifications=notifications,
        email=email,
        options=options,
    )
    result = {**settings_after(category, sent), "changed": True}
    if pinned:
        unpinned = [
            c.get("name")
            for c in channel.get("categories") or []
            if c.get("isPinned") and c.get("id") != category["id"]
        ]
        if unpinned:
            result["unpinned"] = unpinned
    return result
