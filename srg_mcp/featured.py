"""Featured Assets / Featured Content of a content item (SRGDEV-756).

Every content item has two built-in categories, shown in the app under the
content's "More" menu: **Featured Content** (``$type`` "Content") and
**Featured Assets** (``$type`` "Asset"). Each holds ordered sections:

* exactly one unnamed default section (``SingleContentSection``), always first;
* any number of NAMED sections (``Section``, unique names), e.g. "Version 1",
  "Version 2" — a new one is placed right after the default, so the newest
  named section shows first.

``update_content(categories=...)`` can only change a category's ``options``:
the API ignores ``references``/``sections`` there. Items and sections are
written through their own endpoints, which these tools wrap:

    POST   /api/v1/contents/{id}/{kind}/sections                      {name} -> {id}
    PUT    /api/v1/contents/{id}/{kind}/sections/{sectionId}          {name}
    DELETE /api/v1/contents/{id}/{kind}/sections/{sectionId}
    POST   /api/v1/contents/{id}/{kind}/sections/{sectionId}/move     {previousSectionId}
    GET    /api/v1/contents/{id}/{kind}/references?pageSize&order&cursor
    POST   /api/v1/contents/{id}/{kind}/{sectionId}/references        {referenceIds}
    DELETE /api/v1/contents/{id}/{kind}/{sectionId}/references/{refId}
    POST   /api/v1/contents/{id}/{kind}/{sectionId}/references/move   {referenceId, previousReferenceId}

Backend rules these tools work with, not against:

* one item can sit in only ONE section of a category (adding it to a second
  section is a 409), so it is reported as skipped rather than moved;
* an added batch goes to the TOP of its section, so order is fixed with moves;
* reference/section writes do not bump the content ``version``, so
  ``expected_version`` cannot protect them.
"""

from __future__ import annotations

import re

import srg.exceptions
from mcp.types import ToolAnnotations

from srg_mcp import _raw
from srg_mcp._app import mcp

_KINDS = {
    "asset": "Asset",
    "assets": "Asset",
    "featured assets": "Asset",
    "content": "Content",
    "contents": "Content",
    "featured content": "Content",
}
_LABELS = {"Asset": "Featured Assets", "Content": "Featured Content"}
_OBJECT_ID = re.compile(r"^[0-9a-fA-F]{24}$")
_MAX_ITEMS = 200
_PAGE_SIZE = 500
_MAX_PAGES = 20


def _kind(value: str) -> str:
    kind = _KINDS.get(str(value).strip().lower())
    if kind is None:
        raise ValueError(
            f'kind must be "Asset" (Featured Assets) or "Content" (Featured Content), got {value!r}.'
        )
    return kind


def _base(content_id: str, kind: str) -> str:
    return f"/api/v1/contents/{content_id}/{kind}"


def _category(workspace_id: str, content_id: str, kind: str) -> dict:
    data = _raw.call(workspace_id, "GET", f"/api/v2/contents/{content_id}") or {}
    category = next(
        (c for c in data.get("categories") or [] if c.get("$type") == kind), None
    )
    if category is None:
        raise ValueError(f"Content {content_id} has no {_LABELS[kind]} category.")
    return category


def _sections(category: dict) -> list[dict]:
    """The category's sections in display order: [{id, name, default}]."""
    ordered = sorted(category.get("sections") or [], key=lambda s: str(s.get("cursor") or ""))
    return [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "default": s.get("$type") == "SingleContentSection",
        }
        for s in ordered
    ]


def _row(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "type": item.get("$type"),
        "section_id": (item.get("section") or {}).get("id"),
    }


