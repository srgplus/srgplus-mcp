from srg_mcp._app import mcp
from srg_mcp._client import get_client
from mcp.types import ToolAnnotations


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get workspace users",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_workspace_users(workspace_id: str) -> list[dict]:
    """List all users in a workspace with their roles.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    users = get_client().permissions.get_workspace_users(workspace_id)
    return [u.model_dump(mode="json") for u in users]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get user",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_user(user_id: str, workspace_id: str) -> dict:
    """Get a user's full profile by ID.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return (
        get_client()
        .users.get(user_id, workspace_id=workspace_id)
        .model_dump(mode="json")
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check user exists by email",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def check_user_exists_by_email(email: str, workspace_id: str) -> bool:
    """Check whether a user account with the given email address exists.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().users.check_exists_with_email(email, workspace_id=workspace_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check user exists by phone",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def check_user_exists_by_phone(phone_number: str, workspace_id: str) -> bool:
    """Check whether a user account with the given phone number exists (e.g. "+1234567890").

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().users.check_exists_with_phone(
        phone_number, workspace_id=workspace_id
    )


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="List invitations",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_invitations(hub_profile_id: str, workspace_id: str) -> list[dict]:
    """List all pending invitations for a hub profile.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    invitations = get_client().invitations.list(
        "HubProfile", hub_profile_id, workspace_id=workspace_id
    )
    return [inv.model_dump(mode="json") for inv in invitations]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Invite to hub profile",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def invite_to_hub_profile(
    hub_profile_id: str,
    emails: list[str],
    role_id: int,
    workspace_id: str,
) -> dict:
    """Send email invitations to join a hub profile.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    """
    result = get_client().invitations.invite(
        "HubProfile",
        hub_profile_id,
        role_id=role_id,
        emails=emails,
        workspace_id=workspace_id,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Invite to workspace",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def invite_to_workspace(
    emails: list[str],
    role_id: int,
    workspace_id: str,
) -> dict:
    """Send email invitations to join a workspace.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    """
    result = get_client().invitations.invite(
        "Workspace",
        workspace_id,
        role_id=role_id,
        emails=emails,
        workspace_id=workspace_id,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get invitation link",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_invitation_link(
    hub_profile_id: str,
    email: str,
    role_id: int,
    workspace_id: str,
) -> dict:
    """Generate a shareable invitation link for a single email address.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    Returns the invitation ID and access link URL.
    """
    result = get_client().invitations.invite_with_link(
        "HubProfile",
        hub_profile_id,
        role_id=role_id,
        email=email,
        workspace_id=workspace_id,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update invitation",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_invitation(
    hub_profile_id: str,
    invitation_id: str,
    role_id: int,
    workspace_id: str,
) -> str:
    """Update the role assigned to a pending invitation.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    """
    get_client().invitations.update(
        "HubProfile",
        hub_profile_id,
        invitation_id,
        role_id=role_id,
        workspace_id=workspace_id,
    )
    return "updated"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete invitation",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_invitation(
    hub_profile_id: str,
    invitation_id: str,
    workspace_id: str,
) -> str:
    """Cancel and permanently delete a pending invitation.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    get_client().invitations.delete(
        "HubProfile", hub_profile_id, invitation_id, workspace_id=workspace_id
    )
    return "deleted"


