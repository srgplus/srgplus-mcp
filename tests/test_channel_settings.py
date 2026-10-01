"""Channel look and order, category settings (SRGDEV-948 icons, SRGDEV-805b links,
category order, pin, Grid / List / Scroll views).

The category endpoints replace a whole category, so every tool reads it first and must
send each field back unchanged except the one asked. The option shapes are checked
against a port of the backend's ChannelCategoryOptionsValidator: a value it rejects
would be a 400 (or a 500, its enum parsing is case-sensitive).
"""

from __future__ import annotations

import copy
import itertools
from types import SimpleNamespace

import pytest
import srg.exceptions

from srg_mcp import _category_options as opts
from srg_mcp import channel_settings as cs
from srg_mcp import channels

WS = "ws1"
HUB = "6a0000000000000000000001"
USER = "brand"
CH = "6a00000000000000000000c1"
CH2 = "6a00000000000000000000c2"
CH3 = "6a00000000000000000000c3"
CH_OLD = "6a00000000000000000000c9"
CAT_A = "6a00000000000000000000a1"
CAT_B = "6a00000000000000000000a2"
CAT_C = "6a00000000000000000000a3"
CAT_OLD = "6a00000000000000000000a9"
IMG = "6a00000000000000000000f1"

PRESENTATION_TYPES = {"Classic", "List", "Waterfall"}
SUB_TYPES = {"Extended", "Compact"}
MOBILE_RATIOS = {"Original", "Square", "SixteenByNine", "ThreeByTwo", "FourByFive"}
POSITIONS = {"Horizontal", "Vertical"}


def _error(cls, status: int, detail: str):
    return cls({"detail": detail}, SimpleNamespace(status_code=status))


def _backend_accepts(options: dict) -> None:
    """ChannelCategoryOptionsValidator + the JSON reader: what a write must satisfy."""
    assert set(options) == {"view", "progression", "cover", "expandable"}, options
    presentation = options["view"]["presentation"]
    assert next(iter(presentation)) == "$type", "presentation: $type must be the first key"
    if presentation["$type"] == "Standard":
        assert presentation["global"]["type"] in PRESENTATION_TYPES
    else:
        assert presentation["$type"] == "Custom"
        main, expanded = presentation["main"], presentation["expanded"]
        assert main["type"] in PRESENTATION_TYPES
        assert main["subType"] in SUB_TYPES | {None}
        if main["type"] == "Classic":
            assert main["subType"] in (None, "Compact")
        assert expanded["type"] in PRESENTATION_TYPES - {"Classic"}
    aspect = options["cover"]["aspect"]
    assert next(iter(aspect)) == "$type", "aspect: $type must be the first key"
    if aspect["$type"] == "Standard":
        ratio = aspect["ratio"]
        assert ratio["ratio"] in MOBILE_RATIOS
        assert ratio["position"] in POSITIONS | {None}
        if ratio["ratio"] == "Square":
            assert ratio["position"] is None
    assert isinstance(options["progression"]["progression"], bool)
    assert isinstance(options["progression"]["sequentialCompletion"], bool)
    assert isinstance(options["expandable"], bool)


def _standard(kind: str = "Classic") -> dict:
    # Read shape: "$type" first, as the backend writes it.
    return {
        "expandable": True,
        "view": {"presentation": {"$type": "Standard", "global": {"type": kind}}},
        "cover": {"aspect": {"$type": "Standard", "ratio": {"ratio": "Original", "position": None}}},
        "progression": {"progression": False, "sequentialCompletion": False},
    }


def _custom(kind: str, sub: str | None, opens: str) -> dict:
    out = _standard()
    out["view"] = {
        "presentation": {"$type": "Custom", "main": {"type": kind, "subType": sub}, "expanded": {"type": opens}}
    }
    return out


def _presentation(options: dict) -> dict:
    return options["view"]["presentation"]


# --------------------------------------------------------------------------
# Options in plain words
# --------------------------------------------------------------------------


def test_grid_on_a_standard_scroll_category_stays_standard():
    out = opts.with_changes(_standard("Classic"), view="grid")

    assert _presentation(out) == {"$type": "Standard", "global": {"type": "Waterfall"}}
    _backend_accepts(out)


def test_small_cards_need_custom_and_keep_the_grid_when_opened():
    # The backend drops a subType on Standard, so the size lives on a Custom main view.
    out = opts.with_changes(_standard("Waterfall"), card_size="small")

    assert _presentation(out) == {
        "$type": "Custom",
        "main": {"type": "Waterfall", "subType": "Compact"},
        "expanded": {"type": "Waterfall"},
    }
    _backend_accepts(out)


