"""update_content / create_content write paths (SRGDEV-235).

The real bug: update_content went through the SDK's GET-merge-PUT, and PUT
treats an omitted cover as "remove the cover". A caption-only rewrite of 15
reels wiped 14 covers. update_content now PATCHes only the supplied fields.
These tests pin that contract without touching the network.
"""

from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

import srg_mcp._client as client_mod
from srg_mcp import _images, contents

CONTENT_ID = "65f000000000000000000001"
HUB_ID = "65f0000000000000000000aa"
WS_ID = "65f0000000000000000000ff"

PNG_1080x1920 = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\x0dIHDR"
    + struct.pack(">II", 1080, 1920)
    + b"\x08\x02\x00\x00\x00"
    + b"\x00" * 16
)


class _Recorder:
    """Stands in for srg_mcp._raw.call and records every request."""

    def __init__(self, response: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.response = response if response is not None else {
            "id": CONTENT_ID,
            "coverSignedUrl": None,
            "context": [],
            "metadataHeaders": None,
        }

    def __call__(self, workspace_id, method, path, *, json=None, params=None, headers=None):
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "method": method,
                "path": path,
                "json": json,
                "params": params,
                "headers": headers,
            }
        )
        return self.response


@pytest.fixture
def raw(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder()
    monkeypatch.setattr(contents._raw, "call", recorder)
    return recorder


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A fake SDK client: get_v2 answers with the owning hub profile."""
    reads: list[str] = []

    def get_v2(content_id, workspace_id):
        reads.append(content_id)
        return SimpleNamespace(hub_profile_id=HUB_ID)

    fake = SimpleNamespace(contents=SimpleNamespace(get_v2=get_v2), reads=reads)
    monkeypatch.setattr(contents, "get_client", lambda: fake)
    return fake


def test_context_only_update_patches_without_cover(raw: _Recorder, sdk) -> None:
    """Regression: a body rewrite must never send (and so never wipe) the cover."""
    new_body = [{"$type": "Text", "content": "Caption ~40 sec"}]

    result = contents.update_content(CONTENT_ID, WS_ID, context=new_body)

    assert len(raw.calls) == 1
    call = raw.calls[0]
    assert call["method"] == "PATCH"
    assert call["path"] == f"/api/v1/contents/{CONTENT_ID}"
    assert call["params"] == {"hubProfileId": HUB_ID}
    assert call["json"] == {"context": new_body}
    for untouched in ("cover", "mainAssetId", "channels", "categories", "name"):
        assert untouched not in call["json"]
    assert result["updated_fields"] == ["context"]


def test_hub_profile_is_resolved_only_when_missing(raw: _Recorder, sdk) -> None:
    contents.update_content(CONTENT_ID, WS_ID, name="Reel 01", hub_profile_id=HUB_ID)
    assert sdk.reads == []

    contents.update_content(CONTENT_ID, WS_ID, name="Reel 01")
    assert sdk.reads == [CONTENT_ID]
    assert raw.calls[-1]["params"] == {"hubProfileId": HUB_ID}


def test_only_supplied_fields_are_sent(raw: _Recorder, sdk) -> None:
    contents.update_content(
        CONTENT_ID,
        WS_ID,
        privacy="Public",
        details="d",
        url="https://example.org",
        main_asset_id="asset-1",
        channels=["ch-1"],
        categories=[{"$type": "Content"}],
        hub_profile_id=HUB_ID,
    )

    assert raw.calls[0]["json"] == {
        "privacy": "Public",
        "details": "d",
        "url": "https://example.org",
        "mainAssetId": "asset-1",
        "channels": [{"channelId": "ch-1", "categoryIds": []}],
        "categories": [{"$type": "Content"}],
    }


def test_empty_update_is_rejected_before_any_call(raw: _Recorder, sdk) -> None:
    with pytest.raises(ValueError, match="Nothing to update"):
        contents.update_content(CONTENT_ID, WS_ID)
    assert raw.calls == []
    assert sdk.reads == []


def test_cover_url_without_extension_is_sniffed_and_uploaded(
    raw: _Recorder, sdk, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw.response = {
        "id": CONTENT_ID,
        "coverSignedUrl": {"url": "https://r2.example/put-cover"},
        "context": [],
        "metadataHeaders": {"x-amz-meta-type": "ContentCover"},
    }
    monkeypatch.setattr(
        _images, "_download", lambda url: (PNG_1080x1920, "binary/octet-stream")
    )
    uploads: list[tuple] = []
    monkeypatch.setattr(
        _images,
        "put_signed",
        lambda url, image, headers: uploads.append((url, image.mime, headers)),
    )

    contents.update_content(
        CONTENT_ID,
        WS_ID,
        cover_image="https://r2.example/hub-profiles/h/assets/a1?X-Amz-Signature=x",
        hub_profile_id=HUB_ID,
    )

    assert raw.calls[0]["json"] == {
        "cover": {
            "image": {
                "width": 1080,
                "height": 1920,
                "size": len(PNG_1080x1920),
                "extension": "png",
            },
            "generateSignedUrl": True,
        }
    }
    assert uploads == [
        ("https://r2.example/put-cover", "image/png", {"x-amz-meta-type": "ContentCover"})
    ]


def test_bad_cover_fails_before_writing(raw: _Recorder, sdk, monkeypatch) -> None:
    monkeypatch.setattr(
        _images, "_download", lambda url: (b"<html>not an image</html>", "text/html")
    )
    with pytest.raises(ValueError, match="not a supported cover image"):
        contents.update_content(
            CONTENT_ID, WS_ID, cover_image="https://example.com/page", hub_profile_id=HUB_ID
        )
    assert raw.calls == []


def test_hosted_server_rejects_local_cover_path(raw: _Recorder, sdk) -> None:
    token = client_mod.set_current_api_key("srgplus_fake")
    try:
        with pytest.raises(ValueError, match="cannot read files on your computer"):
            contents.update_content(
                CONTENT_ID, WS_ID, cover_image="/Users/me/Reel 15.jpg", hub_profile_id=HUB_ID
            )
    finally:
        client_mod.reset_current_api_key(token)
    assert raw.calls == []


def test_create_content_uploads_cover_via_signed_url(monkeypatch) -> None:
    created: dict = {}
    uploads: list[tuple] = []

    def create(**kwargs):
        created.update(kwargs)
        return SimpleNamespace(
            id=CONTENT_ID,
            cover_signed_url=SimpleNamespace(url="https://r2.example/put-new"),
            metadata_headers={"x-amz-meta-object-id": CONTENT_ID},
        )

    def get(content_id, hub_profile_id, workspace_id):
        return SimpleNamespace(model_dump=lambda mode: {"id": content_id})

    fake = SimpleNamespace(contents=SimpleNamespace(create=create, get=get))
    monkeypatch.setattr(contents, "get_client", lambda: fake)
    monkeypatch.setattr(_images, "_download", lambda url: (PNG_1080x1920, None))
    monkeypatch.setattr(
        _images,
        "put_signed",
        lambda url, image, headers: uploads.append((url, image.extension, headers)),
    )

    out = contents.create_content(
        "Reel 16", HUB_ID, WS_ID, cover_image="https://cdn.example/no-extension"
    )

    assert created["cover"] == {
        "width": 1080,
        "height": 1920,
        "size": len(PNG_1080x1920),
        "extension": "png",
    }
    assert "cover_image" not in created
    assert uploads == [
        ("https://r2.example/put-new", "png", {"x-amz-meta-object-id": CONTENT_ID})
    ]
    assert out == {"id": CONTENT_ID}


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG_1080x1920, "png"),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 28, "jpg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16, "webp"),
        (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20, "heic"),
        (b"just text", None),
    ],
)
def test_sniff_extension(data: bytes, expected: str | None) -> None:
    assert _images.sniff_extension(data) == expected


def test_describe_rejects_oversized_cover() -> None:
    big = PNG_1080x1920 + b"\x00" * (_images.MAX_COVER_BYTES + 1)
    with pytest.raises(ValueError, match="at most"):
        _images.describe(big, "https://cdn.example/huge.png")
