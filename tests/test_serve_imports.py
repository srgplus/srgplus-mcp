"""The hosted server (serve/main.py) imports the tool modules itself, apart from
server.py. A module missing there leaves its tools unregistered, and the core
profile then refuses to start the server (the prod deploy of SRGDEV-824/825
failed that way while every unit test passed)."""

from __future__ import annotations

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "srg_mcp"
TOOL_IMPORT = re.compile(r"^import (srg_mcp\.\w+)\b", re.MULTILINE)


def _tool_modules(path: Path) -> set[str]:
    return set(TOOL_IMPORT.findall(path.read_text())) - {"srg_mcp._client"}


def test_hosted_server_imports_every_tool_module_of_the_stdio_server():
    stdio = _tool_modules(PACKAGE / "server.py")
    hosted = _tool_modules(PACKAGE / "serve" / "main.py")
    assert stdio, "server.py imports no tool modules?"
    assert stdio <= hosted, f"serve/main.py misses {sorted(stdio - hosted)}"
