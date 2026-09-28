"""Channel/category archive + restore send the channel's hubProfileId (SRGDEV-856).

The backend answers a bare 400 without it, and each endpoint reads it from a
different place: archive_category from the JSON body, the other three from the
query string. The hub id is resolved from the channel, so callers only pass
channel/category ids.
"""

from __future__ import annotations

import inspect

import pytest

from srg_mcp import channels

WS = "ws1"
HUB = "hub1"
CH = "ch1"
CAT = "cat1"
USER = "brand"


class _Api:
    """Records _raw.call and answers by (method, path)."""

    def __init__(self, routes: dict | None = None):
        self.calls: list[dict] = []
        self.routes = routes or {}

    def __call__(self, workspace_id, method, path, *, json=None, params=None, headers=None):
        self.calls.append(
            {"ws": workspace_id, "method": method, "path": path, "json": json,
             "params": params, "headers": headers}
        )
        return self.routes.get((method, path))

    def posts(self) -> list[dict]:
        return [c for c in self.calls if c["method"] == "POST"]


def _routes(channel: dict | None = None, hub: dict | None = None) -> dict:
    return {
        ("GET", f"/api/v2/channels/{CH}"): (
            channel if channel is not None
            else {"id": CH, "name": "Role", "hubProfileUserName": USER, "isArchived": False}
        ),
        ("GET", f"/api/v1/hub-profiles/username/{USER}"): (
            hub if hub is not None else {"id": HUB, "userName": USER}
        ),
    }


@pytest.fixture
def api(monkeypatch):
    recorder = _Api(_routes())
    monkeypatch.setattr(channels._raw, "call", recorder)
    return recorder


def _lookups(api: _Api) -> list[tuple[str, str]]:
    return [(c["method"], c["path"]) for c in api.calls if c["method"] == "GET"]


def test_archive_category_sends_hub_id_in_json_body(api):
    assert channels.archive_category(CH, CAT, WS) is None

    (post,) = api.posts()
    assert post["path"] == f"/api/v1/channels/{CH}/{CAT}/archive"
    assert post["json"] == {"hubProfileId": HUB}
    assert post["params"] is None
    assert post["ws"] == WS
    assert _lookups(api) == [
        ("GET", f"/api/v2/channels/{CH}"),
        ("GET", f"/api/v1/hub-profiles/username/{USER}"),
    ]


def test_restore_category_sends_hub_id_as_query(api):
    assert channels.restore_category(CH, CAT, WS) == "restored"

    (post,) = api.posts()
    assert post["path"] == f"/api/v1/channels/{CH}/{CAT}/restore"
    assert post["params"] == {"hubProfileId": HUB}
    assert post["json"] is None


def test_archive_channel_sends_hub_id_as_query(api):
    assert channels.archive_channel(CH, WS) is None

    (post,) = api.posts()
    assert post["path"] == f"/api/v1/channels/{CH}/archive"
    assert post["params"] == {"hubProfileId": HUB}
    assert post["json"] is None


def test_restore_channel_sends_hub_id_as_query(api):
    assert channels.restore_channel(CH, WS) == "restored"

    (post,) = api.posts()
    assert post["path"] == f"/api/v1/channels/{CH}/restore"
    assert post["params"] == {"hubProfileId": HUB}
    assert post["json"] is None


def test_restore_channel_resolves_hub_of_an_archived_channel(monkeypatch):
    api = _Api(_routes(channel={"id": CH, "hubProfileUserName": USER, "isArchived": True}))
    monkeypatch.setattr(channels._raw, "call", api)

    channels.restore_channel(CH, WS)

    assert api.posts()[0]["params"] == {"hubProfileId": HUB}


def test_hub_user_name_is_url_encoded(monkeypatch):
    odd = "a b/c"
    routes = _routes(channel={"id": CH, "hubProfileUserName": odd})
    routes[("GET", "/api/v1/hub-profiles/username/a%20b%2Fc")] = {"id": HUB}
    api = _Api(routes)
    monkeypatch.setattr(channels._raw, "call", api)

    channels.archive_channel(CH, WS)

    assert ("GET", "/api/v1/hub-profiles/username/a%20b%2Fc") in _lookups(api)
    assert api.posts()[0]["params"] == {"hubProfileId": HUB}


@pytest.mark.parametrize(
    "call",
    [
        lambda: channels.archive_category(CH, CAT, WS),
        lambda: channels.restore_category(CH, CAT, WS),
        lambda: channels.archive_channel(CH, WS),
        lambda: channels.restore_channel(CH, WS),
    ],
)
@pytest.mark.parametrize(
    "channel,hub",
    [
        ({"id": CH, "hubProfileUserName": None}, None),  # channel without a hub user name
        (None, {"userName": USER}),  # hub lookup without an id
    ],
)
def test_unresolved_hub_fails_before_any_write(monkeypatch, call, channel, hub):
    api = _Api(_routes(channel=channel, hub=hub))
    monkeypatch.setattr(channels._raw, "call", api)

    with pytest.raises(ValueError, match=f"hub profile of channel {CH}"):
        call()

    assert api.posts() == []


def test_tool_signatures_unchanged():
    def params(fn):
        return list(inspect.signature(fn).parameters)

    assert params(channels.archive_category) == ["channel_id", "category_id", "workspace_id"]
    assert params(channels.restore_category) == ["channel_id", "category_id", "workspace_id"]
    assert params(channels.archive_channel) == ["channel_id", "workspace_id"]
    assert params(channels.restore_channel) == ["channel_id", "workspace_id"]


# --------------------------------------------------------------------------
# rename_category / rename_channel: PATCH, name only (SRGDEV-827)
# --------------------------------------------------------------------------


def test_rename_category_patches_only_the_name(monkeypatch) -> None:
    from srg_mcp import channels

    calls = []
    monkeypatch.setattr(
        channels._raw,
        "call",
        lambda ws, method, path, **kw: calls.append((ws, method, path, kw)),
    )

    assert channels.rename_category("ch1", "cat1", "🎬 Reels", "ws-1") == "renamed"
    assert calls == [
        ("ws-1", "PATCH", "/api/v1/channels/ch1/categories/cat1", {"json": {"name": "🎬 Reels"}})
    ]


def test_rename_channel_patches_only_the_name(monkeypatch) -> None:
    from srg_mcp import channels

    calls = []
    monkeypatch.setattr(
        channels._raw,
        "call",
        lambda ws, method, path, **kw: calls.append((ws, method, path, kw)),
    )

    assert channels.rename_channel("ch1", "Brand", "ws-1") == "renamed"
    assert calls == [("ws-1", "PATCH", "/api/v1/channels/ch1", {"json": {"name": "Brand"}})]
