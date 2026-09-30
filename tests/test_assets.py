"""Unit tests for the `upload_asset` helpers.

These cover the pure, offline parts of the new tool: source validation
(exactly one of source_url / base64_content) and extension inference. The
full upload path hits the SRG+ API + object storage and is exercised by
the SDK's own suite, so it is out of scope here.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from srg_mcp import assets
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


class _FakeAssets:
    """Stands in for client.assets: records the upload call, reads the temp file."""

    def __init__(self) -> None:
        self.kwargs: dict = {}

    def upload(self, **kwargs):
        self.kwargs = kwargs
        with open(kwargs["file"], "rb") as f:
            kwargs["bytes"] = f.read()
        return SimpleNamespace(model_dump=lambda mode="json": {"name": kwargs["name"]})


@pytest.mark.parametrize(
    ("name", "extension", "expected"),
    [
        ("clip.mp4", "mp4", "clip"),  # extension given, name carries it too
        ("clip.mp4", None, "clip"),  # extension inferred from the name
        ("Clip.MP4", None, "Clip"),
        ("v1.2 final.mp4", None, "v1.2 final"),
        ("v1.2 final", "mp4", "v1.2 final"),
        ("clip", "mp4", "clip"),
        ("clip.mov", "mp4", "clip.mov"),  # a different suffix stays
    ],
)
def test_upload_asset_display_name_has_no_extension(monkeypatch, name, extension, expected):
    fake = _FakeAssets()
    monkeypatch.setattr(assets, "get_client", lambda: SimpleNamespace(assets=fake))

    out = assets.upload_asset(
        "hub-1",
        name,
        "ws-1",
        base64_content=base64.b64encode(b"data").decode(),
        extension=extension,
    )

    assert fake.kwargs["name"] == expected
    assert out == {"name": expected}
    assert fake.kwargs["bytes"] == b"data"


def test_upload_asset_temp_file_keeps_the_extension_the_sdk_reads(monkeypatch):
    fake = _FakeAssets()
    monkeypatch.setattr(assets, "get_client", lambda: SimpleNamespace(assets=fake))

    assets.upload_asset(
        "hub-1", "clip.mp4", "ws-1", base64_content=base64.b64encode(b"x").decode()
    )

    assert fake.kwargs["file"].endswith(".mp4")
