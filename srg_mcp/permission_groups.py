from srg_mcp._app import mcp
from srg_mcp._client import get_client
from mcp.types import ToolAnnotations


@mcp.tool(
    annotations=ToolAnnotations(
        title='List permission groups',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_permission_groups(target_type: str, target_id: str) -> list[dict]:
    """List all permission groups for a target.

    target_type: "HubProfile" or "Workspace"
    """
    groups = get_client().permission_groups.list(target_type, target_id)
    return [g.model_dump(mode="json") for g in groups]


@mcp.tool(
    annotations=ToolAnnotations(
        title='Get permission group',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_permission_group(group_id: str) -> dict:
    """Get a permission group by ID, including its members."""
    return get_client().permission_groups.get(group_id).model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title='Create permission group',
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def create_permission_group(
    target_type: str,
    target_id: str,
    name: str,
) -> str:
    """Create a new permission group on a target. Returns the new group ID.

    target_type: "HubProfile" or "Workspace"
    """
    return get_client().permission_groups.create(target_type, target_id, name=name)


@mcp.tool(
    annotations=ToolAnnotations(
        title='Update permission group',
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_permission_group(group_id: str, name: str) -> dict | None:
    """Rename a permission group."""
    return get_client().permission_groups.update(group_id, name=name)


@mcp.tool(
    annotations=ToolAnnotations(
        title='Delete permission group',
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_permission_group(group_id: str) -> str:
    """Permanently delete a permission group. Members lose inherited permissions."""
    get_client().permission_groups.delete(group_id)
    return "deleted"


@mcp.tool(
    annotations=ToolAnnotations(
        title='Add users to permission group',
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def add_users_to_permission_group(group_id: str, user_ids: list[str]) -> dict | None:
    """Add one or more users to a permission group."""
    return get_client().permission_groups.add_users(group_id, user_ids=user_ids)


@mcp.tool(
    annotations=ToolAnnotations(
        title='Remove user from permission group',
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def remove_user_from_permission_group(group_id: str, user_id: str) -> str:
    """Remove a user from a permission group."""
    get_client().permission_groups.remove_user(group_id, user_id)
    return "removed"
