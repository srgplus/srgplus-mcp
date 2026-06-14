from mcp.server.fastmcp import FastMCP

# Server-level guidance returned to EVERY connecting client (claude.ai,
# Cursor, Cline, ChatGPT, etc.) on initialize. Unlike a Claude Code project
# skill — which only exists in the SRG team's repo — this travels with the
# connector to every user and agent automatically, so the load-bearing,
# error-preventing facts about the SRG+ API live here.
SRG_INSTRUCTIONS = """\
SRG+ is a content platform. This server manages hubs, channels, content, and assets.

ID model: workspace → hub profiles (brands) → channels → categories → contents → assets.
Almost every tool takes `workspace_id` explicitly — call `list_workspaces` first and reuse the id.
One key may span several workspaces; list them and pick the right one per call.

Typical flow: list_workspaces → list_hub_profiles → list_channels → get_channel
(returns the channel's categories WITH their ids) → search_contents / get_content.

Content body = the `context` list of widgets. Every widget needs a "$type": "Text"
(field `content`, markdown), "LinkList" (field `links`, each a {"$type":"CustomLink"|"KnownLink",
"title","url"} — both link kinds use title+url), "Media" (field `assetId`), "HubProfile"
(field `hubProfileIds`, an array), or "ContentWidget" (fields `referenceType` +
`referenceIds`:[{"$type":"Content"|"Asset","id":..}]). Widget keys are camelCase — snake_case
(asset_id, hub_profile_id) is silently rejected as a 400. One malformed widget rejects the whole
write; the error names the bad field. See the create_content/update_content tool docs for full shapes.

Pitfalls that cause real damage — read before writing:
- update_content merges SCALAR fields you pass (others are preserved), but any LIST you pass
  (channels, context, categories) REPLACES the whole list. To add one item, read the current
  content first (get_content_v2), extend the existing list, and send the full list back.
  The raw REST PUT /contents is destructive — omitted fields are wiped. (update_content
  resolves the owning hub profile for you — you need not pass hub_profile_id.)
- A 401/403 on an individual category or channel is NORMAL (per-item access control). Skip that
  item and continue the batch; do not treat it as a fatal error.
- For content in PRIVATE channels, the slim list/filter endpoints omit channel/category
  membership — use get_content_v2 to read it reliably.
- Assets: use `upload_asset` (pass a public source_url or base64_content). The hosted server
  cannot read local file paths. The create_*_asset tools only register an empty record and are
  deprecated — do not use them to upload bytes.

"No workspaces found for this API key" means the key was revoked or is invalid — issue a new
one in SRG+ Settings → API Keys, do not retry.
"""

mcp = FastMCP("SRG+", instructions=SRG_INSTRUCTIONS)