def test_large_cards_that_open_as_a_grid_go_back_to_standard():
    out = opts.with_changes(_custom("List", "Compact", "Waterfall"), card_size="large")

    assert _presentation(out) == {"$type": "Standard", "global": {"type": "List"}}


def test_open_view_list_keeps_the_card_size():
    out = opts.with_changes(_standard("List"), open_view="list")

    assert _presentation(out) == {
        "$type": "Custom",
        "main": {"type": "List", "subType": "Extended"},
        "expanded": {"type": "List"},
    }


def test_scroll_drops_the_card_size_and_keeps_the_open_view():
    out = opts.with_changes(_custom("Waterfall", "Compact", "List"), view="scroll")

    assert _presentation(out) == {
        "$type": "Custom",
        "main": {"type": "Classic", "subType": None},
        "expanded": {"type": "List"},
    }
    _backend_accepts(out)


def test_an_unset_card_size_is_left_unset():
    out = opts.with_changes(_custom("List", None, "Waterfall"), view="grid")

    assert _presentation(out)["main"] == {"type": "Waterfall", "subType": None}


def test_scroll_with_a_card_size_is_refused():
    with pytest.raises(ValueError, match="grid and list"):
        opts.with_changes(_standard("Classic"), card_size="small")
    with pytest.raises(ValueError, match="grid and list"):
        opts.with_changes(_standard("Waterfall"), view="scroll", card_size="small")


@pytest.mark.parametrize(
    "kwargs",
    [{"view": "masonry"}, {"open_view": "scroll"}, {"card_size": "medium"}, {"cover_ratio": "21:9"}],
)
def test_unknown_words_fail_before_any_write(kwargs):
    with pytest.raises(ValueError):
        opts.with_changes(_standard(), **kwargs)


@pytest.mark.parametrize(
    "said,ratio,position,read_back",
    [
        ("16:9", "SixteenByNine", "Horizontal", "16:9"),
        ("9:16", "SixteenByNine", "Vertical", "9:16"),
        ("16x9", "SixteenByNine", "Horizontal", "16:9"),
        ("3:2", "ThreeByTwo", "Horizontal", "3:2"),
        ("2/3", "ThreeByTwo", "Vertical", "2:3"),
        ("5:4", "FourByFive", "Horizontal", "5:4"),
        ("4:5", "FourByFive", "Vertical", "4:5"),
        ("Square", "Square", None, "square"),
        ("1:1", "Square", None, "square"),
        ("original", "Original", None, "original"),
    ],
)
def test_cover_ratio_is_the_cards_shape(said, ratio, position, read_back):
    out = opts.with_changes(_standard(), cover_ratio=said)

    assert out["cover"]["aspect"] == {"$type": "Standard", "ratio": {"ratio": ratio, "position": position}}
    _backend_accepts(out)
    assert opts.settings_of({"options": out})["cover_ratio"] == read_back


def test_a_stored_four_by_five_without_position_reads_as_drawn():
    # The apps draw FourByFive without a position as 5:4 (landscape).
    stored = _standard()
    stored["cover"]["aspect"]["ratio"] = {"ratio": "FourByFive", "position": None}

    assert opts.settings_of({"options": stored})["cover_ratio"] == "5:4"


def test_untouched_parts_are_sent_back_with_type_first():
    stored = _standard("List")
    stored["view"]["presentation"] = {"global": {"type": "List"}, "$type": "Standard"}
    stored["cover"]["aspect"] = {"ratio": {"ratio": "Square", "position": None}, "$type": "Standard"}

    out = opts.with_changes(stored, expandable=False)

    assert list(_presentation(out)) == ["$type", "global"]
    assert list(out["cover"]["aspect"]) == ["$type", "ratio"]
    assert out["expandable"] is False
    assert stored["expandable"] is True, "the stored options must not be changed in place"


def test_custom_device_covers_stay_when_the_cover_is_not_asked():
    stored = _standard()
    stored["cover"] = {
        "aspect": {
            "$type": "Custom",
            "mobileRatio": {"ratio": "FourByFive", "position": "Vertical"},
            "desktopRatio": {"ratio": "SixteenByNine", "position": None},
        }
    }

    out = opts.with_changes(stored, view="list")

    assert out["cover"] == stored["cover"]
    assert opts.settings_of({"options": out})["cover_ratio"] == {"mobile": "4:5", "desktop": "16:9"}


