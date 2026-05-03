# srgplus-mcp

MCP server for [SRG+](https://srgplus.com) — lets Claude (and any MCP-aware
agent) manage hubs, channels, content, assets, users, and workspaces through
the SRG+ API.

Two ways to run it:

- **Hosted HTTP** (recommended for production / claude.ai web / Cursor / Cline) — single endpoint, header-based auth, multi-tenant
- **Local stdio** (for desktop dev / offline) — single user, env-var auth, runs as a child process of the agent

Both modes share the same tools and the same SDK underneath — you pick the
transport that fits your client.

## Hosted HTTP

### Run the server

```bash
pip install 'srgplus-mcp[server]'
srgplus-mcp-serve   # listens on $PORT (default 8090)
```

Or in Docker:

```bash
docker build -t srgplus-mcp .
docker run -p 8090:8090 srgplus-mcp
```

Health check:

```bash
curl http://localhost:8090/health
```

### Connect from Claude / Cursor / any MCP client

```json
{
  "mcpServers": {
    "srgplus": {
      "url": "http://localhost:8090/mcp",
      "headers": { "X-API-Key": "srgplus_your_key_here" }
    }
  }
}
```

Or use `Authorization: Bearer srgplus_...` instead of `X-API-Key` — both work.

For a hosted public endpoint pointed at your SRG+ workspace, the URL becomes
`https://mcp.srgplus.com/mcp` (rolling out — see SRGDEV-8 follow-ups for the
deploy plan).

## OAuth (claude.ai web, Connectors Gallery, ChatGPT Apps)

For browser-based clients that require OAuth 2.1 (DCR + PKCE):

1. In claude.ai → **Settings → Connectors → Add custom connector**
2. URL: `https://mcp.srgplus.com/mcp`
3. Leave OAuth fields empty — the wizard will discover, DCR-register, and
   redirect to a consent page
4. On the consent page: paste your SRG+ workspace API key
5. Tools appear in claude.ai

Endpoints exposed (all under the same hostname as `/mcp`):

| Endpoint | Purpose |
|----------|---------|
| `/.well-known/oauth-authorization-server` | RFC 8414 metadata |
| `/.well-known/oauth-protected-resource` | RFC 9728 metadata |
| `/oauth/register` | RFC 7591 Dynamic Client Registration |
| `/oauth/authorize` | Authorization endpoint with consent page |
| `/oauth/token` | Token endpoint (PKCE S256 required) |
| `/oauth/revoke` | RFC 7009 revocation |

**Backwards compatibility:** the `X-API-Key` header and `Authorization:
Bearer srgplus_...` flows from above still work. OAuth tokens (RFC-shaped
JWTs) are detected automatically when the bearer value doesn't start with
`srgplus_`.

### Multiple workspaces

Each SRG+ workspace API key is scoped to a single workspace, so one OAuth
session today connects one workspace.

To connect Claude to **several workspaces at once**, add the SRG+ connector
multiple times in claude.ai → Settings → Connectors. Each instance goes
through its own OAuth flow with the API key for that workspace:

```
SRG+ (Acme)       → https://mcp.srgplus.com/mcp  → API key for Acme workspace
SRG+ (Personal)   → https://mcp.srgplus.com/mcp  → API key for Personal workspace
SRG+ (Studios)    → https://mcp.srgplus.com/mcp  → API key for Studios workspace
```

Tools from each connector show up in claude.ai under their connector name,
so you can scope a request to a specific workspace by mentioning the
connector ("use SRG+ Acme to find content X").

