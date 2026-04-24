from srg_mcp._app import mcp

import srg_mcp.hub_profiles  # noqa: F401
import srg_mcp.channels  # noqa: F401
import srg_mcp.contents  # noqa: F401
import srg_mcp.assets  # noqa: F401
import srg_mcp.users  # noqa: F401
import srg_mcp.workspaces  # noqa: F401
import srg_mcp.permission_groups  # noqa: F401


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