def test_sequential_turns_progression_on_and_no_progression_turns_it_off():
    on = opts.with_changes(_standard(), sequential=True)
    assert on["progression"] == {"progression": True, "sequentialCompletion": True}

    off = opts.with_changes(on, progression=False)
    assert off["progression"] == {"progression": False, "sequentialCompletion": False}

    with pytest.raises(ValueError, match="sequential needs progression"):
        opts.with_changes(_standard(), progression=False, sequential=True)


def test_missing_options_get_the_backend_defaults():
    out = opts.with_changes(None)

    assert out == opts.default_options()
    _backend_accepts(out)


STORED = [
    _standard("Classic"),
    _standard("List"),
    _standard("Waterfall"),
    _custom("Classic", None, "List"),
    _custom("Classic", "Compact", "Waterfall"),
    _custom("List", None, "Waterfall"),
    _custom("Waterfall", "Compact", "List"),
    _custom("List", "Extended", "List"),
]


@pytest.mark.parametrize("stored", STORED)
def test_every_change_gives_options_the_backend_accepts(stored):
    views = [None, "grid", "list", "scroll"]
    sizes = [None, "large", "small"]
    opens = [None, "grid", "list"]
    for view, size, opened in itertools.product(views, sizes, opens):
        try:
            out = opts.with_changes(copy.deepcopy(stored), view=view, card_size=size, open_view=opened)
        except ValueError as exc:
            assert "grid and list" in str(exc)
            continue
        _backend_accepts(out)
        settings = opts.settings_of({"options": out})
        if view:
            assert settings["view"] == view
        if size:
            assert settings["card_size"] == size
        if opened:
            assert settings["open_view"] == opened


# --------------------------------------------------------------------------
# A fake Content-Hub: one hub, its channels and one channel's categories
# --------------------------------------------------------------------------


def _category(cid: str, name: str, *, pinned=False, archived=False, options=None, notify=True, email=False):
    return {
        "id": cid,
        "name": name,
        "isArchived": archived,
        "isPinned": pinned,
        "notificationsEnabled": notify,
        "emailEnabled": email,
        "sections": [{"$type": "Default", "id": "6a00000000000000000000e1", "name": None}],
        "options": options or _standard("Classic"),
    }


