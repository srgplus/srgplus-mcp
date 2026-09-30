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


def test_guide_says_where_archived_hubs_went():
    text = " ".join(SRGPLUS_GUIDE.split())  # immune to re-wrapping
    assert "Archived hubs are left out; `include_archived=True` lists them too" in text
    assert "Archived hubs and channels drop out of `list_hub_profiles` / `list_channels`" in text


def test_guide_new_hub_recipe_is_private_and_core_only():
    text = " ".join(SRGPLUS_GUIDE.split())  # immune to re-wrapping
    assert "## New hub with channels and categories" in SRGPLUS_GUIDE
    # Internal hubs and their channels are created Private.
    assert 'availability_level="Private"' in text
    assert 'privacy="Private"' in text
    # The recipe only uses tools the core connector actually serves.
    for tool in ("create_hub_profile", "create_channel", "create_category"):
        assert tool in CORE_TOOL_NAMES
        assert f"`{tool}(" in SRGPLUS_GUIDE
    # Full-replace updates stay out of core; renames use the PATCH tools.
    assert "update_channel" not in SRGPLUS_GUIDE
    assert "update_category" not in SRGPLUS_GUIDE
    for tool in ("rename_channel", "rename_category"):
        assert tool in CORE_TOOL_NAMES
        assert f"`{tool}(" in SRGPLUS_GUIDE


def test_guide_says_video_covers_are_automatic_and_not_a_reason_to_reupload():
    text = " ".join(SRGPLUS_GUIDE.split())  # immune to re-wrapping
    assert "## Video covers are automatic" in SRGPLUS_GUIDE
    assert "for EVERY upload" in text and "within about a minute" in text
    # How to tell a real cover from the always-present signed URLs.
    assert "non-zero `cover` width, height and size" in text
    assert "`cover.urls` are signed URLs that exist even when there is no cover yet" in text
    # What to do, and what not to do.
    assert "NEVER archive or re-upload" in text
    assert "Still no cover after about 15 minutes: tell the user" in text
    assert "set a CONTENT's cover from a Drive image" in text


def test_guide_upload_names_carry_no_extension():
    text = " ".join(SRGPLUS_GUIDE.split())
    assert "WITHOUT its extension" in text and "a trailing `.jpg` is dropped" in text


def test_instructions_and_docstrings_say_a_late_video_cover_is_normal():
    for marker in ("EVERY upload", "never archive or re-upload"):
        assert marker in mcp.instructions
    for tool in ("get_asset", "complete_upload", "list_drive_files", "upload_asset"):
        doc = " ".join(mcp._tool_manager.get_tool(tool).description.split())
        assert "re-upload" in doc, tool
    for tool in ("set_cover", "set_covers"):
        doc = " ".join(mcp._tool_manager.get_tool(tool).description.split())
        assert "CONTENT" in doc and "video file's own preview" in doc, tool