def _refs(workspace_id: str, content_id: str, kind: str) -> list[dict]:
    """Every item in the category, ordered by section then position.

    Reads the paged references endpoint (exact, not the 15-item cache that
    get_content_v2 carries). That endpoint refuses PRIVATE content to a key
    without a user (403); then the cache is used when it holds every item.
    """
    rows: list[dict] = []
    cursor: str | None = None
    try:
        for _ in range(_MAX_PAGES):
            params: dict = {"pageSize": _PAGE_SIZE, "order": "Ascending"}
            if cursor:
                params["cursor"] = cursor
            page = (
                _raw.call(
                    workspace_id, "GET", f"{_base(content_id, kind)}/references", params=params
                )
                or {}
            )
            rows.extend(_row(item) for item in page.get("items") or [])
            cursor = page.get("nextCursor")
            if not page.get("hasNext") or not cursor:
                return rows
    except srg.exceptions.ForbiddenError:
        return _cached_refs(workspace_id, content_id, kind)
    raise RuntimeError(
        f"{_LABELS[kind]} of content {content_id} has more than "
        f"{_PAGE_SIZE * _MAX_PAGES} items; refusing to guess its contents."
    )


def _cached_refs(workspace_id: str, content_id: str, kind: str) -> list[dict]:
    category = _category(workspace_id, content_id, kind)
    rows = [_row(item) for item in category.get("references") or []]
    complete = not category.get("hasNext") and len(rows) >= int(category.get("totalCount") or 0)
    if not complete or any(r["section_id"] is None for r in rows):
        raise RuntimeError(
            f"SRG+ refused to list the {_LABELS[kind]} of this private content to this "
            "key (403), and the copy in get_content_v2 is partial. Use a personal API "
            "key (srgplus_u_...) of a user with access to the hub."
        )
    return rows


def _in_section(refs: list[dict], section_id: str) -> list[str]:
    return [r["id"] for r in refs if r["section_id"] == section_id]


def _section_label(section: dict | None) -> str:
    if section is None:
        return "another section"
    return "the unnamed default section" if section["default"] else f"section {section['name']!r}"


def _resolve_section(
    workspace_id: str,
    content_id: str,
    kind: str,
    sections: list[dict],
    section_name: str | None,
    section_id: str | None,
) -> tuple[dict, bool]:
    """Find (or create / rename) the target section; returns (section, created)."""
    name = section_name.strip() if section_name is not None else None
    if name == "":
        raise ValueError("section_name must not be blank; omit it to use the default section.")

    if section_id is not None:
        section = next((s for s in sections if s["id"] == section_id), None)
        if section is None:
            known = [{"id": s["id"], "name": s["name"]} for s in sections]
            raise ValueError(
                f"No section {section_id} in {_LABELS[kind]} of content {content_id}. "
                f"Sections: {known}"
            )
        if name is not None and name != section["name"]:
            if section["default"]:
                raise ValueError(
                    "The unnamed default section cannot be renamed. Omit section_id to "
                    "create a new named section instead."
                )
            _raw.call(
                workspace_id,
                "PUT",
                f"{_base(content_id, kind)}/sections/{section_id}",
                json={"name": name},
            )
            section = {**section, "name": name}
        return section, False

    if name is None:
        default = next((s for s in sections if s["default"]), None)
        if default is None:
            raise RuntimeError(
                f"{_LABELS[kind]} of content {content_id} has no default section; "
                "pass section_name to create a named one."
            )
        return default, False

    existing = next((s for s in sections if s["name"] == name), None)
    if existing is not None:
        return existing, False
    created = (
        _raw.call(
            workspace_id,
            "POST",
            f"{_base(content_id, kind)}/sections",
            json={"name": name},
        )
        or {}
    )
    if not created.get("id"):
        raise RuntimeError(f"SRG+ created section {name!r} but returned no id; re-list sections.")
    return {"id": created["id"], "name": name, "default": False}, True