class FakeContentHub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.icon: dict | None = None
        self.slug = "role"
        self.bad_requests_left = 0
        self.categories = [
            _category(CAT_OLD, "Old", archived=True),
            _category(CAT_A, "Reels", pinned=True, options=_standard("Waterfall"), email=True),
            _category(CAT_B, "Guides", notify=False),
            _category(CAT_C, "News", options=_custom("List", "Compact", "List")),
        ]
        self.channels = [
            {"id": CH, "name": "Role", "isArchived": False},
            {"id": CH2, "name": "Video", "isArchived": False},
            {"id": CH3, "name": "Shop", "isArchived": False},
        ]
        self.archived_channels = [{"id": CH_OLD, "name": "Old shop", "isArchived": True}]
        self.taken_slugs: set[str] = set()
        self.channel_put_error: Exception | None = None
        self.refused_moves: dict[str, Exception] = {}

    def channel(self) -> dict:
        return {
            "id": CH,
            "name": "Role",
            "privacy": "Private",
            "isArchived": False,
            "hubProfileName": "Brand",
            "hubProfileUserName": USER,
            "slug": self.slug,
            "icon": copy.deepcopy(self.icon),
            "categories": copy.deepcopy(self.categories),
        }

    def writes(self) -> list[tuple[str, str, object]]:
        return [c for c in self.calls if c[0] != "GET"]

    def __call__(self, workspace_id, method, path, *, json=None, params=None, headers=None):
        assert workspace_id == WS
        self.calls.append((method, path, copy.deepcopy(json)))
        if (method, path) == ("GET", f"/api/v2/channels/{CH}"):
            return self.channel()
        if (method, path) == ("GET", f"/api/v1/hub-profiles/username/{USER}"):
            return {"id": HUB, "userName": USER}
        if (method, path) == ("GET", f"/api/v1/channels/{HUB}"):
            rows = self.channels + ([] if params == {"includeArchived": "false"} else self.archived_channels)
            return [dict(c, slug=c["name"].lower(), hubProfileUserName=USER, privacy="Public", categories=[])
                    for c in rows]
        if (method, path) == ("PUT", f"/api/v1/channels/{CH}/icon"):
            self.icon = dict(json)
            return None
        if (method, path) == ("DELETE", f"/api/v1/channels/{CH}/icon"):
            self.icon = None
            return None
        if (method, path) == ("PATCH", f"/api/v1/channels/{CH}"):
            if json["slug"] in self.taken_slugs:
                raise _error(srg.exceptions.ConflictError, 409,
                             f"Another channel of this profile already uses the name or link {json['slug']}")
            self.slug = json["slug"]
            return None
        if (method, path) == ("PUT", "/api/v1/channels"):
            if self.channel_put_error:
                raise self.channel_put_error
            if self.bad_requests_left:
                self.bad_requests_left -= 1
                raise _error(srg.exceptions.BadRequestError, 400,
                             "Categories on channel update can not be added or deleted.")
            assert json["hubProfileId"] == HUB and json["channelId"] == CH
            stored = sorted(c["id"] for c in self.categories)
            assert sorted(c["categoryId"] for c in json["categories"]) == stored, "every category, once"
            by_id = {c["id"]: c for c in self.categories}
            for item in json["categories"]:
                assert item["isArchived"] == by_id[item["categoryId"]]["isArchived"]
            # The backend stores archived categories first, then the order sent.
            ordered = sorted(json["categories"], key=lambda c: not c["isArchived"])
            self.categories = [by_id[c["categoryId"]] for c in ordered]
            return None
        if method == "PUT" and path.startswith(f"/api/v1/channels/{CH}/categories/"):
            category_id = path.rsplit("/", 1)[1]
            assert set(json) <= {"name", "isPinned", "notificationsEnabled", "emailEnabled", "options"}
            assert {"name", "isPinned", "options"} <= set(json)
            _backend_accepts(json["options"])
            for category in self.categories:
                if json["isPinned"] and category["id"] != category_id:
                    category["isPinned"] = False
                if category["id"] == category_id:
                    category.update(
                        name=json["name"],
                        isPinned=json["isPinned"],
                        # The backend's defaults for an omitted flag: notifications on,
                        # the stored email flag kept.
                        notificationsEnabled=json.get("notificationsEnabled", True),
                        emailEnabled=json.get("emailEnabled", category.get("emailEnabled", False)),
                        options=json["options"],
                    )
            return category_id
        if method == "POST" and path.endswith("/move"):
            moved = path.split("/")[-2]
            if moved in self.refused_moves:
                raise self.refused_moves[moved]
            previous = json["previousChannelId"]
            order = [c for c in self.channels if c["id"] != moved]
            index = 0 if previous is None else [c["id"] for c in order].index(previous) + 1
            order.insert(index, next(c for c in self.channels if c["id"] == moved))
            self.channels = order
            return None
        if (method, path) == ("POST", f"/api/v1/channels/{CH}/categories"):
            _backend_accepts(json["options"])
            return CAT_C
        raise AssertionError(f"unexpected call {method} {path}")


@pytest.fixture
def hub(monkeypatch) -> FakeContentHub:
    fake = FakeContentHub()
    monkeypatch.setattr(channels._raw, "call", fake)
    monkeypatch.setattr(cs._raw, "call", fake)
    return fake


def _stored(hub: FakeContentHub, cid: str) -> dict:
    return next(c for c in hub.categories if c["id"] == cid)


# --------------------------------------------------------------------------
# Channel icon
# --------------------------------------------------------------------------


def test_symbol_icon_with_an_app_colour_name(hub):
    out = cs.set_channel_icon(CH, WS, symbol="star.fill", color="Red")

    assert hub.writes() == [("PUT", f"/api/v1/channels/{CH}/icon",
                             {"kind": "symbol", "symbol": "star.fill", "color": "#FF3B30"})]
    assert out["icon"] == {"kind": "symbol", "color": "#FF3B30", "symbol": "star.fill"}
    assert [c for c in hub.calls if c[0] == "GET"] == [], "a given colour needs no read"


def test_emoji_icon_keeps_the_current_colour(hub):
    hub.icon = {"kind": "symbol", "symbol": "bolt.fill", "color": "#34C759"}

    cs.set_channel_icon(CH, WS, emoji="🚀")

    assert hub.icon == {"kind": "emoji", "emoji": "🚀", "color": "#34C759"}


def test_first_icon_without_a_colour_is_the_apps_blue(hub):
    cs.set_channel_icon(CH, WS, symbol="#")

    assert hub.icon == {"kind": "symbol", "symbol": "number", "color": "#007AFF"}


def test_photo_icon_needs_no_colour(hub):
    cs.set_channel_icon(CH, WS, photo_asset_id=IMG.upper())

    assert hub.icon == {"kind": "photo", "assetId": IMG}


