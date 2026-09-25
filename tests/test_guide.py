"""The connector guide and the always-on instructions state the SRG+
Markdown standard for Text widgets: GitHub Flavored Markdown + ==highlight==.
The guide's advice matches the tools, and its shell snippets reach agents
exactly as written."""

from __future__ import annotations

from srg_mcp._app import mcp
from srg_mcp.guide import SRGPLUS_GUIDE, get_srgplus_guide
from srg_mcp.serve.profiles import CORE_TOOL_NAMES
from srg_mcp.uploads import create_upload

# The macOS size/pixel snippet as tested in a shell: printf keeps its `\n`,
# each continued line keeps its trailing `\`, and the fence stays indented
# under list item 1 so the rest of the guide is not swallowed into code.
MACOS_SIZES_SNIPPET = r"""
   ```bash
   cd "<folder>"; for f in *.jpg; do printf '{"path":"%s","size":%s,"width":%s,"height":%s}\n' \
     "$PWD/$f" "$(stat -f%z "$f")" \
     "$(sips -g pixelWidth "$f" | awk '/pixelWidth/{print $2}')" \
     "$(sips -g pixelHeight "$f" | awk '/pixelHeight/{print $2}')"; done
   ```
"""


def _snippet_lines(text: str) -> list[str]:
    """The snippet's four shell lines in ``text``, stripped of indentation."""
    lines = [line.strip() for line in text.splitlines()]
    start = next(i for i, line in enumerate(lines) if "for f in *.jpg" in line)
    return lines[start : start + 4]


def test_guide_tool_returns_the_guide():
    assert get_srgplus_guide() == SRGPLUS_GUIDE


def test_guide_states_the_markdown_standard():
    assert "## Text widget Markdown (the SRG+ standard)" in SRGPLUS_GUIDE
    for rule in (
        "GitHub Flavored Markdown",
        "==highlight==",
        "A blank line between blocks",
        "- [ ] to do",
        "| :----- | -------: |",
        "(`\\|`)",  # a pipe inside a table cell is written with a backslash
        "<br>",
        "&nbsp;",
        "20,000 characters per Text widget",
        "send everything else back exactly as it was",
    ):
        assert rule in SRGPLUS_GUIDE, rule


def test_instructions_carry_the_markdown_pitfalls():
    instructions = mcp.instructions
    assert "GitHub Flavored Markdown plus ==highlight==" in instructions
    assert "\\|" in instructions
    assert "byte for byte" in instructions


def test_guide_upload_snippet_reaches_agents_as_tested():
    assert MACOS_SIZES_SNIPPET in SRGPLUS_GUIDE


def test_create_upload_docs_carry_the_same_snippet():
    # The docstring is the tool description agents receive. It is not a raw
    # string, so its source must spell the backslashes as \\n and \\.
    expected = _snippet_lines(MACOS_SIZES_SNIPPET)
    expected[0] = expected[0].removeprefix('cd "<folder>"; ')
    assert _snippet_lines(create_upload.__doc__) == expected


def test_guide_workspace_advice_matches_the_tools():
    text = " ".join(SRGPLUS_GUIDE.split())  # immune to re-wrapping
    # list_workspaces returns {id, name} only; the hub count was dropped.
    assert "hub_profile_count" not in SRGPLUS_GUIDE
    assert "`list_workspaces()` — slim rows (id, name)" in text
    assert "brands come from `list_hub_profiles(workspace_id)`" in text
    # get_workspace takes workspace_id and is not in the curated core profile.
    assert "get_workspace" not in CORE_TOOL_NAMES
    assert "get_workspace(id)" not in SRGPLUS_GUIDE
    assert (
        "`get_workspace(workspace_id)`, with seats and subscription, is on the"
        " full `/mcp` only" in text
    )
