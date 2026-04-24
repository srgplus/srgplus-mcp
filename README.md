# srgplus-mcp

MCP server for [SRG+](https://srgplus.app) — lets Claude manage hubs, channels, content, assets, users, and workspaces through the SRG+ API.

## Installation

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

Restart Claude Desktop. The `uvx` command downloads and runs the package automatically — no separate install step needed.

### Claude Code

```bash
claude mcp add srgplus -- uvx srgplus-mcp
```

Then set the environment variable:

```bash
export SRG_API_KEY=srgplus_your_key_here
```

## Getting an API key

Log in to SRG+, go to **Settings → Workspaces → Select Workspace → API Keys**, and create a new key.

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
