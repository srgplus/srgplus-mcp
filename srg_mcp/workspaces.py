from srg_mcp._app import mcp
from srg_mcp._client import get_client


@mcp.tool()
def get_workspace() -> dict:
    """Get full details of the current workspace (name, seats, subscription, hub profiles)."""
    client = get_client()
    return client.workspaces.get(client.workspace_id).model_dump(mode="json")


@mcp.tool()
def update_workspace(name: str) -> dict:
    """Update the current workspace's display name."""
    client = get_client()
    result = client.workspaces.update(client.workspace_id, name=name)
    return result.model_dump(mode="json")


@mcp.tool()
def get_workspace_hub_profiles() -> list[dict]:
    """List all hub profiles in the current workspace (minimal representation)."""
    client = get_client()
    profiles = client.workspaces.get_hub_profiles(client.workspace_id)
    return [p.model_dump(mode="json") for p in profiles]


# ---------------------------------------------------------------------------
# Workspace actions (automations)
# ---------------------------------------------------------------------------


@mcp.tool()
def list_workspace_actions() -> list[dict]:
    """List all automation actions configured on the current workspace."""
    client = get_client()
    actions = client.workspaces.list_actions(client.workspace_id)
    return [a.model_dump(mode="json") for a in actions]


@mcp.tool()
def get_workspace_action(action_id: str) -> dict:
    """Get full details of a workspace automation action by ID."""
    client = get_client()
    return client.workspaces.get_action(client.workspace_id, action_id).model_dump(
        mode="json"
    )


@mcp.tool()
def create_workspace_action(
    title: str,
    metadata: dict,
    hub_profile_ids: list[str] | None = None,
    details: str | None = None,
) -> str:
    """Create a workspace automation action. Returns the new action ID.

    metadata example for a webhook trigger:
      {"$type": "ProgressionUpdatedMetadata", "webhookUrl": "https://..."}
    hub_profile_ids: profiles this action applies to (default: all)
    """
    client = get_client()
    return client.workspaces.create_action(
        client.workspace_id,
        title=title,
        metadata=metadata,
        hub_profile_ids=hub_profile_ids,
        details=details,
    )


@mcp.tool()
def update_workspace_action(
    action_id: str,
    title: str,
    metadata: dict,
    hub_profile_ids: list[str] | None = None,
    details: str | None = None,
) -> dict | None:
    """Update a workspace automation action. All fields are overwritten.

    metadata example: {"$type": "ProgressionUpdatedMetadata", "webhookUrl": "https://..."}
    """
    client = get_client()
    return client.workspaces.update_action(
        client.workspace_id,
        action_id,
        title=title,
        metadata=metadata,
        hub_profile_ids=hub_profile_ids,
        details=details,
    )


@mcp.tool()
def delete_workspace_action(action_id: str) -> str:
    """Permanently delete a workspace automation action."""
    client = get_client()
    client.workspaces.delete_action(client.workspace_id, action_id)
    return "deleted"
