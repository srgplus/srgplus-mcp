from srg_mcp._app import mcp
from srg_mcp._client import get_client


@mcp.tool()
def list_hub_profiles() -> list[dict]:
    """List all hub profiles in the workspace."""
    return [p.model_dump(mode="json") for p in get_client().hub_profiles.list()]


@mcp.tool()
def list_managed_hub_profiles() -> list[dict]:
    """List hub profiles where the current API key user has Admin or Editor role."""
    return [p.model_dump(mode="json") for p in get_client().hub_profiles.list_managed()]


@mcp.tool()
def get_hub_profile(hub_profile_id: str) -> dict:
    """Get full hub profile details by ID."""
    return get_client().hub_profiles.get(hub_profile_id).model_dump(mode="json")


@mcp.tool()
def get_hub_profile_by_username(username: str) -> dict:
    """Get hub profile details by its URL username/slug."""
    return get_client().hub_profiles.get_by_username(username).model_dump(mode="json")


@mcp.tool()
def filter_hub_profiles(
    ids: list[str],
    availability_level: str | None = None,
) -> list[dict]:
    """Batch-fetch lightweight hub profile data for a list of IDs.

    availability_level: "Public" or "Private" to filter by visibility
    """
    return [
        p.model_dump(mode="json")
        for p in get_client().hub_profiles.filter(
            ids=ids,
            availability_level=availability_level,  # type: ignore[arg-type]
        )
    ]


@mcp.tool()
def create_hub_profile(
    name: str,
    user_name: str,
    sub_name: str | None = None,
    description: str | None = None,
    primary_url: str | None = None,
    availability_level: str = "Public",
    app_clip_on: bool = False,
    workspace_id: str | None = None,
    widgets: list[dict] | None = None,
    buttons: list[dict] | None = None,
) -> dict:
    """Create a new hub profile in the workspace.

    availability_level: "Public" (default) or "Private"
    primary_url: optional external URL shown on the profile
    app_clip_on: enable iOS App Clip
    workspace_id: workspace to create in (uses default if omitted)
    widgets: profile widget configuration objects
    buttons: action buttons, each
        {"title": "...", "logic": {"type": "...", "url": "..."}}
    """
    from srg.schemas.hub_profile import ActionButtonLogicUpsert, ActionButtonUpsert

    btn_objs = (
        [
            ActionButtonUpsert(
                title=b["title"],
                logic=ActionButtonLogicUpsert(**b["logic"]),
            )
            for b in buttons
        ]
        if buttons
        else None
    )
    result = get_client().hub_profiles.create(
        name=name,
        user_name=user_name,
        sub_name=sub_name,
        description=description,
        primary_url=primary_url,
        availability_level=availability_level,  # type: ignore[arg-type]
        app_clip_on=app_clip_on,
        workspace_id=workspace_id,
        widgets=widgets,
        buttons=btn_objs,
    )
    return result.model_dump(mode="json")


@mcp.tool()
def update_hub_profile(
    hub_profile_id: str,
    name: str,
    user_name: str,
    sub_name: str | None = None,
    description: str | None = None,
    primary_url: str | None = None,
    availability_level: str = "Public",
    app_clip_on: bool = False,
    widgets: list[dict] | None = None,
    buttons: list[dict] | None = None,
) -> dict:
    """Update an existing hub profile's metadata.

    All fields are overwritten — provide the full desired state.
    availability_level: "Public" or "Private"
    primary_url: optional external URL shown on the profile
    app_clip_on: enable iOS App Clip
    widgets: profile widget configuration objects (replaces existing)
    buttons: action buttons (replaces existing), each
        {"title": "...", "logic": {"type": "...", "url": "..."}}
    """
    from srg.schemas.hub_profile import ActionButtonLogicUpsert, ActionButtonUpsert

    btn_objs = (
        [
            ActionButtonUpsert(
                title=b["title"],
                logic=ActionButtonLogicUpsert(**b["logic"]),
            )
            for b in buttons
        ]
        if buttons
        else None
    )
    result = get_client().hub_profiles.update(
        hub_profile_id,
        name=name,
        user_name=user_name,
        sub_name=sub_name,
        description=description,
        primary_url=primary_url,
        availability_level=availability_level,  # type: ignore[arg-type]
        app_clip_on=app_clip_on,
        widgets=widgets,
        buttons=btn_objs,
    )
    return result.model_dump(mode="json")


@mcp.tool()
def archive_hub_profile(hub_profile_id: str) -> dict | None:
    """Archive a hub profile (hidden from listings, content preserved)."""
    return get_client().hub_profiles.archive(hub_profile_id)


@mcp.tool()
def restore_hub_profile(hub_profile_id: str) -> dict | None:
    """Restore a previously archived hub profile."""
    return get_client().hub_profiles.restore(hub_profile_id)


@mcp.tool()
def delete_hub_profile(hub_profile_id: str) -> str:
    """Permanently delete a hub profile and all its data. Irreversible."""
    get_client().hub_profiles.delete(hub_profile_id)
    return "deleted"


@mcp.tool()
def join_hub_profile(hub_profile_id: str) -> dict | None:
    """Join a public hub profile as the current API key user."""
    return get_client().hub_profiles.join(hub_profile_id)


@mcp.tool()
def move_hub_profile_to_workspace(
    hub_profile_id: str, workspace_id: str
) -> dict | None:
    """Transfer a hub profile to a different workspace (preserves content)."""
    return get_client().hub_profiles.move_to_workspace(hub_profile_id, workspace_id)


@mcp.tool()
def turn_on_hub_profile_community(hub_profile_id: str) -> dict | None:
    """Enable community features for a hub profile (posts, comments, reactions)."""
    return get_client().hub_profiles.turn_on_community(hub_profile_id)