def _add(
    workspace_id: str, content_id: str, kind: str, section_id: str, ids: list[str]
) -> tuple[list[str], list[dict]]:
    """Add ids to a section; returns (added, [{id, reason}] for the rest).

    One batch call first; if the batch is refused, retry per item so a single
    blocked id (another hub, not found, no access) does not sink the others.
    """
    if not ids:
        return [], []
    path = f"{_base(content_id, kind)}/{section_id}/references"
    try:
        _raw.call(workspace_id, "POST", path, json={"referenceIds": ids})
        return list(ids), []
    except srg.exceptions.APIStatusError as batch_error:
        if len(ids) == 1:
            return [], [{"id": ids[0], "reason": batch_error.message}]
    added: list[str] = []
    failed: list[dict] = []
    for ref_id in ids:
        try:
            _raw.call(workspace_id, "POST", path, json={"referenceIds": [ref_id]})
            added.append(ref_id)
        except srg.exceptions.APIStatusError as exc:
            failed.append({"id": ref_id, "reason": exc.message})
    return added, failed


def _reorder(
    workspace_id: str,
    content_id: str,
    kind: str,
    section_id: str,
    current: list[str],
    wanted: list[str],
) -> None:
    """Move items so the section starts with ``wanted`` in that order.

    ``current`` is the section's actual order; each move is mirrored locally
    so only the items that are out of place get a call.
    """
    order = list(current)
    path = f"{_base(content_id, kind)}/{section_id}/references/move"
    for index, ref_id in enumerate(wanted):
        previous = wanted[index - 1] if index else None
        position = order.index(ref_id)
        actual_previous = order[position - 1] if position else None
        if actual_previous == previous:
            continue
        _raw.call(
            workspace_id,
            "POST",
            path,
            json={"referenceId": ref_id, "previousReferenceId": previous},
        )
        order.pop(position)
        order.insert(order.index(previous) + 1 if previous else 0, ref_id)


def _set_featured(
    kind: str,
    content_id: str,
    workspace_id: str,
    ids: list[str],
    section_name: str | None,
    section_id: str | None,
) -> dict:
    if len(ids) > _MAX_ITEMS:
        raise ValueError(f"At most {_MAX_ITEMS} items per section; split the list.")

    skipped: list[dict] = []
    wanted: list[str] = []
    for raw_id in ids:
        ref_id = str(raw_id).strip()
        if not _OBJECT_ID.match(ref_id):
            skipped.append({"id": raw_id, "reason": "not a valid SRG+ id (24 hex characters)"})
        elif ref_id in wanted:
            skipped.append({"id": ref_id, "reason": "listed twice; kept the first position"})
        else:
            wanted.append(ref_id)

    sections = _sections(_category(workspace_id, content_id, kind))
    section, created = _resolve_section(
        workspace_id, content_id, kind, sections, section_name, section_id
    )
    sid = section["id"]
    by_id = {s["id"]: s for s in sections}

    refs = _refs(workspace_id, content_id, kind)
    current = _in_section(refs, sid)
    elsewhere = {r["id"]: r["section_id"] for r in refs if r["section_id"] != sid}

    to_add: list[str] = []
    for ref_id in wanted:
        if ref_id in elsewhere:
            skipped.append(
                {
                    "id": ref_id,
                    "reason": (
                        f"already in {_section_label(by_id.get(elsewhere[ref_id]))} of this "
                        f"content's {_LABELS[kind]}; an item can be in only one section — "
                        "remove it there first"
                    ),
                }
            )
        elif ref_id not in current:
            to_add.append(ref_id)

    # Add before removing: a refused add must not leave the section emptier.
    added, failed = _add(workspace_id, content_id, kind, sid, to_add)
    skipped.extend(failed)

    keep = [ref_id for ref_id in wanted if ref_id in current or ref_id in added]
    removed: list[str] = []
    not_removed: list[dict] = []
    for ref_id in current:
        if ref_id in keep:
            continue
        try:
            _raw.call(
                workspace_id,
                "DELETE",
                f"{_base(content_id, kind)}/{sid}/references/{ref_id}",
            )
            removed.append(ref_id)
        except srg.exceptions.APIStatusError as exc:
            not_removed.append({"id": ref_id, "reason": exc.message})

    # Added items land at the top of the section (per-item retries even in
    # reverse), so read the real order back and fix it with moves.
    actual = _in_section(_refs(workspace_id, content_id, kind), sid)
    keep = [ref_id for ref_id in keep if ref_id in actual]
    _reorder(workspace_id, content_id, kind, sid, actual, keep)

    final = _in_section(_refs(workspace_id, content_id, kind), sid)
    result = {
        "content_id": content_id,
        "featured": _LABELS[kind],
        "section_id": sid,
        "section_name": section["name"],
        "created_section": created,
        "ids": final,
        "count": len(final),
        "added": len(added),
        "removed": len(removed),
        "skipped": skipped,
        "in_requested_order": final[: len(keep)] == keep,
    }
    if not_removed:
        result["not_removed"] = not_removed
    return result