def test_hex_colour_is_normalized(hub):
    cs.set_channel_icon(CH, WS, symbol="leaf.fill", color="34c759")

    assert hub.icon["color"] == "#34C759"


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({}, "exactly one"),
        ({"symbol": "star.fill", "emoji": "⭐"}, "exactly one"),
        ({"symbol": "Star Fill"}, "apps offer"),
        ({"symbol": "rocket.fill"}, "apps offer"),
        ({"photo_asset_id": "not-an-id"}, "24-character"),
        ({"symbol": "star.fill", "color": "turquoise-ish"}, "#RRGGBB"),
    ],
)
def test_bad_icons_fail_before_any_call(hub, kwargs, match):
    with pytest.raises(ValueError, match=match):
        cs.set_channel_icon(CH, WS, **kwargs)
    assert hub.calls == []


def test_remove_icon(hub):
    hub.icon = {"kind": "emoji", "emoji": "🚀", "color": "#FF9500"}

    assert cs.remove_channel_icon(CH, WS) == "removed"
    assert hub.icon is None


def test_the_docstring_lists_every_symbol_the_apps_offer():
    doc = " ".join((cs.set_channel_icon.__doc__ or "").split())
    for symbol in cs.APP_SYMBOLS:
        assert symbol in doc
    for name in cs.COLOR_NAMES:
        assert name in doc


# --------------------------------------------------------------------------
# Channel link
# --------------------------------------------------------------------------


def test_slug_spaces_become_dashes_and_the_link_comes_back(hub):
    out = cs.set_channel_slug(CH, "  Video Lessons ", WS)

    assert hub.writes() == [("PATCH", f"/api/v1/channels/{CH}", {"slug": "video-lessons"})]
    assert out == {
        "channel_id": CH,
        "name": "Role",
        "slug": "video-lessons",
        "link": f"https://srgplus.com/{USER}/channels/video-lessons",
    }


@pytest.mark.parametrize("slug", ["видео", "-", "a" * 51, "video/lessons"])
def test_bad_slugs_fail_before_any_call(hub, slug):
    with pytest.raises(ValueError, match="lower-case latin"):
        cs.set_channel_slug(CH, slug, WS)
    assert hub.calls == []


# --------------------------------------------------------------------------
# Category order
# --------------------------------------------------------------------------


def test_reorder_categories_sends_every_category_with_its_archive_flag(hub):
    out = cs.reorder_categories(CH, [CAT_C, CAT_A], WS)

    (put,) = [w for w in hub.writes() if w[1] == "/api/v1/channels"]
    assert put[2] == {
        "channelId": CH,
        "hubProfileId": HUB,
        "name": "Role",
        "categories": [
            {"categoryId": CAT_C, "isArchived": False},
            {"categoryId": CAT_A, "isArchived": False},
            {"categoryId": CAT_B, "isArchived": False},
            {"categoryId": CAT_OLD, "isArchived": True},
        ],
    }
    assert "privacy" not in put[2], "privacy is kept by leaving it out"
    assert [c["name"] for c in out["order"]] == ["News", "Reels", "Guides"]
    assert out["changed"] is True
    # Nothing else of a category changes.
    assert _stored(hub, CAT_A)["isPinned"] is True


def test_reorder_categories_in_place_writes_nothing(hub):
    out = cs.reorder_categories(CH, [CAT_A.upper(), CAT_B], WS)

    assert out["changed"] is False
    assert hub.writes() == []


def test_reorder_categories_refuses_unknown_repeated_and_archived_ids(hub):
    with pytest.raises(ValueError, match="not in channel 'Role'"):
        cs.reorder_categories(CH, [CAT_A, "6a00000000000000000000ff"], WS)
    with pytest.raises(ValueError, match="listed twice"):
        cs.reorder_categories(CH, [CAT_A, CAT_A], WS)
    with pytest.raises(ValueError, match="archived, so not in the order"):
        cs.reorder_categories(CH, [CAT_OLD], WS)
    with pytest.raises(ValueError, match="at least one"):
        cs.reorder_categories(CH, [], WS)
    assert hub.writes() == []


def test_reorder_categories_reads_again_after_a_concurrent_add(hub):
    hub.bad_requests_left = 1

    out = cs.reorder_categories(CH, [CAT_B], WS)

    assert out["changed"] is True
    assert [w[1] for w in hub.writes()] == ["/api/v1/channels", "/api/v1/channels"]
    assert [c["id"] for c in hub.categories if not c["isArchived"]] == [CAT_B, CAT_A, CAT_C]


# --------------------------------------------------------------------------
# Channel order
# --------------------------------------------------------------------------


