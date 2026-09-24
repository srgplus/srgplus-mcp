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
   `search` must be a NON-EMPTY keyword (a blank query is rejected with 400);
   there is no search-all, so to browse use list_channels/get_channel.
5. `get_content(id, workspace_id)` / `get_content_v2(id, workspace_id)` — v2 is
   the reliable read for channel/category membership and for Private channels.

## Create and place content
1. `create_content(name, hub_profile_id, workspace_id, privacy="Preview",
   details=..., context=[...])`. `privacy` is "Preview" | "Private" | "Public".
   Optional `cover_image` is an http(s) URL of a JPEG/PNG/WEBP/HEIC image
   (max 25 MB). It needs no extension — the type and size are read from the
   bytes. The hosted server cannot read files on your computer.
2. Place it with `add_content_to_categories(content_id, channel_id,
   category_ids=[...], workspace_id)`. A placement needs a CATEGORY, so passing
   `channels=[channel_id]` alone at create often does NOT stick (saved
   channels:[]) — use add_content_to_categories to be sure.
3. `create_content` returns a TRUNCATED echo of the body — verify the real
   persisted widgets with `get_content_v2`.

## The body = `context`, an ordered list of widgets
Every widget carries a `$type`. Keys are **camelCase** — the backend silently
rejects snake_case for multi-word fields (assetId, hubProfileIds) as a 400.
A single bad widget rejects the whole write; the 400 now names the bad field.

- Text: `{"$type":"Text","content":"<markdown>","title":"<optional>"}`
- LinkList: `{"$type":"LinkList","title":"<optional>","links":[
    {"$type":"CustomLink","title":"..","url":"https://..","extension":"<optional image ext>"},
    {"$type":"KnownLink","title":"..","url":"https://.."}]}`
  (both link kinds use `title`+`url`; max 20 links)
- Media: `{"$type":"Media","assetId":"<playable asset id>","autoplay":false,"title":"<optional>"}`
  (assetId must be an EXISTING PLAYABLE/VIDEO asset of the hub. An image, or a
  just-uploaded asset, is NOT playable media and 404s `Media widget assets …
  not found`. There is no image-body widget — put images in the cover, a
  CustomLink, or markdown in a Text widget.)
- HubProfile: `{"$type":"HubProfile","hubProfileIds":["<hub id>",...],"title":"<optional>"}`
  (`hubProfileIds` is a REQUIRED array, even for one hub)
- ContentWidget: `{"$type":"ContentWidget","referenceType":"Content",
    "referenceIds":[{"$type":"Content","id":"<content id>"}],"title":"<optional>"}`
  (each ref is `{"$type":"Content"|"Asset","id":".."}`)

## Update safely
`update_content(content_id, workspace_id, ...)` changes ONLY the fields you
pass. Everything you omit — cover, main asset, channels, categories, body,
action buttons — keeps its stored value, so rewriting captions never touches
the cover. BUT any LIST you pass — `channels`, `context`, `categories` —
REPLACES the whole list. To append a widget: `get_content_v2` first, extend the
existing `context`, and send the full list back. You need not pass
`hub_profile_id`; it is resolved from the content. Never call the raw REST
`PUT /contents` for a partial edit: it wipes every field you omit, the cover
included.

## Upload files from the user's computer (no base64, no public URL)
The hosted server cannot read local paths and base64 does not scale (one
300 KB JPEG is ~400K characters). The bytes go straight to storage instead:

1. Collect size (and pixel size for images). macOS, for a folder of JPEGs:
   ```
   cd "<folder>"; for f in *.jpg; do printf '{"path":"%s","size":%s,"width":%s,"height":%s}\n' \
     "$PWD/$f" "$(stat -f%z "$f")" \
     "$(sips -g pixelWidth "$f" | awk '/pixelWidth/{print $2}')" \
     "$(sips -g pixelHeight "$f" | awk '/pixelHeight/{print $2}')"; done
   ```
   (Linux: `stat -c%s FILE`, `identify -format '%w %h' FILE`.)
2. `create_upload(hub_profile_id, workspace_id, files=[{"path","size","width","height"}, ...])`
   — up to 100 files; returns `script` (bash + curl).
3. Save `script` to a file and run it: `bash /tmp/srg_upload.sh`. It PUTs every
   file (big videos in parts) and prints ONE JSON line.
4. `complete_upload(workspace_id, uploads=<that JSON>)` → ready Drive assets
   (safe to repeat; already-completed uploads are skipped).
   Without the script (`output="urls"`), PUT each part yourself and keep its
   ETag response header:
   `curl -sS -f -X PUT -T "Reel 01.jpg" -D - -o /dev/null "<part url>" | grep -i etag`

`upload_asset(..., source_url=...)` remains for files already on the web;
`base64_content` only for tiny files. The `create_*_asset` tools only register
an empty record and are deprecated; don't use them to upload bytes.

## Covers
- From a Drive image: `set_cover(content_id, asset_id, workspace_id)`; many at
  once: `set_covers(items=[{"content_id","asset_id"}, ...], workspace_id,
  hub_profile_id=...)` (one call; failures don't stop the batch). Right after
  complete_upload an image needs a few seconds to be ready — these tools wait.
  The bytes are copied into the cover, so it survives deleting the Drive file.
- From a URL: `update_content(content_id, workspace_id, cover_image="https://...")`
  (no extension needed). Or `update_content(cover_asset_id=...)`.
- Body edits never touch the cover (update_content only changes what you pass).

## Drive
- `list_drive_files(hub_profile_id, workspace_id, types=["Image"], search=...)`
  → compact rows (id, name, type, size, width/height). Paged via `cursor`.
- `get_asset(asset_id, workspace_id)` → `url` is a signed download URL (~7 days)
  to verify a file. The Drive has no folders yet.

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