_SET_RULES = """
REPLACES the section's items (not a merge): afterwards the section holds
exactly the ids you pass, in that order (first id = shown first). Items of
OTHER sections are never touched. An empty list clears the section. To add
one item: list_featured_sections, append the id, send the full list back.

Which section:
  • section_name only → the named section with that exact name; CREATED if
    missing. A new section is placed first among the named ones (right after
    the unnamed default), so the newest version shows first. Change the order
    with reorder_featured_sections.
  • section_id → that existing section (ids from list_featured_sections);
    with section_name too, the section is renamed.
  • neither → the unnamed default section.

Items that cannot be placed are SKIPPED and listed in `skipped` with the
reason; the rest still go through. Typical reasons: the id is already in
another section of this content (an item can be in only one section — remove
it there first), it belongs to a hub you cannot edit (403), or it does not
exist (404). Always check `skipped`.

Not version-checked: these writes do not change the content `version`, so
expected_version does not apply. Avoid two writers on one section at once.

workspace_id: target workspace ID — get available IDs from list_workspaces()
Returns {"content_id", "featured", "section_id", "section_name",
"created_section", "ids" (final order, read back from SRG+), "count",
"added", "removed", "skipped": [{"id", "reason"}], "in_requested_order"}.
get_content_v2 shows at most 15 items per category and can lag a few seconds;
list_featured_sections is the exact read.
"""

_ASSETS_DOC = (
    """Put Drive assets into a content item's Featured Assets (the "More" menu),
optionally inside a named section such as "Version 1". Use this, not
update_content(categories=...), which cannot write Featured items.

asset_ids: Drive asset ids (from complete_upload, upload_asset or
    list_drive_files), any type: images, video, files.
"""
    + _SET_RULES
)

_CONTENTS_DOC = (
    """Put other content items into a content item's Featured Content (the
"More" menu), optionally inside a named section. A content with Featured
Content becomes a Collection. Use this, not update_content(categories=...),
which cannot write Featured items.

content_ids: ids of existing content items to feature.
"""
    + _SET_RULES
)


