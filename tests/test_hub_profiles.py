"""Hub profile tools (SRGDEV-798): paged list, full read, PATCH edit, avatar/cover from Drive."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import srg.exceptions

from srg_mcp import _images, hub_profiles

WS = "ws1"
HUB = "hub1"


class _Api:
    """Records _raw.call and answers by (method, path)."""

    def __init__(self, routes: dict | None = None):
        self.calls: list[dict] = []
        self.routes = routes or {}

    def __call__(self, workspace_id, method, path, *, json=None, params=None, headers=None):
        self.calls.append(
            {"ws": workspace_id, "method": method, "path": path, "json": json, "headers": headers}
        )
        answer = self.routes.get((method, path))
        if callable(answer):
            return answer()
        return answer

    def only(self, method: str) -> dict:
        (call,) = [c for c in self.calls if c["method"] == method]
        return call


PROFILE = {
    "id": HUB,
    "name": "Brand",
    "subName": "Tagline",
    "userName": "brand",
    "description": "An existing description",
    "primaryUrl": "https://brand.example",
    "availabilityLevel": 1,
    "workspaceId": WS,
    "driveId": "drive1",
    "version": 7,
    "created": "2026-01-01T00:00:00Z",
    "modified": "2026-09-01T00:00:00Z",
    "avatar": {
        "details": {"url": "https://signed/avatar.png", "extension": "png"},
        "modified": "2026-09-01T00:00:00Z",
        "width": 1024,
        "height": 1024,
        "sourceAssetId": "asset9",
    },
    "cover": {"details": None, "modified": None},
    "buttons": [],
    "widgets": [
        {"$type": "Text", "id": "w1", "title": "About", "content": "Hi"},
        {
            "$type": "LinkList",
            "id": "w2",
            "title": "Links",
            "links": [
                {"$type": "KnownLink", "id": "l1", "title": "Instagram",
                 "url": "https://www.instagram.com/brand", "iconUrl": {"url": "https://icon"}},
                {"$type": "CustomLink", "id": "l2", "title": "Shop", "url": "https://shop.example"},
            ],
        },
    ],
}


@pytest.fixture
def api(monkeypatch):
    recorder = _Api({("GET", f"/api/v1/hub-profiles/{HUB}"): PROFILE})
    monkeypatch.setattr(hub_profiles._raw, "call", recorder)
    return recorder


# ---- list --------------------------------------------------------------------


def _rows(n: int) -> list[dict]:
    return [
        {"id": f"h{i}", "name": f"Brand {i}", "userName": f"brand{i}", "workspaceId": WS,
         "driveId": f"d{i}", "avatar": {"details": {"url": "https://x" * 50}} if i % 2 else {"details": None}}
        for i in range(n)
    ]


def test_list_is_slim_and_paged(monkeypatch):
    api = _Api({("GET", f"/api/v1/workspaces/{WS}/hub-profiles"): _rows(120)})
    monkeypatch.setattr(hub_profiles._raw, "call", api)

    first = hub_profiles.list_hub_profiles(WS)
    assert first["total"] == 120
    assert len(first["items"]) == 50
    assert first["items"][1] == {"id": "h1", "name": "Brand 1", "user_name": "brand1", "has_avatar": True}
    assert first["cursor"] == "50"

    last = hub_profiles.list_hub_profiles(WS, page_size=50, cursor="100")
    assert [r["id"] for r in last["items"]][0] == "h100"
    assert len(last["items"]) == 20
    assert last["cursor"] is None


def test_list_fits_a_small_budget_for_100_brands(monkeypatch):
    import json

    api = _Api({("GET", f"/api/v1/workspaces/{WS}/hub-profiles"): _rows(100)})
    monkeypatch.setattr(hub_profiles._raw, "call", api)

    page = hub_profiles.list_hub_profiles(WS, page_size=100)
    # No signed avatar URLs in the list: ~80 characters per brand.
    assert len(json.dumps(page)) < 10_000


def test_list_search_matches_name_or_username(monkeypatch):
    rows = _rows(3) + [{"id": "z", "name": "Rebel Studio", "userName": "rstudio", "avatar": None}]
    api = _Api({("GET", f"/api/v1/workspaces/{WS}/hub-profiles"): rows})
    monkeypatch.setattr(hub_profiles._raw, "call", api)

    assert [r["id"] for r in hub_profiles.list_hub_profiles(WS, search="REBEL")["items"]] == ["z"]
    assert [r["id"] for r in hub_profiles.list_hub_profiles(WS, search="rstud")["items"]] == ["z"]


# ---- get ---------------------------------------------------------------------


def test_get_returns_full_profile_with_version_links_and_images(api):
    out = hub_profiles.get_hub_profile(HUB, WS)

    assert out["version"] == 7
    assert out["visibility"] == "Private"
    assert out["description"] == "An existing description"
    assert out["profile_url"] == "https://srgplus.com/brand"
    assert out["avatar"] == {
        "url": "https://signed/avatar.png", "extension": "png", "width": 1024,
        "height": 1024, "source_asset_id": "asset9", "modified": "2026-09-01T00:00:00Z",
    }
    assert out["cover"] is None
    assert out["links_widget_id"] == "w2"
    assert out["links"][0] == {
        "$type": "KnownLink", "id": "l1", "title": "Instagram",
        "url": "https://www.instagram.com/brand", "platform": "instagram", "icon_url": "https://icon",
    }
    assert out["links"][1]["platform"] == "website"
    assert out["other_widgets"] == [{"$type": "Text", "id": "w1", "title": "About"}]


# ---- update (PATCH) ----------------------------------------------------------


def test_bio_only_patches_only_the_description(api):
    api.routes[("PATCH", f"/api/v1/hub-profiles/{HUB}")] = {"id": HUB, "version": 8}

    out = hub_profiles.update_hub_profile(HUB, WS, bio="A new bio for the brand page")

    patch = api.only("PATCH")
    assert patch["json"] == {"description": "A new bio for the brand page"}
    assert patch["headers"] is None
    assert out["version"] == 8
    assert out["updated_fields"] == ["description"]
    assert out["profile"]["id"] == HUB
    assert not [c for c in api.calls if c["method"] == "PUT"]


def test_expected_version_is_sent_as_if_match(api):
    api.routes[("PATCH", f"/api/v1/hub-profiles/{HUB}")] = {"id": HUB, "version": 8}

    hub_profiles.update_hub_profile(HUB, WS, sub_name="", expected_version=7)

    patch = api.only("PATCH")
    assert patch["json"] == {"subName": ""}
    assert patch["headers"] == {"If-Match": '"7"'}


def test_stale_version_409_propagates_and_nothing_else_runs(api):
    def conflict():
        raise srg.exceptions.ConflictError({"detail": "stale"}, SimpleNamespace(status_code=409))

    api.routes[("PATCH", f"/api/v1/hub-profiles/{HUB}")] = conflict

    with pytest.raises(srg.exceptions.ConflictError):
        hub_profiles.update_hub_profile(HUB, WS, bio="A new bio for the brand", expected_version=3)
    assert [c["method"] for c in api.calls] == ["PATCH"]


def test_links_become_known_links_and_keep_ids(api):
    api.routes[("PATCH", f"/api/v1/hub-profiles/{HUB}")] = {"id": HUB, "version": 8}

    hub_profiles.update_hub_profile(
        HUB, WS,
        links=[
            {"id": "l1", "title": "Instagram", "url": "https://instagram.com/brand", "platform": "instagram"},
            {"title": "Site", "url": "brand.example", "$type": "CustomLink"},
        ],
        visibility="public",
    )

    body = api.only("PATCH")["json"]
    assert body["availabilityLevel"] == 0
    assert body["links"] == [
        {"$type": "KnownLink", "title": "Instagram", "url": "https://instagram.com/brand", "id": "l1"},
        {"$type": "CustomLink", "title": "Site", "url": "https://brand.example"},
    ]
    assert "widgets" not in body


@pytest.mark.parametrize(
    ("links", "message"),
    [
        ([{"title": "A", "url": "https://a"}, {"title": "A", "url": "https://b"}], "unique"),
        ([{"title": f"L{i}", "url": f"https://l{i}"} for i in range(21)], "at most 20"),
        ([{"title": "", "url": "https://a"}], "needs a title"),
        ([{"title": "A", "url": "https://a", "$type": "Button"}], "KnownLink"),
    ],
)
def test_bad_links_fail_before_any_write(api, links, message):
    with pytest.raises(ValueError, match=message):
        hub_profiles.update_hub_profile(HUB, WS, links=links)
    assert api.calls == []


def test_nothing_to_update_and_conflicting_bio(api):
    with pytest.raises(ValueError, match="Nothing to update"):
        hub_profiles.update_hub_profile(HUB, WS)
    with pytest.raises(ValueError, match="same field"):
        hub_profiles.update_hub_profile(HUB, WS, bio="one bio text", description="other text!")
    with pytest.raises(ValueError, match="Public"):
        hub_profiles.update_hub_profile(HUB, WS, visibility="Hidden")
    assert api.calls == []


def test_avatar_url_is_downloaded_first_then_uploaded_to_the_signed_url(api, monkeypatch):
    image = _images.CoverImage(data=b"\x89PNG....", extension="png", width=1024, height=1024)
    loads, puts = [], []
    monkeypatch.setattr(hub_profiles._images, "load", lambda src, exts: loads.append((src, exts)) or image)
    monkeypatch.setattr(hub_profiles._images, "put_signed", lambda url, img, headers: puts.append((url, headers)))
    api.routes[("PATCH", f"/api/v1/hub-profiles/{HUB}")] = {
        "id": HUB, "version": 8, "avatarSignedUrl": {"url": "https://upload/avatar", "metadataHeaders": {"x-a": "1"}},
    }

    out = hub_profiles.update_hub_profile(HUB, WS, avatar_image="https://img.example/a.png")

    assert loads == [("https://img.example/a.png", _images.HUB_IMAGE_EXTENSIONS)]
    assert api.only("PATCH")["json"] == {
        "avatar": {"extension": "png", "generateSignedUrl": True, "width": 1024, "height": 1024}
    }
    assert puts == [("https://upload/avatar", {"x-a": "1"})]
    assert out["updated_fields"] == ["avatar"]


def test_empty_image_removes_it(api):
    api.routes[("PATCH", f"/api/v1/hub-profiles/{HUB}")] = {"id": HUB, "version": 8}

    hub_profiles.update_hub_profile(HUB, WS, cover_image="")

    assert api.only("PATCH")["json"] == {"cover": {"extension": None, "generateSignedUrl": True}}


def test_bad_image_url_writes_nothing(api, monkeypatch):
    def boom(src, exts):
        raise ValueError("not a supported cover image")

    monkeypatch.setattr(hub_profiles._images, "load", boom)

    with pytest.raises(ValueError):
        hub_profiles.update_hub_profile(HUB, WS, bio="A new bio for the brand", cover_image="https://x/y.pdf")
    assert api.calls == []


def test_hub_images_reject_heic():
    with pytest.raises(ValueError, match="PNG"):
        _images.describe(b"\x00\x00\x00\x18ftypheic....", "x.heic", extensions=_images.HUB_IMAGE_EXTENSIONS)


# ---- avatar / cover from Drive ----------------------------------------------


def test_set_hub_avatar_posts_from_asset_with_if_match(api):
    api.routes[("POST", f"/api/v1/hub-profiles/{HUB}/avatar/from-asset")] = {
        "id": HUB, "version": 9, "target": "Avatar",
        "image": {"details": {"url": "https://signed/a.png", "extension": "png"},
                  "width": 1024, "height": 1024, "sourceAssetId": "a1"},
    }

    out = hub_profiles.set_hub_avatar(HUB, "a1", WS, expected_version=8)

    post = api.only("POST")
    assert post["json"] == {"assetId": "a1"}
    assert post["headers"] == {"If-Match": '"8"'}
    assert out["version"] == 9
    assert out["avatar"]["width"] == 1024
    assert out["avatar"]["source_asset_id"] == "a1"


def test_set_hub_cover_waits_for_a_just_uploaded_image(api, monkeypatch):
    sleeps: list[int] = []
    monkeypatch.setattr(hub_profiles.time, "sleep", sleeps.append)
    attempts = {"n": 0}

    def still_uploading_then_ok():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise srg.exceptions.BadRequestError(
                {"detail": "The selected image is still uploading. Try again once it finishes."},
                SimpleNamespace(status_code=400),
            )
        return {"id": HUB, "version": 2, "image": {"details": {"url": "u", "extension": "jpg"}}}

    api.routes[("POST", f"/api/v1/hub-profiles/{HUB}/cover/from-asset")] = still_uploading_then_ok

    out = hub_profiles.set_hub_cover(HUB, "c1", WS)

    assert attempts["n"] == 3
    assert sleeps == [1, 1]
    assert out["cover"]["url"] == "u"


def test_set_hub_avatar_from_another_hub_fails_clearly(api):
    def not_in_hub():
        raise srg.exceptions.NotFoundError(
            {"detail": "Asset a1 is not in this hub profile's Drive"}, SimpleNamespace(status_code=404)
        )

    api.routes[("POST", f"/api/v1/hub-profiles/{HUB}/avatar/from-asset")] = not_in_hub

    with pytest.raises(srg.exceptions.NotFoundError):
        hub_profiles.set_hub_avatar(HUB, "a1", WS)
    assert len(api.calls) == 1  # 404 is not retried


# ---- guide -------------------------------------------------------------------


def test_guide_has_the_hub_profile_recipe():
    from srg_mcp.guide import SRGPLUS_GUIDE

    section = SRGPLUS_GUIDE[SRGPLUS_GUIDE.index("## Set up a hub profile"):]
    assert "REPLACES the whole link list" in section
    assert "set_hub_avatar" in section and "set_hub_cover" in section
    assert "2400x800" in section and "lower-left" in section
    assert "<<HUB_IMAGE_RULES>>" not in SRGPLUS_GUIDE
