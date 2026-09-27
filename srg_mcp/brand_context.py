"""Brand context for agents (SRGDEV-824, SRGDEV-825).

* ``get_brand_index`` — the whole brand in one call: channels → categories →
  contents → sub-contents, and every file once, from
  ``GET /api/v1/contents/{hubProfileId}/index`` (one request instead of one per
  channel, category and content).
* ``get_brand_memory`` / ``append_brand_memory`` — the brand's memory page: a
  normal SRG+ content named "Brand memory" in the private channel "Agent",
  category "Memory", tagged ``brand-memory``. The team edits it in the SRG+ app;
  agents add dated entries. The SRG+ Drive on the Mac shows it as MEMORY.md.
  The page is Preview, not Private (owner decision 2026-09-27): SRG+ reads a
  page body for an API key as a visitor who isn't signed in, so a Private page
  can't be read through the connector. The private channel keeps it off the
  public brand page; anyone who has the page's id can read it.

Writing the page goes through ``PATCH /api/v1/contents/{id}``, which REPLACES the
whole widget list. So an append re-sends every widget exactly, and it only does
that for widgets whose read shape maps losslessly to the write shape (Text,
Media, HubProfile). A page holding anything else (links, content widgets) is
left alone with an explanation instead of being rewritten.
"""

from __future__ import annotations

import datetime as _dt
import secrets
import time
from typing import Any

import srg
from mcp.types import ToolAnnotations

from srg_mcp import _raw
from srg_mcp._app import mcp

MEMORY_TAG = "brand-memory"
MEMORY_CHANNEL = "Agent"
MEMORY_CATEGORY = "Memory"
MEMORY_TITLE = "Brand memory"

# Backend limits (ContentHub TextWidget.MaximumLength, Content.WidgetsLimit).
TEXT_LIMIT = 20_000
WIDGET_LIMIT = 20

OUTLINE_LINE_LIMIT = 600
_CONFLICT_RETRIES = 3


# ---------------------------------------------------------------------------
# Brand index
# ---------------------------------------------------------------------------


def _index(workspace_id: str, hub_profile_id: str) -> dict:
    try:
        return _raw.call(workspace_id, "GET", f"/api/v1/contents/{hub_profile_id}/index")
    except srg.exceptions.NotFoundError as exc:
        raise RuntimeError(
            "This SRG+ server has no brand index yet (GET /contents/{hub}/index, "
            "SRGDEV-823). Walk the brand with list_channels → get_channel → "
            "get_category_references instead."
        ) from exc


def _outline(index: dict, line_limit: int = OUTLINE_LINE_LIMIT) -> str:
    contents = {c["id"]: c for c in index.get("contents") or []}
    lines: list[str] = []

    def add(line: str) -> bool:
        if len(lines) >= line_limit:
            return False
        lines.append(line)
        return True

    def content_line(content: dict, depth: int, path: tuple[str, ...]) -> None:
        extra = []
        if content.get("childContentIds"):
            extra.append(f"{len(content['childContentIds'])} sub")
        files = len(content.get("assetIds") or []) + len(content.get("widgetAssetIds") or [])
        if content.get("mainAssetId"):
            files += 1
        if files:
            extra.append(f"{files} files")
        created = (content.get("created") or "")[:10]
        tail = f" · {', '.join(extra)}" if extra else ""
        if not add(f"{'  ' * depth}- {content['name']} · {content['id']} · {created} · "
                   f"{content.get('privacy')}{tail}"):
            return
        for child_id in content.get("childContentIds") or []:
            child = contents.get(child_id)
            if child is not None and child_id not in path:
                content_line(child, depth + 1, (*path, child_id))

    for channel in index.get("channels") or []:
        add(f"## {channel['name']} ({channel.get('privacy')}) · {channel['id']}")
        for category in channel.get("categories") or []:
            add(f"- {category['name']} · {category['id']} · {len(category.get('contentIds') or [])} contents")
            for content_id in category.get("contentIds") or []:
                content = contents.get(content_id)
                if content is not None:
                    content_line(content, 1, (content_id,))
    if len(lines) >= line_limit:
        lines.append(f"… cut at {line_limit} lines; call get_brand_index(detail='full') for everything.")
    return "\n".join(lines)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get brand index",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_brand_index(hub_profile_id: str, workspace_id: str, detail: str = "outline") -> dict:
    """The whole brand (hub profile) in ONE call: its channels, their categories,
    the contents placed there, sub-contents (Featured Content) and files.

    Use it to get oriented in a brand before searching or walking channels one
    by one. Same visibility as the channel list: only what this key may see.

    detail: "outline" (default) — counts plus a Markdown outline with names,
        ids, created dates and privacy, capped at 600 lines; "full" — the raw
        index: channels[].categories[].contentIds, contents[] (id, name, type,
        privacy, created, modified, version, tags, aiSummary, previewText,
        childContentIds, assetIds, mainAssetId, widgetAssetIds) and assets[]
        (every file once: id, type, name, extension, size).
    `revision` changes exactly when anything in the index changes.
    """
    index = _index(workspace_id, hub_profile_id)
    if detail == "full":
        return index
    if detail != "outline":
        raise ValueError('detail must be "outline" or "full".')
    return {
        "hub_profile_id": index.get("hubProfileId"),
        "revision": index.get("revision"),
        "updated": index.get("updated"),
        "memory_content_id": index.get("memoryContentId"),
        "totals": {
            "channels": len(index.get("channels") or []),
            "categories": sum(len(c.get("categories") or []) for c in index.get("channels") or []),
            "contents": len(index.get("contents") or []),
            "files": len(index.get("assets") or []),
            "file_bytes": sum(a.get("size") or 0 for a in index.get("assets") or []),
        },
        "outline": _outline(index),
    }