@mcp.tool(
    description=_ASSETS_DOC,
    annotations=ToolAnnotations(
        title="Set Featured Assets",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
def set_featured_assets(
    content_id: str,
    workspace_id: str,
    asset_ids: list[str],
    section_name: str | None = None,
    section_id: str | None = None,
) -> dict:
    return _set_featured("Asset", content_id, workspace_id, asset_ids, section_name, section_id)


@mcp.tool(
    description=_CONTENTS_DOC,
    annotations=ToolAnnotations(
        title="Set Featured Content",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
def set_featured_contents(
    content_id: str,
    workspace_id: str,
    content_ids: list[str],
    section_name: str | None = None,
    section_id: str | None = None,
) -> dict:
    return _set_featured("Content", content_id, workspace_id, content_ids, section_name, section_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="List Featured sections",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_featured_sections(content_id: str, workspace_id: str, kind: str = "Asset") -> dict:
    """List the sections of a content item's Featured Assets or Featured Content,
    in display order, with the items they hold (compact, no signed URLs).

    kind: "Asset" (Featured Assets, default) or "Content" (Featured Content).
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns {"content_id", "featured", "sections": [{"id", "name" (null for the
    unnamed default section), "default", "count", "ids", "items": [{"id",
    "name", "type"}]}], "total"}.
    """
    kind = _kind(kind)
    sections = _sections(_category(workspace_id, content_id, kind))
    refs = _refs(workspace_id, content_id, kind)
    rows = []
    for section in sections:
        items = [
            {"id": r["id"], "name": r["name"], "type": r["type"]}
            for r in refs
            if r["section_id"] == section["id"]
        ]
        rows.append(
            {
                **section,
                "count": len(items),
                "ids": [item["id"] for item in items],
                "items": items,
            }
        )
    return {
        "content_id": content_id,
        "featured": _LABELS[kind],
        "sections": rows,
        "total": len(refs),
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete Featured section",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_featured_section(
    content_id: str, section_id: str, workspace_id: str, kind: str = "Asset"
) -> dict:
    """Delete a NAMED section from a content item's Featured Assets / Content.

    The section and its links are removed; the assets / content items
    themselves are NOT deleted (they stay in Drive / the hub). The unnamed
    default section cannot be deleted — empty it with set_featured_assets /
    set_featured_contents and an empty list instead.

    kind: "Asset" (Featured Assets, default) or "Content" (Featured Content).
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns {"deleted_section_id", "section_name", "unlinked"}.
    """
    kind = _kind(kind)
    sections = _sections(_category(workspace_id, content_id, kind))
    section = next((s for s in sections if s["id"] == section_id), None)
    if section is None:
        raise ValueError(f"No section {section_id} in {_LABELS[kind]} of content {content_id}.")
    if section["default"]:
        raise ValueError(
            "The unnamed default section cannot be deleted; empty it with "
            "set_featured_assets / set_featured_contents and an empty list."
        )
    unlinked = len(_in_section(_refs(workspace_id, content_id, kind), section_id))
    _raw.call(workspace_id, "DELETE", f"{_base(content_id, kind)}/sections/{section_id}")
    return {
        "deleted_section_id": section_id,
        "section_name": section["name"],
        "unlinked": unlinked,
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Reorder Featured sections",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def reorder_featured_sections(
    content_id: str, section_ids: list[str], workspace_id: str, kind: str = "Asset"
) -> dict:
    """Reorder the NAMED sections of a content item's Featured Assets / Content.

    section_ids: named section ids in the order to show them (first = shown
        first). Sections you leave out keep their relative order after these.
        The unnamed default section always stays first (a platform rule).
    kind: "Asset" (Featured Assets, default) or "Content" (Featured Content).
    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Returns {"content_id", "featured", "sections": [{"id", "name", "default"}]}
    in the new order.
    """
    kind = _kind(kind)
    sections = _sections(_category(workspace_id, content_id, kind))
    by_id = {s["id"]: s for s in sections}
    if len(set(section_ids)) != len(section_ids):
        raise ValueError("section_ids lists a section twice.")
    for sid in section_ids:
        if sid not in by_id:
            raise ValueError(f"No section {sid} in {_LABELS[kind]} of content {content_id}.")
        if by_id[sid]["default"]:
            raise ValueError("The unnamed default section always stays first; leave it out.")

    default = next((s["id"] for s in sections if s["default"]), None)
    named = [s["id"] for s in sections if not s["default"]]
    wanted = list(section_ids) + [sid for sid in named if sid not in section_ids]
    order = list(named)
    for index, sid in enumerate(wanted):
        previous = wanted[index - 1] if index else default
        position = order.index(sid)
        actual_previous = order[position - 1] if position else default
        if actual_previous == previous:
            continue
        _raw.call(
            workspace_id,
            "POST",
            f"{_base(content_id, kind)}/sections/{sid}/move",
            json={"previousSectionId": previous},
        )
        order.pop(position)
        order.insert(order.index(previous) + 1 if previous in order else 0, sid)

    return {
        "content_id": content_id,
        "featured": _LABELS[kind],
        "sections": _sections(_category(workspace_id, content_id, kind)),
    }