def test_reorder_channels_moves_only_what_is_out_of_place(hub):
    out = cs.reorder_channels(HUB, [CH3, CH], WS)

    assert hub.writes() == [
        ("POST", f"/api/v1/channels/{CH3}/move", {"previousChannelId": None}),
    ]
    assert [c["name"] for c in out["order"]] == ["Shop", "Role", "Video"]
    assert [c["id"] for c in hub.channels] == [CH3, CH, CH2]
    assert out["moved"] == 1


def test_reorder_channels_full_reverse(hub):
    out = cs.reorder_channels(HUB, [CH3, CH2, CH], WS)

    assert [c["id"] for c in hub.channels] == [CH3, CH2, CH]
    assert [c["id"] for c in out["order"]] == [CH3, CH2, CH]
    assert hub.writes()[1] == ("POST", f"/api/v1/channels/{CH2}/move", {"previousChannelId": CH3})


def test_reorder_channels_refuses_a_channel_of_another_hub(hub):
    with pytest.raises(ValueError, match="not in this hub"):
        cs.reorder_channels(HUB, ["6a00000000000000000000cf"], WS)
    assert hub.writes() == []


# --------------------------------------------------------------------------
# Category settings
# --------------------------------------------------------------------------


def test_pin_sends_every_field_back_and_names_the_unpinned_category(hub):
    before = copy.deepcopy(_stored(hub, CAT_B))

    out = cs.update_category_settings(CH, CAT_B, WS, pinned=True)

    (put,) = hub.writes()
    assert put[1] == f"/api/v1/channels/{CH}/categories/{CAT_B}"
    assert put[2]["name"] == "Guides"
    assert put[2]["notificationsEnabled"] is False, "kept, not reset to the default"
    assert put[2]["emailEnabled"] is False
    assert put[2]["options"] == before["options"]
    assert out["pinned"] is True and out["unpinned"] == ["Reels"]
    assert _stored(hub, CAT_A)["isPinned"] is False


def test_grid_view_keeps_pin_notifications_and_email(hub):
    out = cs.update_category_settings(CH, CAT_A, WS, view="list", cover_ratio="9:16")

    stored = _stored(hub, CAT_A)
    assert stored["isPinned"] is True and stored["emailEnabled"] is True
    assert _presentation(stored["options"]) == {"$type": "Standard", "global": {"type": "List"}}
    assert out["view"] == "list" and out["cover_ratio"] == "9:16" and out["pinned"] is True
    assert "unpinned" not in out


def test_small_grid_cards_by_voice(hub):
    out = cs.update_category_settings(CH, CAT_B, WS, view="grid", card_size="small")

    assert out["view"] == "grid" and out["card_size"] == "small" and out["open_view"] == "grid"
    assert _presentation(_stored(hub, CAT_B)["options"])["$type"] == "Custom"


def test_settings_need_something_to_change(hub):
    with pytest.raises(ValueError, match="at least one setting"):
        cs.update_category_settings(CH, CAT_A, WS)
    assert hub.calls == []


def test_unknown_category_lists_the_channels_categories(hub):
    with pytest.raises(ValueError, match="'Reels'"):
        cs.update_category_settings(CH, "6a00000000000000000000ff", WS, pinned=True)
    assert hub.writes() == []


def test_notifications_and_email(hub):
    out = cs.update_category_settings(CH, CAT_C, WS, notifications=False, email=True)

    stored = _stored(hub, CAT_C)
    assert stored["notificationsEnabled"] is False and stored["emailEnabled"] is True
    assert _presentation(stored["options"]) == _presentation(_custom("List", "Compact", "List"))
    assert out["notifications"] is False and out["email"] is True


# --------------------------------------------------------------------------
# The older tools now keep what they are not given
# --------------------------------------------------------------------------


def test_update_category_keeps_pin_and_notifications_it_is_not_given(hub):
    out = channels.update_category(CH, CAT_A, WS, name="Reels 2", view_type="Grid")

    stored = _stored(hub, CAT_A)
    assert stored["name"] == "Reels 2"
    assert stored["isPinned"] is True, "it used to unpin (isPinned defaulted to False)"
    assert stored["emailEnabled"] is True
    assert out["view"] == "grid"


def test_update_channel_sends_category_ids_with_archive_flags(hub):
    channels.update_channel(CH, HUB, WS, categories=[{"id": CAT_B, "order": 1}, {"id": CAT_C, "order": 0}])

    (put,) = hub.writes()
    assert put[2]["categories"] == [
        {"categoryId": CAT_C, "isArchived": False},
        {"categoryId": CAT_B, "isArchived": False},
        {"categoryId": CAT_A, "isArchived": False},
        {"categoryId": CAT_OLD, "isArchived": True},
    ]