A single-OAuth multi-workspace flow (Airtable-style: pick multiple
workspaces in one consent screen, server provisions scoped keys
automatically) is tracked in
[SRGDEV-27](https://sergecreator.atlassian.net/browse/SRGDEV-27) and will
land in a future release. Until then, the multi-connector approach above
covers the same use case with no extra code.

### Production secrets

In production, set these via GCP Secret Manager so token state survives
process restarts:

| Env var | Purpose |
|---------|---------|
| `OAUTH_ISSUER` | Canonical issuer URL (e.g. `https://mcp.srgplus.com`) |
| `OAUTH_CLIENT_REGISTRATION_KEY` | HMAC key for DCR `client_id` JWTs |
| `OAUTH_TOKEN_SIGNING_KEY` | HMAC key for codes/access/refresh tokens |
| `OAUTH_API_KEY_ENCRYPTION_KEY` | 32-byte AES-GCM key (base64url) for wrapping the SRG+ workspace api_key inside JWTs |

If any are unset the server generates an ephemeral random key per process —
fine for local development, but every process restart invalidates all
in-flight authorizations.

### How auth works

Each request must carry the workspace API key in either header:

- `X-API-Key: srgplus_...`
- `Authorization: Bearer srgplus_...`

The server doesn't pre-validate the key — it binds it to the SDK's
per-request contextvar via `SRGClient.use_api_key(...)` and lets the SRG+
SDK make the actual call. Bad keys surface as 401 from the upstream API on
the first tool invocation.

A single shared `SRGClient` (and therefore a single `httpx` connection pool)
serves every request, so the per-request overhead is just a contextvar
set/reset — no per-key client construction or cache.

## Local stdio (developer mode)

Use this when you're building locally against SRG+ and want a child-process
MCP without running an HTTP server.

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "srgplus": {
      "command": "uvx",
      "args": ["srgplus-mcp"],
      "env": {
        "SRG_API_KEY": "srgplus_your_key_here"
      }
    }
  }
}
```

Restart Claude Desktop. The `uvx` command downloads and runs the package
automatically — no separate install step needed.

### Claude Code

```bash
claude mcp add srgplus -- uvx srgplus-mcp
export SRG_API_KEY=srgplus_your_key_here
```

## Getting an API key

Log in to SRG+ → **Settings → Workspaces → Select Workspace → API Keys** →
create a new key. Use the same key for both stdio (`SRG_API_KEY` env var) and
hosted HTTP (`X-API-Key` header).

## Available tools

### Hub Profiles
`list_hub_profiles` · `list_managed_hub_profiles` · `get_hub_profile` · `get_hub_profile_by_username` · `filter_hub_profiles` · `create_hub_profile` · `update_hub_profile` · `archive_hub_profile` · `restore_hub_profile` · `delete_hub_profile` · `join_hub_profile` · `invite_to_hub_profile` · `list_invitations` · `update_invitation` · `delete_invitation` · `get_invitation_link` · `move_hub_profile_to_workspace` · `turn_on_hub_profile_community`

### Channels
`list_channels` · `get_channel` · `get_channel_by_name` · `create_channel` · `update_channel` · `archive_channel` · `delete_channel` · `create_category` · `update_category` · `archive_category` · `delete_category` · `get_category_by_slugs` · `create_section` · `update_section` · `delete_section`

### Contents
`list_contents` · `get_content` · `get_content_v2` · `create_content` · `update_content` · `move_content` · `search_contents` · `add_content_to_category` · `add_content_to_categories` · `remove_content_from_categories` · `get_category_references` · `create_content_section` · `update_content_section` · `delete_content_section` · `add_subcontent` · `get_subcontent` · `move_subcontent` · `delete_subcontent` · `patch_content_progression` · `get_progression_stats`

### Assets
`list_assets` · `get_asset` · `search_assets` · `create_image_asset` · `create_video_asset` · `create_file_asset` · `create_media_asset` · `create_embed_asset` · `update_asset` · `patch_media_progression`

### Users & Permissions
`get_user` · `check_user_exists_by_email` · `check_user_exists_by_phone` · `get_workspace_users` · `give_permission` · `delete_permission` · `can_read` · `can_edit` · `can_archive` · `can_create_child` · `can_manage_permissions` · `is_member` · `get_permission_targets` · `list_permission_groups` · `get_permission_group` · `create_permission_group` · `update_permission_group` · `delete_permission_group` · `add_users_to_permission_group` · `remove_user_from_permission_group`

### Workspace
`get_workspace` · `update_workspace` · `get_workspace_hub_profiles` · `list_workspace_actions` · `get_workspace_action` · `create_workspace_action` · `update_workspace_action` · `delete_workspace_action` · `invite_to_workspace` · `get_workspace_invitation_link` · `list_workspace_invitations` · `update_workspace_invitation` · `delete_workspace_invitation`
