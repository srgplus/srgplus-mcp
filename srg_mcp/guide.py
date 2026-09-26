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
from srg_mcp.hub_profiles import HUB_IMAGE_RULES
from mcp.types import ToolAnnotations

# Raw string, so every backslash reaches agents exactly as written here (the
# printf `\n` and trailing `\` in the shell snippet, `\|` in tables).
SRGPLUS_GUIDE = r"""# SRG+ connector guide

SRG+ is a content platform. ID model:
`workspace → hub profiles (brands) → channels → categories → contents → assets`.

Almost every tool takes `workspace_id` explicitly. Resolve it once and reuse it.

## Find your way around
1. `list_workspaces()` — slim rows (id, name) in one call. One key may span
   many workspaces (a personal `srgplus_u_` key sees all of yours). A
   workspace's brands come from `list_hub_profiles(workspace_id)`;
   `get_workspace(workspace_id)`, with seats and subscription, is on the full
   `/mcp` only.
2. `list_hub_profiles(workspace_id, search=...)` — the brands in a workspace
   as compact rows (id, name, user_name, has_avatar), 50 per page; pass the
   returned `cursor` for more. Use `search` (name or username) instead of
   paging through 100+ brands. `get_hub_profile` has the full profile.
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

Write vs read: a ContentWidget is WRITTEN with `referenceIds` but READ BACK by
`get_content_v2` with `references` — expanded objects whose `$type` is the item
kind (`Content`, or `Image`/`Video`/`File`/`Media`/`Embed` for assets). Same
data, different key: a missing `referenceIds` on read does NOT mean the write
failed. To re-send a widget you read, map `references` → `referenceIds`
`[{"$type":"Content"|"Asset","id":..}]`.

## Text widget Markdown (the SRG+ standard)
A Text widget's `content` is GitHub Flavored Markdown (the GFM spec in full:
headings, lists, task lists, tables, code, quotes, links, images,
strikethrough) plus one extension, `==highlight==`. SRG+ stores the string
byte for byte. To render the same on web, iPhone, iPad, Mac and Android, and to
survive later edits in the SRG+ apps, write this subset:

- A blank line between blocks: before and after every heading, list, table,
  code fence, quote and `---` rule. A `---` right under a line of text turns
  that text into a heading, and a line right under a table becomes a row.
- Sections with `##` and `###` (the content name is already the page title).
- Inline: `*italic*`, `**bold**`, `~~strike~~`, `==highlight==`, `` `code` ``.
  The `==` pair hugs its text: `==like this==` highlights, `a == b` does not.
- Lists: `-` bullets, `1.` numbers, nest with 2 spaces (3 under `1.`). Tasks:
  `- [ ] to do` and `- [x] done`.
- Tables: a header row, a delimiter row, one row per line:
  ```
  | Field  | Value    |
  | :----- | -------: |
  | Format | 8 frames |
  ```
  A pipe inside a cell needs a backslash (`\|`), also inside `code`. For a line
  break inside a cell use `<br>`. Name the columns instead of leaving an empty
  `| | |` header.
- Code: fence with three backticks and a language (```json). A fence that is
  never closed swallows the rest of the widget.
- Links `[text](https://...)`, images `![alt](https://...)` with public https
  URLs.
- Real characters (`·`, `→`, `—`) instead of entities (`&middot;`, `&rarr;`,
  `&mdash;`), and a normal space instead of `&nbsp;`.
- A newline inside a paragraph shows as a line break; a blank line starts a new
  paragraph. Don't end lines with spaces or a backslash.
- Shown as plain text, so don't use them: raw HTML (except `<br>` in a table
  cell), footnotes, math, emoji shortcodes (`:rocket:`), wiki links
  (`[[page]]`), `> [!NOTE]` alerts.
- Up to 20,000 characters per Text widget (5,000 in a hub-profile Text widget).
  Split a long page into several Text widgets.

Editing an existing Text widget: read it with `get_content_v2`, change only the
part you mean to change, and send everything else back exactly as it was. Don't
re-wrap lines, re-align tables, swap `*` for `_` or convert entities: people
edit the same text in the SRG+ apps.

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

Several agents/people editing the same content? `get_content_v2` returns a
`version`. Pass it back as `update_content(..., expected_version=<version>)`
(also `set_cover`, `set_covers` items): if someone changed the content since
you read it you get a 409 instead of overwriting their edit — re-read, re-apply
your change, retry. Without expected_version an update still never touches
fields you did not pass.

## Featured Assets / Featured Content (the content's "More" menu)
Every content item has two built-in lists: **Featured Assets** (Drive assets)
and **Featured Content** (other content items; a content with any becomes a
Collection). Each has one unnamed default section (always first) plus any
number of NAMED sections — use them for versions ("Version 1", "Version 2").

- `set_featured_assets(content_id, workspace_id, asset_ids=[...], section_name="Version 2")`
  → the section is created if missing and then holds exactly those assets, in
  that order (REPLACES that section's items; other sections are untouched).
  A new named section is placed first among the named ones, so the newest
  version shows first. Without section_name the default section is used.
  `set_featured_contents(..., content_ids=[...])` is the same for content.
- `list_featured_sections(content_id, workspace_id, kind="Asset"|"Content")`
  → sections in display order with their ids (compact, no signed URLs). This
  is the exact read; get_content_v2 shows at most 15 items per category and can
  lag a few seconds after a write.
- `reorder_featured_sections(content_id, section_ids=[...], workspace_id)`;
  `delete_featured_section(content_id, section_id, workspace_id)` (unlinks the
  items; the assets themselves stay in Drive).
- An item can be in only ONE section of a content: reusing a Version 1 frame
  in Version 2 is reported in `skipped` (remove it from Version 1 first, or
  upload a copy). Check `skipped` after every call.
- `update_content(categories=...)` writes only a category's `options`; it
  rejects `references`/`sections` changes (the API would ignore them).

Recipe, carousel versions: upload the frames (create_upload → complete_upload)
→ `set_featured_assets(content_id, ws, asset_ids=<frames in order>,
section_name="Version 1")`; later a new set → `section_name="Version 2"`.
Versions accumulate; nothing is overwritten.

## Upload files from the user's computer (no base64, no public URL)
The hosted server cannot read local paths and base64 does not scale (one
300 KB JPEG is ~400K characters). The bytes go straight to storage instead:

1. Collect size (and pixel size for images). macOS, for a folder of JPEGs:
   ```bash
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

## Set up a hub profile (the brand page srgplus.com/<user_name>)
1. Read first: `get_hub_profile(hub_profile_id, workspace_id)` → name,
   sub_name (line under the name), user_name, description (the bio),
   primary_url (website), visibility, avatar, cover, links, buttons, `version`.
2. Text fields: `update_hub_profile(hub_profile_id, workspace_id, bio=...,
   sub_name=..., primary_url=...)`. Only the fields you pass change; the
   avatar, cover, links, buttons, other widgets, visibility and user_name keep
   their stored value. `""` clears sub_name / description / primary_url.
   Limits: name and user_name 2-150, bio 10-1000, sub_name up to 150.
   user_name is the URL slug (letters, digits, `-`, `_`, `.`; stored lowercased);
   changing it changes the page address, so only do it when asked.
3. Links: `update_hub_profile(..., links=[{"title": "Instagram", "url":
   "https://instagram.com/brand"}, ...])`. Same rule as `context`: the list you
   pass REPLACES the whole link list. To add one link, read `links` from
   get_hub_profile, append, and send the full list back (keep each `id`).
   Max 20 links, unique titles, 1-100 chars. Default `$type` is KnownLink (SRG+
   fetches the site's icon); `platform` in the read shape is inferred from the
   host and is display-only. `links=[]` removes the link list.
4. Images from the Drive (preferred): upload with create_upload → script →
   complete_upload (or pick from `list_drive_files(types=["Image"])`), then
   `set_hub_avatar(hub_profile_id, asset_id, workspace_id)` and
   `set_hub_cover(...)`. The asset must be in THE SAME hub's Drive (another
   hub's asset → 404). They wait for a just-uploaded image and return the
   stored width/height and URL. From a public URL instead:
   `update_hub_profile(..., avatar_image="https://...", cover_image=...)`.
5. Image sizes and safe area:
<<HUB_IMAGE_RULES>>
6. With several editors, pass `expected_version` (the `version` you read) to
   every write: a stale write then fails with 409 and changes nothing.

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
  hard delete, low-level collection subcontent, workspace actions). Don't
  connect both in one surface.
"""


# The image rules live next to the hub-profile tools; indent them into step 5.
SRGPLUS_GUIDE = SRGPLUS_GUIDE.replace(
    "<<HUB_IMAGE_RULES>>",
    "\n".join("   " + line for line in HUB_IMAGE_RULES.splitlines()),
)


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
    exact widget shapes for the `context` body, the Markdown standard for Text
    widgets (GFM + ==highlight==), safe-update rules, Featured
    Assets / Featured Content with named sections (versions), asset upload,
    setting up a hub profile (bio, links, avatar and cover sizes / safe area),
    archive/restore, and common pitfalls.

    Call this once before authoring or editing content if you are unsure of the
    workflow or a widget's shape — it is the authoritative reference and ships
    with the connector (no separate skill install needed).
    """
    return SRGPLUS_GUIDE