def test_update_channel_without_categories_keeps_their_order(hub):
    channels.update_channel(CH, HUB, WS, privacy="public")

    (put,) = hub.writes()
    assert put[2]["privacy"] == "Public"
    assert [c["categoryId"] for c in put[2]["categories"]] == [CAT_A, CAT_B, CAT_C, CAT_OLD]


def test_create_category_honours_the_view(hub):
    new_id = channels.create_category(CH, "Shorts", WS, view_type="Grid", card_size="small", cover_ratio="9:16")

    (post,) = hub.writes()
    assert new_id == CAT_C
    assert post[2]["options"]["view"]["presentation"] == {
        "$type": "Custom",
        "main": {"type": "Waterfall", "subType": "Compact"},
        "expanded": {"type": "Waterfall"},
    }
    assert post[2]["options"]["cover"]["aspect"]["ratio"] == {"ratio": "SixteenByNine", "position": "Vertical"}
    assert post[2]["sections"] == []


def test_create_category_defaults_match_the_backend(hub):
    channels.create_category(CH, "Plain", WS)

    (post,) = hub.writes()
    assert post[2] == {
        "name": "Plain",
        "isPinned": False,
        "notificationsEnabled": True,
        "options": opts.default_options(),
        "sections": [],
    }


# --------------------------------------------------------------------------
# Reads show the icon, the link and each category's settings
# --------------------------------------------------------------------------


def test_get_channel_shows_icon_link_and_settings(hub):
    hub.icon = {"kind": "emoji", "emoji": "🎬", "color": "#FF9500"}

    out = channels.get_channel(CH, WS)

    assert out["slug"] == "role"
    assert out["link"] == f"https://srgplus.com/{USER}/channels/role"
    assert out["icon"] == {"kind": "emoji", "color": "#FF9500", "emoji": "🎬"}
    by_name = {c["name"]: c["settings"] for c in out["categories"]}
    assert by_name["Reels"]["pinned"] is True and by_name["Reels"]["view"] == "grid"
    news = by_name["News"]
    assert (news["view"], news["card_size"], news["open_view"]) == ("list", "small", "list")
    assert by_name["Guides"]["notifications"] is False


def test_list_channels_shows_icon_link_and_archive_state(hub):
    rows = channels.list_channels(HUB, WS)

    assert [r["name"] for r in rows] == ["Role", "Video", "Shop"]
    assert rows[0]["link"] == f"https://srgplus.com/{USER}/channels/role"
    assert rows[0]["is_archived"] is False and rows[0]["privacy"] == "Public"
    assert rows[0]["icon"] is None


def test_a_flag_the_read_did_not_carry_is_not_guessed(hub):
    del hub.categories[2]["emailEnabled"]  # Guides

    cs.update_category_settings(CH, CAT_B, WS, view="list")

    (put,) = hub.writes()
    assert "emailEnabled" not in put[2], "left out, so the backend keeps the stored value"
    assert put[2]["notificationsEnabled"] is False


# --------------------------------------------------------------------------
# Review findings: voice-safe errors and no surprise changes
# --------------------------------------------------------------------------


def test_symbol_any_case_is_the_apps_symbol(hub):
    cs.set_channel_icon(CH, WS, symbol="Star.Fill", color="blue")

    assert hub.icon["symbol"] == "star.fill"


def test_a_taken_slug_says_pick_another_not_retry(hub):
    hub.taken_slugs.add("video")

    with pytest.raises(ValueError, match="'video' is taken.*pick another"):
        cs.set_channel_slug(CH, "Video", WS)
    assert hub.slug == "role"


def test_pinning_an_archived_category_is_refused_and_the_live_pin_stays(hub):
    with pytest.raises(ValueError, match="archived; restore it first"):
        cs.update_category_settings(CH, CAT_OLD, WS, pinned=True)

    assert hub.writes() == []
    assert _stored(hub, CAT_A)["isPinned"] is True


def test_a_setting_that_is_already_so_writes_nothing(hub):
    out = cs.update_category_settings(CH, CAT_A, WS, pinned=True, view="grid")

    assert out["changed"] is False and out["pinned"] is True and out["view"] == "grid"
    assert hub.writes() == []


def test_categories_by_exact_name(hub):
    out = cs.update_category_settings(CH, "guides", WS, view="list")

    assert out["category_id"] == CAT_B and out["changed"] is True
    assert cs.reorder_categories(CH, ["News", "reels"], WS)["order"][0]["name"] == "News"