# ---------------------------------------------------------------------------
# Brand memory
# ---------------------------------------------------------------------------


_NO_USER_KEY = (
    "The brand memory page is set to Private, and SRG+ reads a page body for an API key as a visitor "
    "who is not signed in (SRGDEV-821), so the connector can't read it. Set the \"Brand memory\" page "
    "to Preview in the SRG+ app (it stays in the private Agent channel), or read it in the app or as "
    "MEMORY.md in the SRG+ Drive on the Mac."
)

_UNLISTED = (
    "Can't tell whether this brand already has a memory page: the brand index doesn't name one and the "
    "private Agent › Memory category can't be listed with an API key. Tag the page \"brand-memory\" in "
    "the SRG+ app, then try again."
)


def _readable(action: Any) -> Any:  # noqa: ANN401
    """Read the memory page body; a 401/403 there means the page was made Private."""
    try:
        return action()
    except (srg.exceptions.ForbiddenError, srg.exceptions.AuthenticationError) as exc:
        raise RuntimeError(_NO_USER_KEY) from exc


def _same(a: str | None, b: str) -> bool:
    return (a or "").strip().casefold() == b.casefold()


def _memory_place(workspace_id: str, hub_profile_id: str) -> tuple[dict | None, dict | None]:
    """The "Agent" channel and its "Memory" category, when they exist."""
    channels = _raw.call(
        workspace_id, "GET", f"/api/v1/channels/{hub_profile_id}", params={"includeArchived": "false"}
    ) or []
    channel = next((c for c in channels if _same(c.get("name"), MEMORY_CHANNEL)), None)
    if channel is None:
        return None, None
    category = next(
        (k for k in channel.get("categories") or []
         if _same(k.get("name"), MEMORY_CATEGORY) and not k.get("isArchived")),
        None,
    )
    return channel, category


def _find_memory(workspace_id: str, hub_profile_id: str, *, before_create: bool = False) -> str | None:
    """The memory page's content id: the tagged content the brand index names,
    else the tagged (or "Brand memory") content in Agent › Memory.

    The index runs as the key's user; the category listing doesn't (API keys
    are visitors there, 401 on a private channel). When the listing can't be
    read and a page is about to be created, raise instead of making a second one.
    """
    try:
        memory_id = _index(workspace_id, hub_profile_id).get("memoryContentId")
    except RuntimeError:
        memory_id = None
    if memory_id:
        return memory_id
    channel, category = _memory_place(workspace_id, hub_profile_id)
    if channel is None or category is None:
        return None
    try:
        page = _raw.call(
            workspace_id,
            "GET",
            f"/api/v1/channels/{channel['id']}/{category['id']}/references",
            params={"PageSize": "50", "Order": "Ascending"},
        ) or {}
    except (srg.exceptions.ForbiddenError, srg.exceptions.AuthenticationError) as exc:
        if before_create:
            raise RuntimeError(_UNLISTED) from exc
        return None
    items = page.get("items") or []
    for item in items:
        try:
            content = _raw.call(workspace_id, "GET", f"/api/v2/contents/{item['id']}") or {}
        except (srg.exceptions.ForbiddenError, srg.exceptions.AuthenticationError):
            continue
        if any(_same(tag, MEMORY_TAG) for tag in content.get("tags") or []):
            return content.get("id") or item["id"]
    named = next((i for i in items if _same(i.get("name"), MEMORY_TITLE)), None)
    return named["id"] if named is not None else None


