"""A self-contained how-to guide, shipped WITH the connector.

The server-level ``instructions`` (see ``_app.py``) are the always-on, concise
layer every client receives on connect. This module adds the *full* guide as a
tool the agent can pull on demand — recipes, exact widget shapes, pitfalls —
so the rich guidance travels with the MCP itself and no separate skill/plugin
install is required on any machine, profile, or client (claude.ai, Claude Code,
Cursor, ...). Keep this in sync with the ``srgplus-core`` skill; this copy is
the canonical one for connector users.
"""

from srg_mcp._app import mcp
from mcp.types import ToolAnnotations

SRGPLUS_GUIDE = """\
# SRG+ connector guide

SRG+ is a content platform. ID model:
`workspace → hub profiles (brands) → channels → categories → contents → assets`.

Almost every tool takes `workspace_id` explicitly. Resolve it once and reuse it.

## Find your way around
1. `list_workspaces()` — slim rows (id, name, hub_profile_count). One key may
   span many workspaces (a personal `srgplus_u_` key sees all of yours). Use
   `get_workspace(id)` only when you need full detail.
2. `list_hub_profiles(workspace_id)` — the brands in a workspace. Match by
   name/username client-side; filter, don't dump (there can be 100+).
3. `list_channels(hub_profile_id, workspace_id)` then
   `get_channel(channel_id, workspace_id)` — the channel payload carries its
   categories WITH their ids. Category ids for attaching content come from here.
4. `search_contents(hub_profile_id, search, workspace_id)` — fuzzy, hub-wide.
5. `get_content(id, workspace_id)` / `get_content_v2(id, workspace_id)` — v2 is
   the reliable read for channel/category membership and for Private channels.

## Create and place content
1. `create_content(name, hub_profile_id, workspace_id, privacy="Preview",
   details=..., context=[...])`. `privacy` is "Preview" | "Private" | "Public".
2. Place it: pass `channels=[channel_id]` at create, or afterwards
   `add_content_to_categories(content_id, channel_id, category_ids=[...], workspace_id)`.

## The body = `context`, an ordered list of widgets
Every widget carries a `$type`. Keys are **camelCase** — the backend silently
rejects snake_case for multi-word fields (assetId, hubProfileIds) as a 400.
A single bad widget rejects the whole write; the 400 now names the bad field.

- Text: `{"$type":"Text","content":"<markdown>","title":"<optional>"}`
- LinkList: `{"$type":"LinkList","title":"<optional>","links":[
    {"$type":"CustomLink","title":"..","url":"https://..","extension":"<optional image ext>"},
    {"$type":"KnownLink","title":"..","url":"https://.."}]}`
  (both link kinds use `title`+`url`; max 20 links)
- Media: `{"$type":"Media","assetId":"<asset id>","autoplay":false,"title":"<optional>"}`
  (upload the file first with `upload_asset` to get the id)
- HubProfile: `{"$type":"HubProfile","hubProfileIds":["<hub id>",...],"title":"<optional>"}`
  (`hubProfileIds` is a REQUIRED array, even for one hub)
- ContentWidget: `{"$type":"ContentWidget","referenceType":"Content",
    "referenceIds":[{"$type":"Content","id":"<content id>"}],"title":"<optional>"}`
  (each ref is `{"$type":"Content"|"Asset","id":".."}`)

## Update safely
`update_content(content_id, workspace_id, ...)` MERGES scalar fields you pass
(omitted ones are preserved). BUT any LIST you pass — `channels`, `context`,
`categories` — REPLACES the whole list. To append a widget: `get_content_v2`
first, extend the existing `context`, and send the full list back. You need not
pass `hub_profile_id`; it is resolved from the content.

## Assets
`upload_asset(hub_profile_id, name, workspace_id, source_url="https://..")` or
`base64_content` + `extension`. The hosted server CANNOT read local file paths —
use a public URL or base64. The `create_*_asset` tools only register an empty
record and are deprecated; don't use them to upload bytes.

## Archive / restore (reversible)
Core is archive-only (no hard delete; deletion stays manual in-app):
`archive_content`/`restore_content`, `archive_channel`/`restore_channel`,
`archive_category`/`restore_category`, `archive_hub_profile`/`restore_hub_profile`.

## Pitfalls — handle, don't abort
- A 401/403 on an individual category or channel is NORMAL (per-item access
  control). Skip that item and continue the batch; don't fail the whole task.
- "No workspaces found for this API key" = the key is revoked/invalid. Issue a
  new key in SRG+ Settings → API Keys; do not retry.
- Private-channel content: the slim list/filter omits memberships — use
  `get_content_v2`.
- Two profiles on one host: `https://mcp.srgplus.com` (curated daily set, the
  default) and `https://mcp.srgplus.com/mcp` (full set: users, permissions,
  hard delete, sections, workspace actions). Don't connect both in one surface.
"""


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get SRG+ guide",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=False,
    )
)
def get_srgplus_guide() -> str:
    """Return the full SRG+ how-to guide: navigation, content creation, the
    exact widget shapes for the `context` body, safe-update rules, asset upload,
    archive/restore, and common pitfalls.

    Call this once before authoring or editing content if you are unsure of the
    workflow or a widget's shape — it is the authoritative reference and ships
    with the connector (no separate skill install needed).
    """
    return SRGPLUS_GUIDE
