"""The connector guide and the always-on instructions state the SRG+
Markdown standard for Text widgets: GitHub Flavored Markdown + ==highlight==."""

from __future__ import annotations

from srg_mcp._app import mcp
from srg_mcp.guide import SRGPLUS_GUIDE, get_srgplus_guide


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
