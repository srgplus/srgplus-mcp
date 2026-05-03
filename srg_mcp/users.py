from srg_mcp._app import mcp
from srg_mcp._client import get_client
from mcp.types import ToolAnnotations


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title='Get workspace users',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_workspace_users() -> list[dict]:
    """List all users in the current workspace with their roles."""
    client = get_client()
    users = client.permissions.get_workspace_users(client.workspace_id)
    return [u.model_dump(mode="json") for u in users]


@mcp.tool(
    annotations=ToolAnnotations(
        title='Get user',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_user(user_id: str) -> dict:
    """Get a user's full profile by ID."""
    return get_client().users.get(user_id).model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title='Check user exists by email',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def check_user_exists_by_email(email: str) -> bool:
    """Check whether a user account with the given email address exists."""
    return get_client().users.check_exists_with_email(email)


@mcp.tool(
    annotations=ToolAnnotations(
        title='Check user exists by phone',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def check_user_exists_by_phone(phone_number: str) -> bool:
    """Check whether a user account with the given phone number exists (e.g. "+1234567890")."""
    return get_client().users.check_exists_with_phone(phone_number)


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title='List invitations',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_invitations(hub_profile_id: str) -> list[dict]:
    """List all pending invitations for a hub profile."""
    invitations = get_client().invitations.list("HubProfile", hub_profile_id)
    return [inv.model_dump(mode="json") for inv in invitations]


@mcp.tool(
    annotations=ToolAnnotations(
        title='Invite to hub profile',
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def invite_to_hub_profile(
    hub_profile_id: str,
    emails: list[str],
    role_id: int,
) -> dict:
    """Send email invitations to join a hub profile.

    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    """
    result = get_client().invitations.invite(
        "HubProfile",
        hub_profile_id,
        role_id=role_id,
        emails=emails,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title='Invite to workspace',
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def invite_to_workspace(emails: list[str], role_id: int) -> dict:
    """Send email invitations to join the current workspace.

    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    """
    client = get_client()
    result = client.invitations.invite(
        "Workspace",
        client.workspace_id,
        role_id=role_id,
        emails=emails,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title='Get invitation link',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_invitation_link(
    hub_profile_id: str,
    email: str,
    role_id: int,
) -> dict:
    """Generate a shareable invitation link for a single email address.

    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    Returns the invitation ID and access link URL.
    """
    result = get_client().invitations.invite_with_link(
        "HubProfile",
        hub_profile_id,
        role_id=role_id,
        email=email,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title='Update invitation',
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_invitation(
    hub_profile_id: str,
    invitation_id: str,
    role_id: int,
) -> str:
    """Update the role assigned to a pending invitation.

    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    """
    get_client().invitations.update(
        "HubProfile",
        hub_profile_id,
        invitation_id,
        role_id=role_id,
    )
    return "updated"


@mcp.tool(
    annotations=ToolAnnotations(
        title='Delete invitation',
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_invitation(hub_profile_id: str, invitation_id: str) -> str:
    """Cancel and permanently delete a pending invitation."""
    get_client().invitations.delete("HubProfile", hub_profile_id, invitation_id)
    return "deleted"


@mcp.tool(
    annotations=ToolAnnotations(
        title='List workspace invitations',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def list_workspace_invitations() -> list[dict]:
    """List all pending invitations for the current workspace."""
    client = get_client()
    invitations = client.invitations.list("Workspace", client.workspace_id)
    return [inv.model_dump(mode="json") for inv in invitations]


@mcp.tool(
    annotations=ToolAnnotations(
        title='Get workspace invitation link',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_workspace_invitation_link(email: str, role_id: int) -> dict:
    """Generate a shareable invitation link for a workspace for a single email.

    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    Returns the invitation ID and access link URL.
    """
    client = get_client()
    result = client.invitations.invite_with_link(
        "Workspace",
        client.workspace_id,
        role_id=role_id,
        email=email,
    )
    return result.model_dump(mode="json")


@mcp.tool(
    annotations=ToolAnnotations(
        title='Update workspace invitation',
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def update_workspace_invitation(invitation_id: str, role_id: int) -> str:
    """Update the role assigned to a pending workspace invitation.

    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    """
    client = get_client()
    client.invitations.update(
        "Workspace",
        client.workspace_id,
        invitation_id,
        role_id=role_id,
    )
    return "updated"


@mcp.tool(
    annotations=ToolAnnotations(
        title='Delete workspace invitation',
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_workspace_invitation(invitation_id: str) -> str:
    """Cancel and permanently delete a pending workspace invitation."""
    client = get_client()
    client.invitations.delete("Workspace", client.workspace_id, invitation_id)
    return "deleted"


# ---------------------------------------------------------------------------
# Permissions — checks
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title='Check read permission',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def can_read(target_id: str, target_type: str) -> bool:
    """Check whether the current user has read access to a target.

    target_type: "HubProfile", "Workspace", "Channel", "Content", etc.
    """
    return get_client().permissions.can_read(
        target_id=target_id, target_type=target_type
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title='Check edit permission',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def can_edit(target_id: str, target_type: str) -> bool:
    """Check whether the current user has edit access to a target.

    target_type: "HubProfile", "Workspace", "Channel", "Content", etc.
    """
    return get_client().permissions.can_edit(
        target_id=target_id, target_type=target_type
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title='Check create-child permission',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def can_create_child(
    parent_target_type: str,
    parent_target_id: str,
    child_target_type: str,
) -> bool:
    """Check whether the current user can create a child resource inside a parent.

    Example: can the user create a "Channel" inside a "HubProfile"?
    """
    return get_client().permissions.can_create_child(
        parent_target_type=parent_target_type,
        parent_target_id=parent_target_id,
        child_target_type=child_target_type,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title='Check manage-permissions permission',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def can_manage_permissions(target_id: str, target_type: str) -> bool:
    """Check whether the current user can grant/revoke roles on a target."""
    return get_client().permissions.can_manage_permissions(
        target_id=target_id, target_type=target_type
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title='Check archive permission',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def can_archive(target_id: str, target_type: str) -> bool:
    """Check whether the current user can archive a target."""
    return get_client().permissions.can_archive(
        target_id=target_id, target_type=target_type
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title='Check membership',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def is_member(target_id: str, target_type: str) -> bool:
    """Check whether the current user is a member of a target (any role)."""
    return get_client().permissions.is_member(
        target_id=target_id, target_type=target_type
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title='Get permission targets',
        readOnlyHint=True,
        destructiveHint=False,
        openWorldHint=True,
    )
)
def get_permission_targets(
    target_type: str,
    child_target_type: str | None = None,
    parent_target_id: str | None = None,
) -> list[dict]:
    """Get all targets of a given type accessible to the current user.

    target_type: "HubProfile", "Workspace", "Channel", etc.
    child_target_type: filter to targets that have a child of this type
    parent_target_id: filter to targets belonging to this parent
    Returns each target with its permission flags (can_edit, can_archive, etc.)
    """
    targets = get_client().permissions.get_targets(
        target_type,
        child_target_type=child_target_type,
        parent_target_id=parent_target_id,
    )
    return [t.model_dump(mode="json") for t in targets]


# ---------------------------------------------------------------------------
# Permissions — assign / revoke
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        title='Grant permission',
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
) -> str:
    """Grant a user a role on a target (hub profile, workspace, channel, etc.).

    target_type: "HubProfile", "Workspace", or "Channel"
    role_id: 1 = Admin, 2 = Editor, 3 = Viewer
    """
    get_client().permissions.give(
        user_id=user_id,
        target_id=target_id,
        target_type=target_type,
        role_id=role_id,
    )
    return "granted"


@mcp.tool(
    annotations=ToolAnnotations(
        title='Revoke permission',
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    )
)
def delete_permission(user_id: str, target_id: str, target_type: str) -> str:
    """Revoke all permissions a user has on a target.

    target_type: "HubProfile", "Workspace", or "Channel"
    """
    get_client().permissions.delete(
        target_type=target_type,
        target_id=target_id,
        user_id=user_id,
    )
    return "revoked"
