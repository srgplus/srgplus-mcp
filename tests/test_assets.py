"""Unit tests for the `upload_asset` helpers.

These cover the pure, offline parts of the new tool: source validation
(exactly one of source_url / base64_content) and extension inference. The
full upload path hits the SRG+ API + object storage and is exercised by
the SDK's own suite, so it is out of scope here.
"""

from __future__ import annotations

import pytest

from srg_mcp.assets import _infer_extension, _validate_single_source


def test_validate_single_source_accepts_url_only():
    _validate_single_source("https://example.com/y.pdf", None)


def test_validate_single_source_accepts_base64_only():
    _validate_single_source(None, "Zm9v")


def test_validate_single_source_rejects_neither():
    with pytest.raises(ValueError):
        _validate_single_source(None, None)


def test_validate_single_source_rejects_both():
    with pytest.raises(ValueError):
        _validate_single_source("https://example.com/y.pdf", "Zm9v")


@pytest.mark.parametrize(
    "extension, source_url, name, expected",
    [
        ("pdf", None, "Doc", "pdf"),
        (".PNG", None, "Banner", "png"),
        (None, "https://cdn.example.com/a/b/report.pdf?sig=1", "Report", "pdf"),
        (None, None, "handbook.md", "md"),
        (None, "https://cdn.example.com/no-ext", "plain", ""),
    ],
)
def test_infer_extension(extension, source_url, name, expected):
    assert _infer_extension(extension, source_url, name) == expected
