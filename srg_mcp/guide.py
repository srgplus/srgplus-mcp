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
   Archived hubs are left out; `include_archived=True` lists them too, each
   marked `"archived": true`.
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
   To take it out of one category: `remove_content_from_categories(content_id,
   channel_id, category_ids=[...], workspace_id)`. Only those categories lose
   it; every other placement stays. Don't reset all placements and re-add.
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
   — up to 100 files; returns `script` (bash + curl). The Drive name is the
   file name WITHOUT its extension (the server adds the extension itself), so
   `Reel 01.jpg` shows as "Reel 01". If you pass `name`, leave the extension
   off; a trailing `.jpg` is dropped for you.
3. Save `script` to a file and run it: `bash /tmp/srg_upload.sh`. It PUTs every
   file (big videos in parts) and prints ONE JSON line.
4. `complete_upload(workspace_id, uploads=<that JSON>)` → ready Drive assets
   (safe to repeat; already-completed uploads are skipped).
   Without the script (`output="urls"`), PUT each part yourself and keep its
   ETag response header:
   `curl -sS -f -X PUT -T "Reel 01.jpg" -D - -o /dev/null "<part url>" | grep -i etag`

`upload_asset(..., source_url=...)` remains for files already on the web;
`base64_content` only for tiny files. Its `name` follows the same rule (no
extension needed; a trailing one is dropped).
Videos get their cover automatically, see "Video covers are automatic". The `create_*_asset` tools only register
an empty record and are deprecated; don't use them to upload bytes.

## Video covers are automatic
The server makes a video's cover by itself for EVERY upload (this connector,
the apps, the web, the Finder drive), normally within about a minute. A burst
of many uploads at once can delay it. A video with no cover yet is normal.
- Check with `get_asset(asset_id, workspace_id)`: a real cover has non-zero
  `cover` width, height and size. `cover.urls` are signed URLs that exist
  even when there is no cover yet, so a URL alone proves nothing.
- Wait and check again a minute or two later. NEVER archive or re-upload a
  file because its cover is late: the copy would wait for its cover too.
- Still no cover after about 15 minutes: tell the user, don't work around it.
- `set_cover` / `set_covers` (below) set a CONTENT's cover from a Drive
  image. They do not give a video file its own preview.