def _text(content: dict) -> str:
    return "\n\n".join(
        w.get("content") or "" for w in content.get("context") or [] if w.get("$type") == "Text"
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get brand memory",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_brand_memory(hub_profile_id: str, workspace_id: str) -> dict:
    """Read the brand's memory: decisions, notes and context that the team and
    agents keep for this brand (the "Brand memory" page in the private "Agent"
    channel, category "Memory"; the page itself is Preview).

    Read it at the start of work on a brand. Returns {content_id, version,
    updated, text}; content_id is null when the brand has no memory page yet
    (append_brand_memory creates it).
    """
    content_id = _find_memory(workspace_id, hub_profile_id)
    if content_id is None:
        return {"content_id": None, "version": None, "updated": None, "text": "",
                "note": "No memory page yet. append_brand_memory creates it on first use."}
    content = _readable(lambda: _raw.call(workspace_id, "GET", f"/api/v2/contents/{content_id}")) or {}
    return {
        "content_id": content_id,
        "version": content.get("version"),
        "updated": content.get("modified") or content.get("created"),
        "text": _text(content),
    }


def _new_widget_id() -> str:
    # A widget id is a Mongo ObjectId: 4 bytes of time, then random bytes.
    return f"{int(time.time()):08x}{secrets.token_hex(8)}"


def _to_write(widget: dict) -> dict:
    """A widget as read back by GET v2, in the shape PATCH accepts, unchanged."""
    kind = widget.get("$type")
    base = {"$type": kind, "id": widget.get("id"), "title": widget.get("title")}
    if kind == "Text":
        return {**base, "content": widget.get("content") or ""}
    if kind == "Media" and (widget.get("playableAsset") or {}).get("id"):
        return {**base, "assetId": widget["playableAsset"]["id"], "autoplay": bool(widget.get("autoplay"))}
    if kind == "HubProfile":
        ids = [h.get("id") for h in widget.get("hubProfiles") or [] if h.get("id")]
        return {**base, "hubProfileIds": ids}
    raise RuntimeError(
        f"The memory page has a {kind} widget that this tool can't re-send without "
        "risking changes to it. Add the entry in the SRG+ app, or keep the memory page "
        "to text, images and videos."
    )


def _entry(text: str, author: str | None) -> str:
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    first, *rest = text.strip().splitlines()
    lines = [f"- {today} · {(author or 'agent').strip()} · {first.strip()}"]
    lines += [f"  {line}" if line.strip() else "" for line in rest]
    return "\n".join(lines)


def _append(widgets: list[dict], entry: str) -> list[dict]:
    """Add the entry to the last Text widget, or start a new one when it is full."""
    for i in range(len(widgets) - 1, -1, -1):
        if widgets[i]["$type"] != "Text":
            continue
        current = widgets[i]["content"].rstrip("\n")
        joined = f"{current}\n{entry}" if current else entry
        if len(joined) <= TEXT_LIMIT:
            return [*widgets[:i], {**widgets[i], "content": joined}, *widgets[i + 1:]]
        break
    if len(widgets) >= WIDGET_LIMIT:
        raise RuntimeError(
            f"The memory page is full ({WIDGET_LIMIT} blocks). Move old entries to another page in the SRG+ app."
        )
    if len(entry) > TEXT_LIMIT:
        raise ValueError(f"An entry can be at most {TEXT_LIMIT} characters.")
    return [*widgets, {"$type": "Text", "id": _new_widget_id(), "title": None, "content": entry}]


def _retry_forbidden(action: Any, attempts: int = 5) -> Any:  # noqa: ANN401
    """A channel made a moment ago answers 403 until its permissions are copied."""
    for attempt in range(attempts):
        try:
            return action()
        except srg.exceptions.ForbiddenError:
            if attempt == attempts - 1:
                raise
            time.sleep(1 + attempt)
    return None


def _create_memory(workspace_id: str, hub_profile_id: str) -> str:
    """Agent channel (Private) › Memory category › "Brand memory" page (Preview), tagged."""
    channel, category = _memory_place(workspace_id, hub_profile_id)
    if channel is None:
        try:
            _raw.call(workspace_id, "POST", "/api/v1/channels",
                      json={"name": MEMORY_CHANNEL, "hubProfileId": hub_profile_id, "privacy": "Private"})
        except srg.exceptions.SRGError as exc:
            raise RuntimeError(
                f"Could not create the private '{MEMORY_CHANNEL}' channel for the memory page "
                f"({getattr(exc, 'message', exc)}). New channels need a Pro or Business plan and "
                "edit rights on the brand; create it in the SRG+ app and try again."
            ) from exc
        for _ in range(5):
            channel, category = _memory_place(workspace_id, hub_profile_id)
            if channel is not None:
                break
            time.sleep(1)
        if channel is None:
            raise RuntimeError(f"The '{MEMORY_CHANNEL}' channel was created but is not listed yet; try again.")
    if category is None:
        category_id = _retry_forbidden(lambda: _raw.call(
            workspace_id, "POST", f"/api/v1/channels/{channel['id']}/categories",
            json={"name": MEMORY_CATEGORY, "isPinned": False, "notificationsEnabled": False,
                  "emailEnabled": False, "sections": []},
        ))
    else:
        category_id = category["id"]
    created = _retry_forbidden(lambda: _raw.call(
        workspace_id, "POST", "/api/v1/contents",
        json={
            "name": MEMORY_TITLE,
            "hubProfileId": hub_profile_id,
            "privacy": "Preview",
            "channels": [{"channelId": channel["id"], "categoryIds": [category_id]}],
            "context": [{
                "$type": "Text",
                "id": _new_widget_id(),
                "title": None,
                "content": "Decisions, notes and context for this brand. The team edits this page "
                           "in SRG+; agents add dated entries below.\n\n## Log",
            }],
        },
    )) or {}
    content_id = created.get("id") if isinstance(created, dict) else created
    if not content_id:
        raise RuntimeError("SRG+ created the memory page but returned no id; call get_brand_memory.")
    _raw.call(workspace_id, "PATCH", f"/api/v1/contents/{content_id}/metadata",
              json={"tags": [MEMORY_TAG]}, params={"hubProfileId": hub_profile_id})
    return content_id


@mcp.tool(
    annotations=ToolAnnotations(
        title="Append to brand memory",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def append_brand_memory(hub_profile_id: str, workspace_id: str, text: str, author: str | None = None) -> dict:
    """Add ONE dated entry to the brand's memory page. Never rewrites or removes
    existing entries.

    Use it for brand facts worth keeping across sessions and agents: decisions
    ("covers for Reels are 4:5"), preferences, contacts, recurring context. Not
    for task progress or scratch notes. On first use it creates the page: a
    private channel "Agent", category "Memory", content "Brand memory" (the
    whole brand team can read it; the page is Preview so the connector can
    read it, which also means anyone with its id can). Never put secrets in it.

    text: the entry, plain Markdown; the first line is the summary.
    author: who is writing, e.g. "Claude (video editor)"; default "agent".
    Returns {content_id, version, entry}.
    """
    if not text or not text.strip():
        raise ValueError("text is empty.")
    entry = _entry(text, author)
    content_id = (_find_memory(workspace_id, hub_profile_id, before_create=True)
                  or _create_memory(workspace_id, hub_profile_id))

    for attempt in range(_CONFLICT_RETRIES):
        content = _readable(lambda: _raw.call(workspace_id, "GET", f"/api/v2/contents/{content_id}")) or {}
        widgets = _append([_to_write(w) for w in content.get("context") or []], entry)
        try:
            _raw.call(
                workspace_id,
                "PATCH",
                f"/api/v1/contents/{content_id}",
                json={"context": widgets},
                params={"hubProfileId": content.get("hubProfileId") or hub_profile_id},
                headers={"If-Match": f'"{int(content.get("version") or 0)}"'},
            )
            return {"content_id": content_id, "version": int(content.get("version") or 0) + 1, "entry": entry}
        except srg.exceptions.ConflictError:
            # Someone saved the page since we read it: read again and re-apply.
            if attempt == _CONFLICT_RETRIES - 1:
                raise
    raise RuntimeError("unreachable")
