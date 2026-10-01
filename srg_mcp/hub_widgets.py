"""Hub profile widgets: the sections of a brand page, read in full and edited one at a time.

The page srgplus.com/<user_name> shows its widgets in order: Text, LinkList,
ContentWidget (cards of contents or Drive assets), HubProfile (other
profiles), Media (a playable video) and Contact. get_hub_profile only lists
them (id, type, title). These tools read them in full and write through the
one-widget endpoints, which keep every other widget exactly as stored
(nothing re-resolved, uploaded icons kept) and every other profile field:

    POST   /api/v1/hub-profiles/{id}/widgets              {widget, position}
    PUT    /api/v1/hub-profiles/{id}/widgets/{widgetId}   <the widget>
    DELETE /api/v1/hub-profiles/{id}/widgets/{widgetId}
    PUT    /api/v1/hub-profiles/{id}/widgets/order        {widgetIds}

All honor If-Match (expected_version): 409, nothing written, when the profile
changed since it was read. Widget bodies are camelCase with "$type" FIRST: the
backend reads the type only from the first property. Removing a widget never
deletes the contents, assets or profiles it shows.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import srg.exceptions
from mcp.types import ToolAnnotations

from srg_mcp import _raw
from srg_mcp._app import mcp
from srg_mcp.hub_profiles import _get, _if_match, _link_out, _links_in

_OBJECT_ID = re.compile(r"^[0-9a-fA-F]{24}$")
_ANY_OBJECT_ID = re.compile(r"[0-9a-fA-F]{24}")

# Backend limits (HubProfile.WidgetsLimit, UpdateProfileValidator, TextWidget).
MAX_WIDGETS = 20
_MAX_TITLE = 150
_MAX_TEXT = 5000
_MAX_REFERENCES = 200

_TYPES = {t.lower(): t for t in ("Text", "LinkList", "ContentWidget", "HubProfile", "Media", "Contact")}
# The create endpoint knows only these; the others need content that exists first.
CREATE_TYPES = ("Text", "LinkList", "Contact")
_CONTACT_TYPES = {"email": "Email", "phone": "Phone"}
# Reference kinds as read back ($type of each item of `references`) that are Drive assets.
_ASSET_KINDS = {"asset", "image", "video", "file", "media", "embed"}
# Read-only expansions of the read shape → the field a write takes instead.
_READ_ONLY = {"references": "referenceIds", "hubProfiles": "hubProfileIds", "playableAsset": "assetId"}
_WRITE_ATTEMPTS = 3


def _base(hub_profile_id: str) -> str:
    return f"/api/v1/hub-profiles/{hub_profile_id}/widgets"


# ---- read shape ------------------------------------------------------------------------


def _ref_kind(value: Any) -> str | None:  # noqa: ANN401
    """A reference $type (write "Content"/"Asset", or read "Image", "Video", ...) → "Content" | "Asset"."""
    kind = str(value or "").strip().lower()
    if kind == "content":
        return "Content"
    return "Asset" if kind in _ASSET_KINDS else None


def _widget_out(widget: dict, position: int) -> dict:
    """One widget as read: the fields a write takes (camelCase, as in content `context`) plus
    read-only expansions (`references`, `hubProfiles`, `playableAsset`)."""
    kind = widget.get("$type")
    out: dict = {"$type": kind, "id": widget.get("id"), "title": widget.get("title"), "position": position}
    if kind == "Text":
        out["content"] = widget.get("content")
    elif kind == "LinkList":
        out["links"] = [_link_out(link) for link in widget.get("links") or []]
    elif kind == "ContentWidget":
        refs = widget.get("references") or []
        reference_type = widget.get("referenceType")
        out["referenceType"] = reference_type
        out["referenceIds"] = [
            {"$type": _ref_kind(r.get("$type")) or reference_type, "id": r.get("id")} for r in refs
        ]
        out["references"] = [{"$type": r.get("$type"), "id": r.get("id"), "name": r.get("name")} for r in refs]
        out["count"] = len(refs)
    elif kind == "HubProfile":
        hubs = widget.get("hubProfiles") or []
        out["hubProfileIds"] = [h.get("id") for h in hubs]
        out["hubProfiles"] = [
            {"id": h.get("id"), "name": h.get("name"), "userName": h.get("userName")} for h in hubs
        ]
    elif kind == "Media":
        asset = widget.get("playableAsset") or {}
        out["assetId"] = asset.get("id")
        out["autoplay"] = bool(widget.get("autoplay"))
        out["playableAsset"] = {"$type": asset.get("$type"), "id": asset.get("id"), "name": asset.get("name")}
    elif kind == "Contact":
        out["contacts"] = [
            {
                "$type": c.get("$type"),
                "id": c.get("id"),
                "title": c.get("title"),
                "details": c.get("details"),
                "has_icon": bool(c.get("iconUrl")),
            }
            for c in widget.get("contacts") or []
        ]
    return out


def _widgets_of(profile: dict) -> list[dict]:
    return [_widget_out(w, i) for i, w in enumerate(profile.get("widgets") or [])]


def _row(widget: dict) -> dict:
    row = {"position": widget["position"], "$type": widget["$type"], "id": widget["id"], "title": widget["title"]}
    if widget["$type"] == "ContentWidget":
        row["count"] = widget["count"]
    return row


def _read(hub_profile_id: str, workspace_id: str) -> tuple[dict, list[dict]]:
    profile = _get(hub_profile_id, workspace_id)
    return profile, _widgets_of(profile)


def _find(widgets: list[dict], widget_id: str) -> dict:
    found = next((w for w in widgets if w["id"] == widget_id), None)
    if found is None:
        raise ValueError(
            f"This hub profile has no widget {widget_id}. Its widgets: {[_row(w) for w in widgets]}"
        )
    return found


def _written(hub_profile_id: str, workspace_id: str, widget_id: str | None) -> dict:
    """Read the profile back after a write: its version, the written widget, the new order."""
    profile, widgets = _read(hub_profile_id, workspace_id)
    out: dict = {"hub_profile_id": hub_profile_id, "version": profile.get("version")}
    if widget_id:
        out["widget"] = next((w for w in widgets if w["id"] == widget_id), None)
    out["widgets"] = [_row(w) for w in widgets]
    return out


# ---- write shape -----------------------------------------------------------------------


def _object_id(value: Any, what: str) -> str:  # noqa: ANN401
    text = str(value if value is not None else "").strip()
    if not _OBJECT_ID.match(text):
        raise ValueError(f"{what} must be an SRG+ id (24 hex characters), not {value!r}.")
    return text


def _title_in(value: Any) -> str | None:  # noqa: ANN401
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"A widget title must be text, not {value!r}.")
    title = value.strip()
    if len(title) > _MAX_TITLE:
        raise ValueError(f"A widget title is at most {_MAX_TITLE} characters; got {len(title)}.")
    return title or None


def _unique(ids: list[str], what: str) -> None:
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise ValueError(f"Each {what} can be listed once; repeated: {repeated}.")


def _references_in(widget: dict) -> tuple[str, list[dict]]:
    declared = widget.get("referenceType")
    reference_type = None
    if declared is not None:
        reference_type = {"content": "Content", "asset": "Asset"}.get(str(declared).strip().lower())
        if reference_type is None:
            raise ValueError(f'referenceType must be "Content" or "Asset", not {declared!r}.')
    rows = widget.get("referenceIds")
    if rows is None:
        raise ValueError(
            'A ContentWidget needs "referenceIds": [{"$type": "Content", "id": "<content id>"}, ...] '
            "(set_hub_profile_content_widget takes plain content ids)."
        )
    if not isinstance(rows, list):
        raise ValueError("referenceIds must be a list.")
    refs: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            kind = _ref_kind(row.get("$type")) if row.get("$type") is not None else reference_type or "Content"
            if kind is None:
                raise ValueError(f'Each reference $type must be "Content" or "Asset", not {row.get("$type")!r}.')
            ref_id = row.get("id")
        else:
            kind, ref_id = reference_type or "Content", row
        refs.append({"$type": kind, "id": _object_id(ref_id, "Each reference id")})
    if reference_type is None:
        kinds = {r["$type"] for r in refs}
        if len(kinds) > 1:
            raise ValueError("A ContentWidget shows either contents or Drive assets, not both.")
        reference_type = next(iter(kinds), "Content")
    other = [r["id"] for r in refs if r["$type"] != reference_type]
    if other:
        raise ValueError(
            f'This ContentWidget has referenceType "{reference_type}", so every reference must be '
            f"a {reference_type.lower()}; these are not: {other}."
        )
    _unique([r["id"] for r in refs], "reference")
    if len(refs) > _MAX_REFERENCES:
        raise ValueError(f"A ContentWidget holds at most {_MAX_REFERENCES} items; got {len(refs)}.")
    return reference_type, refs


def _hub_profile_ids_in(widget: dict) -> list[str]:
    raw = widget.get("hubProfileIds")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            'A HubProfile widget needs "hubProfileIds": ["<hub profile id>", ...] (an array, even for one).'
        )
    ids = [_object_id(value, "Each hubProfileIds item") for value in raw]
    _unique(ids, "hub profile")
    return ids


def _contacts_in(widget: dict) -> list[dict]:
    contacts = widget.get("contacts")
    if not isinstance(contacts, list) or not contacts:
        raise ValueError('A Contact widget needs "contacts": [{"$type": "Email" | "Phone", "details": "..."}].')
    rows = []
    for contact in contacts:
        if not isinstance(contact, dict):
            raise ValueError(f'Each contact is {{"$type": "Email" | "Phone", "details": "..."}}, not {contact!r}.')
        kind = _CONTACT_TYPES.get(str(contact.get("$type") or "").strip().lower())
        if kind is None:
            raise ValueError(f'A contact $type is "Email" or "Phone", not {contact.get("$type")!r}.')
        details = str(contact.get("details") or "").strip()
        if not details:
            raise ValueError(f"Each contact needs its details (the address or number); got {contact!r}.")
        row: dict = {"$type": kind}
        if contact.get("id"):
            row["id"] = _object_id(contact["id"], "A contact id")
        row["title"] = _title_in(contact.get("title"))
        row["details"] = details
        rows.append(row)
    return rows


def _from_read_shape(widget: dict) -> dict:
    """Map read-only expansions onto the field a write takes (a write field that is present wins)."""
    out = dict(widget)
    if out.get("referenceIds") is None and isinstance(out.get("references"), list):
        out["referenceIds"] = [
            {"$type": _ref_kind(r.get("$type")) or r.get("$type"), "id": r.get("id")} if isinstance(r, dict) else r
            for r in out["references"]
        ]
    if out.get("hubProfileIds") is None and isinstance(out.get("hubProfiles"), list):
        out["hubProfileIds"] = [h.get("id") if isinstance(h, dict) else h for h in out["hubProfiles"]]
    if out.get("assetId") is None and isinstance(out.get("playableAsset"), dict):
        out["assetId"] = out["playableAsset"].get("id")
    for key in _READ_ONLY:
        out.pop(key, None)
    return out


def widget_in(widget: Any, *, keep_id: bool = True, allowed: tuple[str, ...] | None = None) -> dict:  # noqa: ANN401
    """An agent widget (write or read shape) → the backend body: camelCase, "$type" first.

    keep_id: send the widget's `id` (existing widgets in a whole-list write); a new widget
    gets its id from SRG+. Raises ValueError, before anything is written, on a bad widget.
    """
    if not isinstance(widget, dict):
        raise ValueError(f'A widget is an object such as {{"$type": "Text", "content": "..."}}, not {widget!r}.')
    widget = _from_read_shape(widget)
    raw_type = widget.get("$type", widget.get("type"))
    kind = _TYPES.get(str(raw_type or "").strip().lower())
    if kind is None:
        raise ValueError(f"A widget $type is one of {', '.join(_TYPES.values())}; got {raw_type!r}.")
    if allowed is not None and kind not in allowed:
        raise ValueError(
            f"A {kind} widget cannot be set here (only {', '.join(allowed)}); "
            "add it afterwards with add_hub_profile_widget."
        )
    out: dict = {"$type": kind}
    if keep_id and widget.get("id"):
        out["id"] = _object_id(widget["id"], "A widget id")
    out["title"] = _title_in(widget.get("title"))
    if kind == "Text":
        content = widget.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError('A Text widget needs "content": "<markdown>" (1-5000 characters).')
        if len(content) > _MAX_TEXT:
            raise ValueError(f"A hub profile Text widget holds at most {_MAX_TEXT} characters; got {len(content)}.")
        out["content"] = content
    elif kind == "LinkList":
        links = widget.get("links")
        if not isinstance(links, list):
            raise ValueError('A LinkList widget needs "links": [{"title": "...", "url": "https://..."}, ...].')
        out["links"] = _links_in(links)
    elif kind == "ContentWidget":
        out["referenceType"], out["referenceIds"] = _references_in(widget)
    elif kind == "HubProfile":
        out["hubProfileIds"] = _hub_profile_ids_in(widget)
    elif kind == "Media":
        if widget.get("assetId") is None:
            raise ValueError('A Media widget needs "assetId": "<id of a playable video in the hub\'s Drive>".')
        out["assetId"] = _object_id(widget["assetId"], "assetId")
        autoplay = widget.get("autoplay", False)
        if not isinstance(autoplay, bool):
            raise ValueError(f"autoplay is true or false, not {autoplay!r}.")
        out["autoplay"] = autoplay
    else:
        out["contacts"] = _contacts_in(widget)
    return out


def widgets_in(widgets: Any, *, allowed: tuple[str, ...] | None = None, keep_id: bool = True) -> list[dict]:  # noqa: ANN401
    """A whole widget list → backend bodies (validated before anything is written)."""
    if not isinstance(widgets, list):
        raise ValueError("widgets must be a list of widget objects.")
    if len(widgets) > MAX_WIDGETS:
        raise ValueError(f"A hub profile has at most {MAX_WIDGETS} widgets; got {len(widgets)}.")
    rows = [widget_in(w, keep_id=keep_id, allowed=allowed) for w in widgets]
    _unique([r["id"] for r in rows if "id" in r], "widget id")
    return rows


def _with_fresh_profile(
    hub_profile_id: str,
    workspace_id: str,
    expected_version: int | None,
    write: Callable[[dict, list[dict], int | None], Any],
) -> Any:  # noqa: ANN401
    """Run write(profile, widgets, version) on a fresh read, sending If-Match = version.

    The write builds its body from that read, so a write must never land on a profile that
    changed after it: with expected_version that is a 409 for the caller; without it the
    profile is read again and the write re-applied on top of the change.
    """
    for attempt in range(1, _WRITE_ATTEMPTS + 1):
        profile, widgets = _read(hub_profile_id, workspace_id)
        version = expected_version if expected_version is not None else profile.get("version")
        try:
            return write(profile, widgets, version)
        except srg.exceptions.ConflictError:
            if expected_version is not None or attempt == _WRITE_ATTEMPTS:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


# ---- tools -----------------------------------------------------------------------------

_SHAPES = """\
Widget shapes (camelCase, as in a content's `context`):
  • {"$type": "Text", "title": null, "content": "<markdown, 1-5000 chars>"}
  • {"$type": "LinkList", "title": null, "links": [{"title": "Instagram",
     "url": "https://..."}]}  (KnownLink by default; max 20, unique titles)
  • {"$type": "ContentWidget", "title": "Playbooks", "referenceType": "Content",
     "referenceIds": [{"$type": "Content", "id": "<content id>"}]}  (cards of
     contents in that order; "Asset" + Drive asset ids for files)
  • {"$type": "HubProfile", "title": null, "hubProfileIds": ["<hub profile id>"]}
  • {"$type": "Media", "title": null, "assetId": "<playable video id>", "autoplay": false}
  • {"$type": "Contact", "title": null, "contacts": [{"$type": "Email" | "Phone",
     "title": "...", "details": "hi@brand.com"}]}
title is optional (1-150 chars). A widget read with get_hub_profile_widgets can be
sent back as is: `references` / `hubProfiles` / `playableAsset` are read-only and
only used when `referenceIds` / `hubProfileIds` / `assetId` is missing."""


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get hub profile widgets",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_hub_profile_widgets(hub_profile_id: str, workspace_id: str) -> dict:
    """Read every widget of a hub profile page (srgplus.com/<user_name>) in full,
    in display order (the link list included).

    Each widget has $type, id, title, position (0 = first) and its fields:
      • Text: content (Markdown).
      • LinkList: links [{$type, id, title, url, platform, icon_url}].
      • ContentWidget: referenceType ("Content" or "Asset"), referenceIds
        [{$type, id}] (what a write takes), references [{$type, id, name}]
        (expanded, read-only: $type is "Content" or the asset kind Image /
        Video / File / Media / Embed; names as of the last widget write) and
        count.
      • HubProfile: hubProfileIds and hubProfiles [{id, name, userName}].
      • Media: assetId, autoplay, playableAsset {$type, id, name}.
      • Contact: contacts [{$type ("Email" | "Phone"), id, title, details, has_icon}].
    Any widget can be sent back to update_hub_profile_widget or
    update_hub_profile(widgets=...) as read.
    Pass `version` as expected_version to the widget writes to get a 409
    instead of overwriting someone else's edit.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns {"hub_profile_id", "version", "count", "widgets": [...]}.
    """
    profile, widgets = _read(hub_profile_id, workspace_id)
    return {
        "hub_profile_id": hub_profile_id,
        "version": profile.get("version"),
        "count": len(widgets),
        "widgets": widgets,
    }


@mcp.tool(
    description=f"""Add ONE widget to a hub profile page. Every other widget and
every other profile field stays exactly as it is.

widget: the new widget (its `id`, if any, is ignored: SRG+ gives it one).
position: where it goes, 0 = first; omit to add it at the end. A page has at
    most {MAX_WIDGETS} widgets.
expected_version: the `version` from get_hub_profile_widgets / get_hub_profile
    → 409 (nothing written) if someone changed the profile since.
workspace_id: target workspace ID — get available IDs from list_workspaces()

{_SHAPES}

Every id must exist (a missing content or asset is a 404 naming it). For a
list of contents, set_hub_profile_content_widget is simpler.
Returns {{"hub_profile_id", "version", "widget" (as read back),
"widgets": [{{position, $type, id, title}}] (the new order)}}.
""",
    annotations=ToolAnnotations(
        title="Add hub profile widget",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    ),
)
def add_hub_profile_widget(
    hub_profile_id: str,
    workspace_id: str,
    widget: dict,
    position: int | None = None,
    expected_version: int | None = None,
) -> dict:
    body: dict = {"widget": widget_in(widget, keep_id=False)}
    if position is not None:
        if int(position) < 0:
            raise ValueError("position is 0 (first) or more; omit it to add the widget at the end.")
        body["position"] = int(position)
    data = _raw.call(
        workspace_id, "POST", _base(hub_profile_id), json=body, headers=_if_match(expected_version)
    ) or {}
    return _written(hub_profile_id, workspace_id, data.get("widgetId"))


@mcp.tool(
    description=f"""Change ONE widget of a hub profile page in place (same id,
same position). Only the fields you pass change; the widget's other fields and
every other widget stay as they are. A list you pass (links, referenceIds,
hubProfileIds, contacts) REPLACES that list.

widget_id: from get_hub_profile_widgets.
widget: the fields to change, e.g. {{"title": "Reports"}} or
    {{"referenceIds": [...]}}. A whole widget read with get_hub_profile_widgets
    works too. The type cannot change: remove the widget and add a new one.
expected_version: the `version` from get_hub_profile_widgets → 409 (nothing
    written) if someone changed the profile since. Without it the change is
    applied to the latest profile.
workspace_id: target workspace ID — get available IDs from list_workspaces()

{_SHAPES}

Returns {{"hub_profile_id", "version", "widget" (as read back), "widgets"}}.
""",
    annotations=ToolAnnotations(
        title="Update hub profile widget",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
def update_hub_profile_widget(
    hub_profile_id: str,
    widget_id: str,
    widget: dict,
    workspace_id: str,
    expected_version: int | None = None,
) -> dict:
    if not isinstance(widget, dict) or not widget:
        raise ValueError('widget holds the fields to change, e.g. {"title": "Reports"}.')
    if widget.get("id") and widget["id"] != widget_id:
        raise ValueError(f"widget.id ({widget['id']}) is not widget_id ({widget_id}).")
    changes = _from_read_shape({k: v for k, v in widget.items() if k not in ("id", "position", "count")})

    def write(_profile: dict, widgets: list[dict], version: int | None) -> None:
        stored = _find(widgets, widget_id)
        kind = changes.get("$type", changes.get("type"))
        if kind is not None and _TYPES.get(str(kind).strip().lower()) != stored["$type"]:
            raise ValueError(
                f"Widget {widget_id} is a {stored['$type']} widget; its type cannot change. "
                "Remove it and add a new widget instead."
            )
        # The stored widget as read, with the changes on top; validated once, as a whole.
        body = widget_in({**stored, **changes}, keep_id=False)
        _raw.call(
            workspace_id, "PUT", f"{_base(hub_profile_id)}/{widget_id}", json=body, headers=_if_match(version)
        )

    _with_fresh_profile(hub_profile_id, workspace_id, expected_version, write)
    return _written(hub_profile_id, workspace_id, widget_id)


def _content_ids_in(content_ids: Any) -> tuple[list[str], list[dict]]:  # noqa: ANN401
    if not isinstance(content_ids, list):
        raise ValueError("content_ids must be a list of content ids, in the order to show them.")
    wanted: list[str] = []
    skipped: list[dict] = []
    for raw in content_ids:
        content_id = str(raw).strip()
        if not _OBJECT_ID.match(content_id):
            skipped.append({"id": raw, "reason": "not a valid SRG+ id (24 hex characters)"})
        elif content_id in wanted:
            skipped.append({"id": content_id, "reason": "listed twice; kept the first position"})
        else:
            wanted.append(content_id)
    if content_ids and not wanted:
        raise ValueError(f"None of content_ids is an SRG+ content id; nothing was changed. {skipped}")
    if len(wanted) > _MAX_REFERENCES:
        raise ValueError(f"A ContentWidget holds at most {_MAX_REFERENCES} contents; got {len(wanted)}.")
    return wanted, skipped


def _content_target(widgets: list[dict], widget_id: str | None, title: str | None) -> dict | None:
    """The content widget to fill: by id, else by exact title, else the only one. None = create."""
    if widget_id:
        target = _find(widgets, widget_id)
        if target["$type"] != "ContentWidget":
            raise ValueError(f"Widget {widget_id} is a {target['$type']} widget, not a ContentWidget.")
        if target.get("referenceType") != "Content":
            raise ValueError(
                f"Widget {widget_id} shows Drive assets (referenceType Asset), not contents; "
                "change it with update_hub_profile_widget."
            )
        return target
    candidates = [w for w in widgets if w["$type"] == "ContentWidget" and w.get("referenceType") == "Content"]
    if title:
        candidates = [w for w in candidates if (w.get("title") or "") == title]
    if len(candidates) > 1:
        rows = [{"id": w["id"], "title": w["title"], "count": w["count"]} for w in candidates]
        raise ValueError(
            f"This hub profile has {len(candidates)} content widgets{' titled ' + repr(title) if title else ''}; "
            f"pass widget_id to pick one: {rows}"
        )
    return candidates[0] if candidates else None


@mcp.tool(
    annotations=ToolAnnotations(
        title="Set hub profile content widget",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def set_hub_profile_content_widget(
    hub_profile_id: str,
    workspace_id: str,
    content_ids: list[str],
    title: str | None = None,
    widget_id: str | None = None,
    position: int | None = None,
    expected_version: int | None = None,
) -> dict:
    """Show these contents as cards on a hub profile page, in this order (the
    page's ContentWidget). Like set_featured_contents for a content.

    REPLACES the widget's contents (not a merge): afterwards it holds exactly
    content_ids, in that order (first id = first card). To add one: read it
    with get_hub_profile_widgets, add the id, send the full list. [] empties
    the widget (remove_hub_profile_widget deletes it). The contents themselves
    are never changed or deleted.

    Which widget:
      • widget_id → that ContentWidget (title renames it when passed).
      • title only → the content widget with exactly that title; CREATED if
        there is none.
      • neither → the page's only content widget; created (untitled) if there
        is none; an error listing them if there are several.
    title: the heading above the cards; "" removes it; omitted keeps it.
    position: where a NEW widget goes (0 = first, default the end); an
        existing one stays put (reorder_hub_profile_widgets moves it).
    expected_version: the `version` from get_hub_profile_widgets → 409 (nothing
        written) if someone changed the profile since.
    Ids that are not valid, listed twice, or not found in SRG+ are SKIPPED and
    listed in `skipped` with the reason; the rest still goes through.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns {"hub_profile_id", "widget_id", "created", "title", "content_ids"
    (final order, read back), "references" [{$type, id, name}], "count",
    "skipped", "in_requested_order", "version", "widgets" (page order)}.
    """
    wanted, skipped = _content_ids_in(content_ids)
    if position is not None and int(position) < 0:
        raise ValueError("position is 0 (first) or more; omit it to add the widget at the end.")
    match_title = _title_in(title) if title is not None else None
    ids = list(wanted)

    def write(_profile: dict, widgets: list[dict], version: int | None) -> tuple[str, bool]:
        target = _content_target(widgets, widget_id, match_title)
        if title is None:
            new_title = target["title"] if target else None
        else:
            new_title = match_title
        body = {
            "$type": "ContentWidget",
            "title": new_title,
            "referenceType": "Content",
            "referenceIds": [{"$type": "Content", "id": cid} for cid in ids],
        }
        if target is None:
            payload: dict = {"widget": body}
            if position is not None:
                payload["position"] = int(position)
            data = _raw.call(
                workspace_id, "POST", _base(hub_profile_id), json=payload, headers=_if_match(version)
            ) or {}
            return data.get("widgetId"), True
        _raw.call(
            workspace_id, "PUT", f"{_base(hub_profile_id)}/{target['id']}", json=body, headers=_if_match(version)
        )
        return target["id"], False

    try:
        written_id, created = _with_fresh_profile(hub_profile_id, workspace_id, expected_version, write)
    except srg.exceptions.NotFoundError as exc:
        # The backend names the ids it could not find (nothing was written): skip them and
        # write the rest, unless that would leave none of the requested contents.
        named = set(_ANY_OBJECT_ID.findall(exc.message))
        missing = [cid for cid in ids if cid in named]
        if not missing or "reference" not in exc.message.lower():
            raise
        if len(missing) == len(ids):
            raise ValueError(
                f"None of the content ids was found in SRG+ (deleted, or not contents): {missing}. "
                "Nothing was changed."
            ) from exc
        skipped.extend({"id": cid, "reason": "not found in SRG+ (deleted, or not a content)"} for cid in missing)
        ids[:] = [cid for cid in ids if cid not in missing]
        written_id, created = _with_fresh_profile(hub_profile_id, workspace_id, expected_version, write)

    out = _written(hub_profile_id, workspace_id, written_id)
    widget = out.pop("widget") or {}
    final = [r["id"] for r in widget.get("references") or []]
    return {
        "hub_profile_id": hub_profile_id,
        "widget_id": written_id,
        "created": created,
        "title": widget.get("title"),
        "content_ids": final,
        "references": widget.get("references") or [],
        "count": len(final),
        "skipped": skipped,
        "in_requested_order": final == ids,
        "version": out["version"],
        "widgets": out["widgets"],
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Remove hub profile widget",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def remove_hub_profile_widget(
    hub_profile_id: str,
    widget_id: str,
    workspace_id: str,
    expected_version: int | None = None,
) -> dict:
    """Remove ONE widget from a hub profile page. Only the widget goes: the
    contents, Drive assets and profiles it showed are NOT deleted, and every
    other widget stays as it is. Removing the LinkList removes the page's links.

    widget_id: from get_hub_profile_widgets.
    expected_version: the `version` from get_hub_profile_widgets → 409 (nothing
        written) if someone changed the profile since.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns {"hub_profile_id", "removed" ({$type, id, title, ...} as it was),
    "version", "widgets" (the page order after)}.
    """
    _profile, widgets = _read(hub_profile_id, workspace_id)
    removed = _find(widgets, widget_id)
    _raw.call(
        workspace_id, "DELETE", f"{_base(hub_profile_id)}/{widget_id}", headers=_if_match(expected_version)
    )
    out = _written(hub_profile_id, workspace_id, None)
    return {"hub_profile_id": hub_profile_id, "removed": removed, "version": out["version"], "widgets": out["widgets"]}


@mcp.tool(
    annotations=ToolAnnotations(
        title="Reorder hub profile widgets",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def reorder_hub_profile_widgets(
    hub_profile_id: str,
    widget_ids: list[str],
    workspace_id: str,
    expected_version: int | None = None,
) -> dict:
    """Reorder the widgets of a hub profile page. No widget changes.

    widget_ids: widget ids in the order to show them (first = top of the page).
        Widgets you leave out keep their relative order after these, so
        [id] alone moves that widget to the top.
    expected_version: the `version` from get_hub_profile_widgets → 409 (nothing
        written) if someone changed the profile since.
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns {"hub_profile_id", "version", "widgets": [{position, $type, id,
    title}]} in the new order.
    """
    if not isinstance(widget_ids, list) or not widget_ids:
        raise ValueError("widget_ids lists the widget ids in the order to show them.")
    ids = [_object_id(widget_id, "Each widget id") for widget_id in widget_ids]
    _unique(ids, "widget")
    _raw.call(
        workspace_id,
        "PUT",
        f"{_base(hub_profile_id)}/order",
        json={"widgetIds": ids},
        headers=_if_match(expected_version),
    )
    out = _written(hub_profile_id, workspace_id, None)
    return {"hub_profile_id": hub_profile_id, "version": out["version"], "widgets": out["widgets"]}