## Covers
- From a Drive image: `set_cover(content_id, asset_id, workspace_id)`; many at
  once: `set_covers(items=[{"content_id","asset_id"}, ...], workspace_id,
  hub_profile_id=...)` (one call; failures don't stop the batch). Right after
  complete_upload an image needs a few seconds to be ready — these tools wait.
  The bytes are copied into the cover, so it survives deleting the Drive file.
- From a URL: `update_content(content_id, workspace_id, cover_image="https://...")`
  (no extension needed). Or `update_content(cover_asset_id=...)`.
- Ready-made preset covers (no image, no upload): there are 12 gradient covers.
  `list_cover_presets(workspace_id)` → `{"presets": [{id, name, previewUrl,
  url}]}` (`previewUrl` ~400 px to look at, `url` 1600 px). The ids, in
  display order: `pearl`, `champagne`, `desert`, `orange`, `burgundy`,
  `purple`, `lavender`, `sierra`, `midnight`, `mint`, `alpine`, `graphite`.
  Apply one: `set_cover_preset(content_id, preset_id, workspace_id)`; many at
  once: `set_covers(items=[{"content_id", "preset_id"}, ...], workspace_id)`
  (items may mix `asset_id` and `preset_id`, exactly one per item). Same
  `expected_version` / 409 rule as `set_cover`; an unknown id is refused with
  the valid list.
  When to use: the content has no suitable image and a clean, consistent card
  will do (new or placeholder cards, a batch that should look uniform, quick
  drafts). A preset REPLACES the current cover, so never put one over a cover
  the user chose or uploaded unless they ask; when the user wants their own
  picture, upload it and use `set_cover`.
- Body edits never touch the cover (update_content only changes what you pass).

## Drive
- `list_drive_files(hub_profile_id, workspace_id, types=["Image"], search=...)`
  → compact rows (id, name, type, size, width/height). Paged via `cursor`.
- `get_asset(asset_id, workspace_id)` → `url` is a signed download URL (~7 days)
  to verify a file. The Drive has no folders yet.

### Remove Drive files (archive → delete)
Same as the app's Drive bin. A file's asset id is what these tools take.
1. Find the ids: `list_drive_files(hub_profile_id, workspace_id, search="SB")`.
   Show the user the exact list (name + id) and what stays, before touching it.
2. Archive (reversible): `archive_drive_files(asset_ids=[...], workspace_id)`
   moves them to the bin. `list_drive_files(..., archived=True)` lists the bin;
   `restore_drive_files(asset_ids=[...], workspace_id)` brings them back.
3. Delete for good: `delete_drive_files(asset_ids=[...], workspace_id)` deletes
   files that are already archived (a non-archived one fails and is kept).
   One step: `delete_drive_files(..., archive_first=True)` archives then deletes.
   Returns per-file results and `bytes_freed`. Up to 200 ids per call; a file
   that fails doesn't stop the batch. Deleting cannot be undone.
Covers set from a Drive image are copies and survive; Media widgets and
Featured Assets that point at a deleted file lose it.

## New hub with channels and categories
Top-down, one call per item; each call returns the id the next step needs.
1. `create_hub_profile(name, user_name, workspace_id,
   availability_level="Private", description=...)` → the new hub's `id`.
   The default is "Public" (anyone can open srgplus.com/<user_name>), so pass
   "Private" for an internal hub (team or agents only). user_name is the URL
   slug, unique across SRG+ (letters, digits, `-`, `_`, `.`); name 2-150,
   description optional, 10-1000 characters. A new hub already has one
   Private channel, "general" (`archive_channel` it if you don't need it).
2. `create_channel(name, hub_profile_id, workspace_id, privacy="Private")` →
   the channel id. Keep the channels of an internal hub Private (the default).
   Names are unique within the hub, 1-50 characters, no `/` or `\`. Channels
   need a Pro or higher plan: a Free or Individual workspace is refused.
3. `create_category(channel_id, name, workspace_id)` → the category id. Names
   are unique within the channel (1-50 characters). A new channel already has
   one category, "New Content".
4. Check: `list_hub_profiles(workspace_id, search=<user_name>)` lists the hub,
   `get_hub_profile` opens it, `get_channel(channel_id, workspace_id)` shows
   the categories with their ids.
"Already exists" on a rerun: don't retry, look the id up (step 4 or
`list_channels`) and carry on.
Rename: `rename_category(channel_id, category_id, name, workspace_id)` and
`rename_channel(channel_id, name, workspace_id)` change ONLY the name (contents,
order, pin, options, privacy stay). Emoji in names are fine. Rename in place;
never create a new category and move the contents just to change a name.
Reordering channels and categories is not in the core connector; do it in the
SRG+ app.

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
   `update_hub_profile(..., avatar_image="https://...", cover_image=...)`;
   `avatar_image=""` / `cover_image=""` removes the image.
5. Image sizes and safe area:
<<HUB_IMAGE_RULES>>
6. With several editors, pass `expected_version` (the `version` you read) to
   every write: a stale write then fails with 409 and changes nothing.

## Hub profile widgets (the sections of the brand page)
The page shows its widgets in order: Text, LinkList (the links), ContentWidget
(cards of contents, or of Drive assets), HubProfile (other profiles), Media (a
playable video) and Contact. `get_hub_profile` only lists them (id, type,
title).
1. Read: `get_hub_profile_widgets(hub_profile_id, workspace_id)` → `version`
   and every widget in display order with `position` (0 = top) and all its
   fields. A ContentWidget shows `referenceIds` (what a write takes) and
   `references` `[{$type, id, name}]` (read-only; `$type` is `Content` or the
   asset kind). Names are as of the last write of that widget.
2. Content cards: `set_hub_profile_content_widget(hub_profile_id, workspace_id,
   content_ids=[...])` → the widget then shows exactly those contents in that
   order (REPLACES its list, like `set_featured_contents`). It fills the
   page's only content widget, or creates one; with several, pass `widget_id`
   (or `title`: the widget with that exact title, created if missing). Ids
   that don't exist are skipped and listed in `skipped`. The contents
   themselves are never changed.
3. Any widget, ONE at a time; the others stay exactly as stored:
   - add: `add_hub_profile_widget(hub_profile_id, workspace_id,
     widget={...}, position=0)` (omit position to add at the end; max 20);
   - change: `update_hub_profile_widget(hub_profile_id, widget_id,
     widget={"title": "Reports"}, workspace_id)` → only the fields you pass
     change; a list you pass (links, referenceIds, ...) replaces that list. The
     type cannot change: remove and add instead;
   - remove: `remove_hub_profile_widget(hub_profile_id, widget_id,
     workspace_id)` → only the widget goes, never the contents it shows;
   - order: `reorder_hub_profile_widgets(hub_profile_id, widget_ids=[...],
     workspace_id)` → listed first, the rest after in their order.
4. Shapes (camelCase, `$type` first, same as in a content's `context`):
   - `{"$type":"Text","title":null,"content":"<markdown>"}` (up to 5,000 characters)
   - `{"$type":"LinkList","title":null,"links":[{"title":"..","url":"https://.."}]}`
   - `{"$type":"ContentWidget","title":"Playbooks","referenceType":"Content",
     "referenceIds":[{"$type":"Content","id":"<content id>"}]}` (`"Asset"` and
     Drive asset ids for files)
   - `{"$type":"HubProfile","title":null,"hubProfileIds":["<hub profile id>"]}`
   - `{"$type":"Media","title":null,"assetId":"<playable video id>","autoplay":false}`
   - `{"$type":"Contact","title":null,"contacts":[{"$type":"Email","details":"hi@brand.com"}]}`
   A widget read with `get_hub_profile_widgets` can be sent back as is.
5. Whole page at once: `update_hub_profile(..., widgets=[...])` REPLACES ALL
   widgets (the link list included): keep each `id`, leave `id` out for a new
   one, and a widget you leave out is removed. Every widget is resolved again,
   so one deleted content anywhere fails the write. Prefer the one-widget
   tools. `create_hub_profile(widgets=...)` takes Text, LinkList and Contact
   only.
6. Every widget write takes `expected_version` (the `version` you read) →
   409, nothing written, if the profile changed since.

## Archive / restore (reversible)
Hubs and content are archive-only in core (no hard delete; deletion stays
manual in-app). Drive files, channels and categories can also be deleted for
good: see "Remove Drive files" above and "Delete a channel or category" below.
`archive_content`/`restore_content`, `archive_channel`/`restore_channel`,
`archive_category`/`restore_category`, `archive_hub_profile`/`restore_hub_profile`.
Archived hubs and channels drop out of `list_hub_profiles` / `list_channels`.
To find one to restore, pass `include_archived=True` (archived hubs come back
marked `"archived": true`). Archiving a hub archives its channels too.
Permanently deleting a hub profile is app-only (the owner, signed in, deletes
an archived hub in the SRG+ app); the API refuses any API key with 403, so no
connector surface has a tool for it. Asked to delete a hub, offer to archive
it and say the final delete is done by the owner in the app.

## Delete a channel or category (archive → delete)
1. Confirm the exact channel or category with the user. Tell them the
   contents inside are NOT deleted: they only lose this place and stay in the
   hub, in Drive and in other channels (`get_brand_index` lists the ones left
   in no category).
2. Archive (reversible): `archive_channel(channel_id, workspace_id)` or
   `archive_category(channel_id, category_id, workspace_id)`.
3. Delete for good: `delete_channel(channel_id, workspace_id)` (the channel
   and all its categories) or `delete_category(channel_id, category_id,
   workspace_id)`. Only archived ones; a live one fails with 409 and is kept.
   One step: pass `archive_first=True`.
Only the hub owner or an admin can delete (editors can archive, not delete). Taking ONE content
out of a category is `remove_content_from_categories`, not a category delete.

## Pitfalls — handle, don't abort
- A 401/403 on an individual category or channel is NORMAL (per-item access
  control). Skip that item and continue the batch; don't fail the whole task.
- "No workspaces found for this API key" = the key is revoked/invalid. Issue a
  new key in SRG+ Settings → API Keys; do not retry.
- Private-channel content: the slim list/filter omits memberships — use
  `get_content_v2`.
- Two profiles on one host: `https://mcp.srgplus.com` (curated daily set, the
  default) and `https://mcp.srgplus.com/mcp` (full set: users, permissions
  and permission groups, low-level collection subcontent, workspace actions). Don't
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
    covers (from a Drive image or one of the 12 ready-made preset gradients),
    creating a new hub with its channels and categories, setting up a hub
    profile (bio, links, avatar and cover sizes / safe area), the hub profile
    widgets (content cards and the other sections of a brand page),
    archive/restore, and common pitfalls.

    Call this once before authoring or editing content if you are unsure of the
    workflow or a widget's shape — it is the authoritative reference and ships
    with the connector (no separate skill install needed).
    """
    return SRGPLUS_GUIDE