def test_two_categories_with_one_name_need_the_id(hub):
    hub.categories.append(_category("6a00000000000000000000a4", "Guides"))

    with pytest.raises(ValueError, match="Several categories are called 'Guides'"):
        cs.update_category_settings(CH, "Guides", WS, pinned=True)
    with pytest.raises(ValueError, match="several have this name"):
        cs.reorder_categories(CH, ["Guides"], WS)
    assert hub.writes() == []


def test_reorder_categories_retries_only_after_a_concurrent_change(hub):
    hub.channel_put_error = _error(srg.exceptions.BadRequestError, 400, "Channel name must be 1-50 characters")

    with pytest.raises(ValueError, match="rename_channel"):
        cs.reorder_categories(CH, [CAT_B], WS)
    assert len(hub.writes()) == 1, "a 400 that is not the concurrent-change one is not retried"

    hub.calls.clear()
    hub.channel_put_error = _error(srg.exceptions.ConflictError, 409, "Channel with name Role already exists")
    with pytest.raises(ValueError, match="rename one of them first"):
        cs.reorder_categories(CH, [CAT_B], WS)


def test_reorder_channels_names_and_archived_ones(hub):
    out = cs.reorder_channels(HUB, ["shop", "Role"], WS)
    assert [c["name"] for c in out["order"]] == ["Shop", "Role", "Video"]

    with pytest.raises(ValueError, match="archived, so not in the order"):
        cs.reorder_channels(HUB, [CH_OLD], WS)


def test_reorder_channels_403_says_who_may(hub):
    hub.refused_moves[CH3] = _error(srg.exceptions.ForbiddenError, 403, "Forbidden")

    with pytest.raises(ValueError, match="Only the hub owner or an admin.*Nothing was moved"):
        cs.reorder_channels(HUB, [CH3], WS)


def test_reorder_channels_failure_part_way_says_what_moved(hub):
    hub.refused_moves[CH2] = _error(srg.exceptions.NotFoundError, 404, "Channel not found")

    with pytest.raises(RuntimeError, match="Moving 'Video' failed.*Already moved: 'Shop'"):
        cs.reorder_channels(HUB, [CH3, CH2, CH], WS)
    assert [c["id"] for c in hub.channels] == [CH3, CH, CH2]


def test_link_falls_back_to_the_name_like_the_apps(hub):
    hub.slug = None

    out = channels.get_channel(CH, WS)

    assert out["link"] == f"https://srgplus.com/{USER}/channels/Role"
    assert channels.channel_link({"hubProfileUserName": USER, "name": "Мой канал 🎬"}) == (
        f"https://srgplus.com/{USER}/channels/%D0%9C%D0%BE%D0%B9%20%D0%BA%D0%B0%D0%BD%D0%B0%D0%BB%20%F0%9F%8E%AC"
    )


def test_update_channel_checks_privacy_and_keeps_the_name(hub):
    with pytest.raises(ValueError, match='"Public" or "Private"'):
        channels.update_channel(CH, HUB, WS, privacy="2")
    assert hub.writes() == []

    channels.update_channel(CH, HUB, WS, privacy="PRIVATE")
    (put,) = hub.writes()
    assert put[2]["privacy"] == "Private" and put[2]["name"] == "Role"


def test_update_category_refuses_to_pin_an_archived_one(hub):
    with pytest.raises(ValueError, match="restore it first"):
        channels.update_category(CH, CAT_OLD, WS, is_pinned=True)
    assert hub.writes() == []


def test_a_scroll_categorys_hidden_card_size_does_not_come_back():
    stored = _custom("Classic", "Compact", "Waterfall")

    out = opts.with_changes(stored, view="grid")

    assert _presentation(out) == {"$type": "Standard", "global": {"type": "Waterfall"}}


@pytest.mark.parametrize(
    "said,ratio,position",
    [
        ("16:9 vertical", "SixteenByNine", "Vertical"),
        ("16:9 Horizontal", "SixteenByNine", "Horizontal"),
        ("4:5 horizontal", "FourByFive", "Horizontal"),
        ("3:2 portrait", "ThreeByTwo", "Vertical"),
        ("16 x 9 landscape", "SixteenByNine", "Horizontal"),
        ("square vertical", "Square", None),
    ],
)
def test_cover_ratio_takes_the_apps_label_with_a_turn(said, ratio, position):
    assert opts.ratio_of(said) == (ratio, position)


@pytest.mark.parametrize("said", ["portrait", "16:9 vertical horizontal", "wide"])
def test_cover_ratio_without_a_shape_is_refused(said):
    with pytest.raises(ValueError, match="cover_ratio"):
        opts.ratio_of(said)