@mcp.tool(
    annotations=ToolAnnotations(
        title="List workspace invitations",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_workspace_invitations(workspace_id: str) -> list[dict]:
    """List all pending invitations for a workspace.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    invitations = get_client().invitations.list(
        "Workspace", workspace_id, workspace_id=workspace_id
    )
    return [inv.model_dump(mode="json") for inv in invitations]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get workspace invitation link",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_workspace_invitation_link(
    email: str,
    role_id: int,
    workspace_id: str,
) -> dict:
    """Generate a shareable invitation link for a workspace for a single email.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    Returns the invitation ID and access link URL.
    """
    result = get_client().invitations.invite_with_link(
        "Workspace",
        workspace_id,
        role_id=role_id,
        email=email,
        workspace_id=workspace_id,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update workspace invitation",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_workspace_invitation(
    invitation_id: str,
    role_id: int,
    workspace_id: str,
) -> str:
    """Update the role assigned to a pending workspace invitation.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    """
    get_client().invitations.update(
        "Workspace",
        workspace_id,
        invitation_id,
        role_id=role_id,
        workspace_id=workspace_id,
    )
    return "updated"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete workspace invitation",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_workspace_invitation(invitation_id: str, workspace_id: str) -> str:
    """Cancel and permanently delete a pending workspace invitation.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    get_client().invitations.delete(
        "Workspace", workspace_id, invitation_id, workspace_id=workspace_id
    )
    return "deleted"


# ---------------------------------------------------------------------------
# Permissions — checks
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check read permission",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def can_read(target_id: str, target_type: str, workspace_id: str) -> bool:
    """Check whether the current user has read access to a target.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    target_type: "HubProfile", "Workspace", "Channel", "Content", etc.
    """
    return get_client().permissions.can_read(
        target_id=target_id, target_type=target_type, workspace_id=workspace_id
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check edit permission",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def can_edit(target_id: str, target_type: str, workspace_id: str) -> bool:
    """Check whether the current user has edit access to a target.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    target_type: "HubProfile", "Workspace", "Channel", "Content", etc.
    """
    return get_client().permissions.can_edit(
        target_id=target_id, target_type=target_type, workspace_id=workspace_id
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check create-child permission",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def can_create_child(
    parent_target_type: str,
    parent_target_id: str,
    child_target_type: str,
    workspace_id: str,
) -> bool:
    """Check whether the current user can create a child resource inside a parent.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    Example: can the user create a "Channel" inside a "HubProfile"?
    """
    return get_client().permissions.can_create_child(
        parent_target_type=parent_target_type,
        parent_target_id=parent_target_id,
        child_target_type=child_target_type,
        workspace_id=workspace_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check manage-permissions permission",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def can_manage_permissions(target_id: str, target_type: str, workspace_id: str) -> bool:
    """Check whether the current user can grant/revoke roles on a target.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().permissions.can_manage_permissions(
        target_id=target_id, target_type=target_type, workspace_id=workspace_id
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check archive permission",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def can_archive(target_id: str, target_type: str, workspace_id: str) -> bool:
    """Check whether the current user can archive a target.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().permissions.can_archive(
        target_id=target_id, target_type=target_type, workspace_id=workspace_id
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check membership",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def is_member(target_id: str, target_type: str, workspace_id: str) -> bool:
    """Check whether the current user is a member of a target (any role).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    """
    return get_client().permissions.is_member(
        target_id=target_id, target_type=target_type, workspace_id=workspace_id
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get permission targets",
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_permission_targets(
    target_type: str,
    workspace_id: str,
    child_target_type: str | None = None,
    parent_target_id: str | None = None,
) -> list[dict]:
    """Get all targets of a given type accessible to the current user.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    target_type: "HubProfile", "Workspace", "Channel", etc.
    child_target_type: filter to targets that have a child of this type
    parent_target_id: filter to targets belonging to this parent
    Returns each target with its permission flags (can_edit, can_archive, etc.)
    """
    targets = get_client().permissions.get_targets(
        target_type,
        child_target_type=child_target_type,
        parent_target_id=parent_target_id,
        workspace_id=workspace_id,
    )
    return [t.model_dump(mode="json") for t in targets]


# ---------------------------------------------------------------------------
# Permissions — assign / revoke
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title="Grant permission",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def give_permission(
    user_id: str,
    target_id: str,
    target_type: str,
    role_id: int,
    workspace_id: str,
) -> str:
    """Grant a user a role on a target (hub profile, workspace, channel, etc.).

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    target_type: "HubProfile", "Workspace", or "Channel"
    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    """
    get_client().permissions.give(
        user_id=user_id,
        target_id=target_id,
        target_type=target_type,
        role_id=role_id,
        workspace_id=workspace_id,
    )
    return "granted"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Revoke permission",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_permission(
    user_id: str,
    target_id: str,
    target_type: str,
    workspace_id: str,
) -> str:
    """Revoke all permissions a user has on a target.

    workspace_id: target workspace ID — get available IDs from list_workspaces()
    target_type: "HubProfile", "Workspace", or "Channel"
    """
    get_client().permissions.delete(
        target_type=target_type,
        target_id=target_id,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    return "revoked"
