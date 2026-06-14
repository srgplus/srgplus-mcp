from srg_mcp._app import mcp
from srg_mcp._client import get_client
from mcp.types import ToolAnnotations


@mcp.tool(
    annotations=ToolAnnotations(
        title="List workspaces",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_workspaces() -> list[dict]:
    """List all workspaces accessible with the current API key(s).

    Returns a SLIM row per workspace — id, name, hub_profile_count — which is
    all you need to pick a workspace_id for other tools. For full details
    (seats, subscription, hub profiles) call get_workspace(workspace_id).

    A user-level key (srgplus_u_) returns every workspace it can reach; multiple
    keys are merged. The list comes from the single bulk call made when the key
    was resolved, so it is one response, not one request per workspace.
    """
    client = get_client()
    overview = getattr(client, "workspaces_overview", None)
    if overview is None:  # SDK < 0.2.4 fallback: full fetch per workspace
        return [
            client.workspaces.get(ws_id).model_dump(mode="json")
            for ws_id in client.workspace_ids
        ]
    return [
        {
            "id": str(ws.get("id")),
            "name": ws.get("name"),
            "hub_profile_count": len(ws.get("hubProfiles") or []),
        }
        for ws in overview
    ]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get workspace",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_workspace(workspace_id: str) -> dict:
    """Get full details of a workspace (name, seats, subscription, hub profiles).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().workspaces.get(workspace_id).model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update workspace",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_workspace(workspace_id: str, name: str) -> dict:
    """Update a workspace's display name.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    result = get_client().workspaces.update(workspace_id, name=name)
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get workspace hub profiles",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_workspace_hub_profiles(workspace_id: str) -> list[dict]:
    """List all hub profiles in a workspace (minimal representation).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    profiles = get_client().workspaces.get_hub_profiles(workspace_id)
    return [p.model_dump(mode="json") for p in profiles]


# ---------------------------------------------------------------------------
# Workspace actions (automations)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="List workspace actions",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_workspace_actions(workspace_id: str) -> list[dict]:
    """List all automation actions configured on a workspace.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    actions = get_client().workspaces.list_actions(workspace_id)
    return [a.model_dump(mode="json") for a in actions]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get workspace action",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_workspace_action(action_id: str, workspace_id: str) -> dict:
    """Get full details of a workspace automation action by ID.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return (
        get_client()
        .workspaces.get_action(action_id, workspace_id=workspace_id)
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Create workspace action",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_workspace_action(
    workspace_id: str,
    title: str,
    metadata: dict,
    hub_profile_ids: list[str] | None = None,
    details: str | None = None,
) -> str:
    """Create a workspace automation action. Returns the new action ID.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    metadata example for a webhook trigger:
      {"$type": "ProgressionUpdatedMetadata", "webhookUrl": "https://..."}
    hub_profile_ids: profiles this action applies to (default: all)
    """
    return get_client().workspaces.create_action(
        workspace_id,
        title=title,
        metadata=metadata,
        hub_profile_ids=hub_profile_ids,
        details=details,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update workspace action",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_workspace_action(
    action_id: str,
    workspace_id: str,
    title: str,
    metadata: dict,
    hub_profile_ids: list[str] | None = None,
    details: str | None = None,
) -> dict | None:
    """Update a workspace automation action. All fields are overwritten.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    metadata example: {"$type": "ProgressionUpdatedMetadata", "webhookUrl": "https://..."}
    """
    return get_client().workspaces.update_action(
        action_id,
        workspace_id=workspace_id,
        title=title,
        metadata=metadata,
        hub_profile_ids=hub_profile_ids,
        details=details,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete workspace action",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_workspace_action(action_id: str, workspace_id: str) -> str:
    """Permanently delete a workspace automation action.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    get_client().workspaces.delete_action(action_id, workspace_id=workspace_id)
    return "deleted"
