"""Hub profile widget tools: full read, one-widget writes, content cards in order.

The tools run against a small in-memory model of the hub profile endpoints that
mirrors the backend rules that matter: If-Match → 409, every write bumps the
version, the one-widget endpoints leave the other widgets exactly as stored, a
content widget keeps its references in the order sent, a missing reference is a
404 that names it, and a widget body must carry "$type" as its FIRST key (the
backend reads the discriminator only from the first property).
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
import srg.exceptions

from srg_mcp import hub_profiles, hub_widgets

WS = "ws1"
HUB = "65f0000000000000000000aa"
OTHER_HUB = "65f0000000000000000000bb"
C = [f"65f00000000000000000c0{n:02x}" for n in range(8)]  # contents
A = [f"65f00000000000000000a0{n:02x}" for n in range(4)]  # Drive assets
W_TEXT, W_LINKS, W_CARDS, W_FILES, W_HUBS, W_VIDEO, W_CONTACT = (
    f"65f00000000000000000f0{n:02x}" for n in range(7)
)
MISSING = "65f0000000000000000003ff"


def _error(cls, status: int, detail: str):
    return cls({"detail": detail}, SimpleNamespace(status_code=status))


def _first_key_is_type(obj: dict, where: str) -> None:
    assert next(iter(obj)) == "$type", f"{where}: $type must be the first key, got {list(obj)}"


class FakeHub:
    """Stands in for srg_mcp._raw.call: one hub profile and its widget endpoints."""

    def __init__(self) -> None:
        self.version = 4
        self.calls: list[dict] = []
        self.contents = {cid: f"Content {i}" for i, cid in enumerate(C)}
        self.assets = {aid: f"File {i}" for i, aid in enumerate(A)}
        self.hubs = {OTHER_HUB: ("Other Brand", "other-brand")}
        self.bump_before_next_write = 0  # simulate someone else editing meanwhile
        self._next = 0x10
        self.widgets: list[dict] = [
            {"$type": "Text", "id": W_TEXT, "title": "About", "content": "Hello **world**"},
            {
                "$type": "LinkList", "id": W_LINKS, "title": None,
                "links": [
                    {"$type": "KnownLink", "id": "65f00000000000000000e001", "title": "Instagram",
                     "url": "https://instagram.com/brand", "iconUrl": {"url": "https://fav/ig.png"}},
                    {"$type": "CustomLink", "id": "65f00000000000000000e002", "title": "Shop",
                     "url": "https://shop.example", "extension": "png",
                     "iconUrl": {"url": "https://signed/icon.png"}},
                ],
            },
            {
                "$type": "ContentWidget", "id": W_CARDS, "title": None, "referenceType": "Content",
                "references": [self._content_ref(C[1]), self._content_ref(C[0])],
            },
            {
                "$type": "ContentWidget", "id": W_FILES, "title": "Files", "referenceType": "Asset",
                "references": [{"$type": "Image", "id": A[0], "name": "File 0", "cover": {"url": "x"}}],
            },
            {
                "$type": "HubProfile", "id": W_HUBS, "title": "Friends",
                "hubProfiles": [{"id": OTHER_HUB, "name": "Other Brand", "userName": "other-brand",
                                 "avatar": {"url": "https://signed/a.png"}}],
            },
            {
                "$type": "Media", "id": W_VIDEO, "title": None, "autoplay": True,
                "playableAsset": {"$type": "Video", "id": A[1], "name": "File 1", "hlsStreamUrl": "https://hls"},
            },
            {
                "$type": "Contact", "id": W_CONTACT, "title": "Write us",
                "contacts": [{"$type": "Email", "id": "65f00000000000000000d001", "title": "Mail",
                              "details": "hi@brand.example", "iconUrl": "https://signed/mail.png",
                              "extension": "png"}],
            },
        ]

    # -- helpers ---------------------------------------------------------------------------
    def _content_ref(self, cid: str) -> dict:
        return {"$type": "Content", "id": cid, "name": self.contents[cid], "created": "2026-09-30T00:00:00Z",
                "cover": None, "previewText": "...", "topContentCovers": []}

    def _new_id(self) -> str:
        self._next += 1
        return f"65f00000000000000000f0{self._next:02x}"

    def writes(self) -> list[dict]:
        return [c for c in self.calls if c["method"] != "GET"]

    def ids(self) -> list[str]:
        return [w["id"] for w in self.widgets]

    def by_id(self, widget_id: str) -> dict:
        return next(w for w in self.widgets if w["id"] == widget_id)

    def _check_version(self, headers: dict | None) -> None:
        if self.bump_before_next_write:
            self.bump_before_next_write -= 1
            self.version += 1  # someone else saved the profile in between
        if headers and "If-Match" in headers:
            expected = int(headers["If-Match"].strip('"'))
            if expected != self.version:
                raise _error(srg.exceptions.ConflictError, 409,
                             f"Hub profile with id: {HUB} is at version {self.version}, not {expected}")

    def _resolve(self, body: dict, widget_id: str) -> dict:
        """A widget write body → the stored widget as GET returns it."""
        _first_key_is_type(body, "widget")
        kind = body["$type"]
        out = {"$type": kind, "id": widget_id, "title": body.get("title")}
        if kind == "Text":
            out["content"] = body["content"]
        elif kind == "LinkList":
            links = []
            for link in body["links"]:
                _first_key_is_type(link, "link")
                links.append({"$type": link["$type"], "id": link.get("id") or self._new_id(),
                              "title": link["title"], "url": link["url"], "iconUrl": None})
            out["links"] = links
        elif kind == "ContentWidget":
            refs = []
            for ref in body["referenceIds"]:
                _first_key_is_type(ref, "reference")
                refs.append(ref)
            missing = [r["id"] for r in refs if r["id"] not in (self.contents if r["$type"] == "Content" else self.assets)]
            if missing:
                raise _error(srg.exceptions.NotFoundError, 404,
                             f"Some content widget references are not found: {', '.join(missing)}.")
            out["referenceType"] = body["referenceType"]
            out["references"] = [
                self._content_ref(r["id"]) if r["$type"] == "Content"
                else {"$type": "File", "id": r["id"], "name": self.assets[r["id"]]}
                for r in refs
            ]
        elif kind == "HubProfile":
            out["hubProfiles"] = [{"id": h, "name": self.hubs[h][0], "userName": self.hubs[h][1]}
                                  for h in body["hubProfileIds"]]
        elif kind == "Media":
            out["autoplay"] = body["autoplay"]
            out["playableAsset"] = {"$type": "Video", "id": body["assetId"], "name": self.assets[body["assetId"]]}
        elif kind == "Contact":
            for contact in body["contacts"]:
                _first_key_is_type(contact, "contact")
            out["contacts"] = [{**c, "id": c.get("id") or self._new_id()} for c in body["contacts"]]
        return out

    def _answer(self, widget_id: str | None) -> dict:
        self.version += 1
        return {"id": HUB, "version": self.version, "widgetId": widget_id, "widgetIds": self.ids(), "widgets": []}

    # -- the API ---------------------------------------------------------------------------
    def __call__(self, workspace_id, method, path, *, json=None, params=None, headers=None):
        self.calls.append({"method": method, "path": path, "json": copy.deepcopy(json), "headers": headers})
        base = f"/api/v1/hub-profiles/{HUB}"
        if method == "GET" and path == base:
            return {"id": HUB, "name": "Brand", "userName": "brand", "version": self.version,
                    "widgets": copy.deepcopy(self.widgets)}
        if method == "PATCH" and path == base:
            self._check_version(headers)
            if "widgets" in json:
                self.widgets = [self._resolve(w, w.get("id") or self._new_id()) for w in json["widgets"]]
            return self._answer(None)
        if method == "POST" and path == f"{base}/widgets":
            self._check_version(headers)
            widget = json["widget"]
            assert "id" not in widget, "a new widget is sent without an id"
            position = json.get("position", len(self.widgets))
            if not 0 <= position <= len(self.widgets):
                raise _error(srg.exceptions.BadRequestError, 400, "position must be between 0 and the count")
            if len(self.widgets) >= 20:
                raise _error(srg.exceptions.BadRequestError, 400, "Widgets count must be less or equal that 20")
            new_id = self._new_id()
            self.widgets.insert(position, self._resolve(widget, new_id))
            return self._answer(new_id)
        if method == "PUT" and path == f"{base}/widgets/order":
            self._check_version(headers)
            order = json["widgetIds"]
            unknown = [i for i in order if i not in self.ids()]
            if unknown:
                raise _error(srg.exceptions.BadRequestError, 400, f"The profile has no widget with id {unknown}.")
            self.widgets = [self.by_id(i) for i in order] + [w for w in self.widgets if w["id"] not in order]
            return self._answer(None)
        if path.startswith(f"{base}/widgets/"):
            widget_id = path.rsplit("/", 1)[1]
            self._check_version(headers)
            if widget_id not in self.ids():
                raise _error(srg.exceptions.NotFoundError, 404, f"Hub profile {HUB} has no widget with id {widget_id}.")
            index = self.ids().index(widget_id)
            if method == "DELETE":
                del self.widgets[index]
                return self._answer(widget_id)
            if method == "PUT":
                assert json.get("id") in (None, widget_id)
                written = self._resolve(json, widget_id)
                if written["$type"] != self.widgets[index]["$type"]:
                    raise _error(srg.exceptions.BadRequestError, 400, "the type cannot change")
                self.widgets[index] = written
                return self._answer(widget_id)
        raise AssertionError(f"unexpected call {method} {path}")


@pytest.fixture
def hub(monkeypatch) -> FakeHub:
    fake = FakeHub()
    monkeypatch.setattr(hub_widgets._raw, "call", fake)
    monkeypatch.setattr(hub_profiles._raw, "call", fake)
    return fake


def _content_ids(fake: FakeHub, widget_id: str) -> list[str]:
    return [r["id"] for r in fake.by_id(widget_id)["references"]]


# ---- read ----------------------------------------------------------------------------------


def test_get_reads_every_widget_in_full_in_display_order(hub):
    out = hub_widgets.get_hub_profile_widgets(HUB, WS)

    assert out["version"] == 4
    assert out["count"] == 7
    widgets = out["widgets"]
    assert [w["id"] for w in widgets] == [W_TEXT, W_LINKS, W_CARDS, W_FILES, W_HUBS, W_VIDEO, W_CONTACT]
    assert [w["position"] for w in widgets] == list(range(7))
    assert widgets[0] == {"$type": "Text", "id": W_TEXT, "title": "About", "position": 0, "content": "Hello **world**"}
    cards = widgets[2]
    assert cards["referenceType"] == "Content"
    assert cards["referenceIds"] == [{"$type": "Content", "id": C[1]}, {"$type": "Content", "id": C[0]}]
    assert cards["references"] == [
        {"$type": "Content", "id": C[1], "name": "Content 1"},
        {"$type": "Content", "id": C[0], "name": "Content 0"},
    ]
    assert cards["count"] == 2
    # Asset cards are read with their kind, written back as Asset references.
    assert widgets[3]["references"] == [{"$type": "Image", "id": A[0], "name": "File 0"}]
    assert widgets[3]["referenceIds"] == [{"$type": "Asset", "id": A[0]}]
    assert widgets[4]["hubProfileIds"] == [OTHER_HUB]
    assert widgets[4]["hubProfiles"] == [{"id": OTHER_HUB, "name": "Other Brand", "userName": "other-brand"}]
    assert widgets[5]["assetId"] == A[1] and widgets[5]["autoplay"] is True
    assert widgets[5]["playableAsset"] == {"$type": "Video", "id": A[1], "name": "File 1"}
    assert widgets[6]["contacts"] == [{"$type": "Email", "id": "65f00000000000000000d001", "title": "Mail",
                                       "details": "hi@brand.example", "has_icon": True}]
    links = widgets[1]["links"]
    assert links[0]["platform"] == "instagram" and links[1]["$type"] == "CustomLink"
    # Compact: no signed cover / stream URLs.
    assert "cover" not in json.dumps(widgets) and "hls" not in json.dumps(widgets)


# ---- set_hub_profile_content_widget -----------------------------------------------------------


def test_set_content_widget_replaces_the_only_content_widget_in_the_given_order(hub):
    before = copy.deepcopy(hub.widgets)

    out = hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[C[3], C[2], C[1]])

    (put,) = hub.writes()
    assert put["method"] == "PUT" and put["path"] == f"/api/v1/hub-profiles/{HUB}/widgets/{W_CARDS}"
    assert put["json"] == {
        "$type": "ContentWidget", "title": None, "referenceType": "Content",
        "referenceIds": [{"$type": "Content", "id": C[3]}, {"$type": "Content", "id": C[2]},
                         {"$type": "Content", "id": C[1]}],
    }
    assert put["headers"] == {"If-Match": '"4"'}  # tied to the profile it was built from
    assert _content_ids(hub, W_CARDS) == [C[3], C[2], C[1]]
    # Every other widget is exactly as it was.
    assert [w for w in hub.widgets if w["id"] != W_CARDS] == [w for w in before if w["id"] != W_CARDS]
    assert out["widget_id"] == W_CARDS
    assert out["created"] is False
    assert out["content_ids"] == [C[3], C[2], C[1]]
    assert out["references"][0] == {"$type": "Content", "id": C[3], "name": "Content 3"}
    assert out["count"] == 3 and out["in_requested_order"] is True
    assert out["skipped"] == []
    assert out["version"] == 5
    assert [w["id"] for w in out["widgets"]] == hub.ids()


def test_set_content_widget_creates_one_when_the_page_has_none(hub):
    hub.widgets = [w for w in hub.widgets if w["id"] != W_CARDS]

    out = hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[C[0]], position=0)

    (post,) = hub.writes()
    assert post["method"] == "POST" and post["json"]["position"] == 0
    assert post["json"]["widget"]["referenceIds"] == [{"$type": "Content", "id": C[0]}]
    assert out["created"] is True
    assert hub.widgets[0]["id"] == out["widget_id"]
    assert out["content_ids"] == [C[0]]


def test_set_content_widget_by_title_finds_or_creates_that_widget(hub):
    created = hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[C[4]], title="Reports")
    assert created["created"] is True and created["title"] == "Reports"
    assert hub.widgets[-1]["title"] == "Reports"  # added at the end

    again = hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[C[5], C[4]], title="Reports")
    assert again["created"] is False and again["widget_id"] == created["widget_id"]
    assert _content_ids(hub, created["widget_id"]) == [C[5], C[4]]
    assert _content_ids(hub, W_CARDS) == [C[1], C[0]]  # the untitled one is untouched


def test_set_content_widget_title_renames_and_empty_title_clears(hub):
    hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[C[0]], widget_id=W_CARDS, title="Playbooks")
    assert hub.by_id(W_CARDS)["title"] == "Playbooks"

    hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[C[0]], widget_id=W_CARDS)
    assert hub.by_id(W_CARDS)["title"] == "Playbooks"  # omitted keeps it

    hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[C[0]], widget_id=W_CARDS, title="")
    assert hub.by_id(W_CARDS)["title"] is None


def test_set_content_widget_with_several_candidates_asks_which(hub):
    hub.widgets.append({"$type": "ContentWidget", "id": W_CARDS[:-2] + "99", "title": "More",
                        "referenceType": "Content", "references": []})

    with pytest.raises(ValueError, match="pass widget_id"):
        hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[C[0]])
    assert hub.writes() == []


@pytest.mark.parametrize(
    ("widget_id", "message"),
    [(W_FILES, "Drive assets"), (W_TEXT, "not a ContentWidget"), (MISSING, "no widget")],
)
def test_set_content_widget_refuses_a_widget_that_is_not_content_cards(hub, widget_id, message):
    with pytest.raises(ValueError, match=message):
        hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[C[0]], widget_id=widget_id)
    assert hub.writes() == []


def test_set_content_widget_skips_bad_repeated_and_missing_ids_and_writes_the_rest(hub):
    out = hub_widgets.set_hub_profile_content_widget(
        HUB, WS, content_ids=[C[2], "nope", C[2], MISSING, C[3]]
    )

    assert _content_ids(hub, W_CARDS) == [C[2], C[3]]
    reasons = {s["id"]: s["reason"] for s in out["skipped"]}
    assert "24 hex" in reasons["nope"]
    assert "listed twice" in reasons[C[2]]
    assert "not found" in reasons[MISSING]
    assert out["content_ids"] == [C[2], C[3]] and out["in_requested_order"] is True
    # First write refused (404, nothing written), the second without the missing id.
    assert [w["method"] for w in hub.writes()] == ["PUT", "PUT"]


def test_set_content_widget_never_empties_the_widget_by_accident(hub):
    with pytest.raises(ValueError, match="None of the content ids was found"):
        hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[MISSING])
    with pytest.raises(ValueError, match="nothing was changed"):
        hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=["bad"])
    assert _content_ids(hub, W_CARDS) == [C[1], C[0]]


def test_set_content_widget_empty_list_empties_it(hub):
    out = hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[])
    assert out["content_ids"] == [] and hub.by_id(W_CARDS)["references"] == []


def test_set_content_widget_stale_expected_version_is_409_without_retry(hub):
    with pytest.raises(srg.exceptions.ConflictError):
        hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[C[0]], expected_version=3)
    (put,) = hub.writes()
    assert put["headers"] == {"If-Match": '"3"'}
    assert _content_ids(hub, W_CARDS) == [C[1], C[0]]


def test_set_content_widget_without_expected_version_retries_on_a_concurrent_edit(hub):
    hub.bump_before_next_write = 1

    out = hub_widgets.set_hub_profile_content_widget(HUB, WS, content_ids=[C[6]])

    assert [w["headers"] for w in hub.writes()] == [{"If-Match": '"4"'}, {"If-Match": '"5"'}]
    assert out["content_ids"] == [C[6]]


# ---- add / update / remove / reorder -----------------------------------------------------------


def test_add_widget_at_a_position_sends_no_id_and_reads_it_back(hub):
    out = hub_widgets.add_hub_profile_widget(
        HUB, WS, widget={"id": W_TEXT, "content": "Intro", "type": "text", "title": "  Hi  "},
        position=0, expected_version=4,
    )

    (post,) = hub.writes()
    assert post["json"] == {"widget": {"$type": "Text", "title": "Hi", "content": "Intro"}, "position": 0}
    assert post["headers"] == {"If-Match": '"4"'}
    assert out["widget"]["content"] == "Intro" and out["widget"]["position"] == 0
    assert out["widgets"][0]["id"] == out["widget"]["id"] != W_TEXT
    assert out["version"] == 5


def test_add_content_widget_in_the_content_context_shape(hub):
    out = hub_widgets.add_hub_profile_widget(HUB, WS, widget={
        "$type": "ContentWidget", "title": "Playbooks", "referenceType": "Content",
        "referenceIds": [{"$type": "Content", "id": C[5]}, C[4]],
    })

    body = hub.writes()[0]["json"]["widget"]
    assert body["referenceIds"] == [{"$type": "Content", "id": C[5]}, {"$type": "Content", "id": C[4]}]
    assert [r["id"] for r in out["widget"]["references"]] == [C[5], C[4]]
    assert hub.ids()[-1] == out["widget"]["id"]


@pytest.mark.parametrize(
    ("widget", "message"),
    [
        ({"$type": "Gallery"}, "one of Text"),
        ({"$type": "Text"}, "content"),
        ({"$type": "Text", "content": "x" * 5001}, "5000"),
        ({"$type": "Text", "content": "ok", "title": "t" * 151}, "150"),
        ({"$type": "ContentWidget", "referenceType": "Content",
          "referenceIds": [{"$type": "Asset", "id": A[0]}]}, "every reference must be a content"),
        ({"$type": "ContentWidget", "referenceIds": [{"$type": "Content", "id": C[0]},
                                                     {"$type": "Asset", "id": A[0]}]}, "not both"),
        ({"$type": "ContentWidget", "referenceIds": [C[0], C[0]]}, "repeated"),
        ({"$type": "ContentWidget", "referenceType": "Contents", "referenceIds": []}, "referenceType"),
        ({"$type": "ContentWidget", "referenceIds": ["not-an-id"]}, "24 hex"),
        ({"$type": "HubProfile", "hubProfileIds": []}, "hubProfileIds"),
        ({"$type": "Media"}, "assetId"),
        ({"$type": "Media", "assetId": A[1], "autoplay": "yes"}, "autoplay"),
        ({"$type": "Contact", "contacts": [{"$type": "Fax", "details": "1"}]}, "Email"),
        ({"$type": "LinkList", "links": [{"title": "A", "url": "https://a"}, {"title": "A", "url": "https://b"}]},
         "unique"),
    ],
)
def test_bad_widgets_fail_before_any_write(hub, widget, message):
    with pytest.raises(ValueError, match=message):
        hub_widgets.add_hub_profile_widget(HUB, WS, widget=widget)
    assert hub.calls == []


def test_update_widget_changes_only_the_fields_passed(hub):
    out = hub_widgets.update_hub_profile_widget(HUB, W_CARDS, {"title": "Reports"}, WS)

    (put,) = hub.writes()
    assert put["path"].endswith(f"/widgets/{W_CARDS}")
    assert put["json"] == {
        "$type": "ContentWidget", "title": "Reports", "referenceType": "Content",
        "referenceIds": [{"$type": "Content", "id": C[1]}, {"$type": "Content", "id": C[0]}],
    }
    assert put["headers"] == {"If-Match": '"4"'}
    assert out["widget"]["title"] == "Reports" and out["widget"]["count"] == 2


def test_update_widget_takes_a_widget_as_read_back(hub):
    read = hub_widgets.get_hub_profile_widgets(HUB, WS)["widgets"]
    links = copy.deepcopy(read[1])
    links["links"].append({"title": "Site", "url": "brand.example"})
    hubs = copy.deepcopy(read[4])
    hubs["hubProfiles"] = [{"id": OTHER_HUB}]  # read-only list: used when hubProfileIds is absent
    del hubs["hubProfileIds"]

    hub_widgets.update_hub_profile_widget(HUB, W_LINKS, links, WS)
    hub_widgets.update_hub_profile_widget(HUB, W_HUBS, hubs, WS)

    sent_links = hub.writes()[0]["json"]
    assert sent_links["links"] == [
        {"$type": "KnownLink", "title": "Instagram", "url": "https://instagram.com/brand",
         "id": "65f00000000000000000e001"},
        {"$type": "CustomLink", "title": "Shop", "url": "https://shop.example", "id": "65f00000000000000000e002"},
        {"$type": "KnownLink", "title": "Site", "url": "https://brand.example"},
    ]
    assert hub.writes()[1]["json"]["hubProfileIds"] == [OTHER_HUB]


def test_update_widget_keeps_contacts_without_sending_icons(hub):
    hub_widgets.update_hub_profile_widget(HUB, W_CONTACT, {"title": "Mail us"}, WS)

    assert hub.writes()[0]["json"] == {
        "$type": "Contact", "title": "Mail us",
        "contacts": [{"$type": "Email", "id": "65f00000000000000000d001", "title": "Mail",
                      "details": "hi@brand.example"}],
    }


@pytest.mark.parametrize(
    ("widget_id", "widget", "message"),
    [
        (W_TEXT, {"$type": "LinkList", "links": []}, "type cannot change"),
        (MISSING, {"title": "x"}, "no widget"),
        (W_TEXT, {"id": W_LINKS, "title": "x"}, "is not widget_id"),
        (W_TEXT, {}, "fields to change"),
    ],
)
def test_update_widget_refusals_write_nothing(hub, widget_id, widget, message):
    with pytest.raises(ValueError, match=message):
        hub_widgets.update_hub_profile_widget(HUB, widget_id, widget, WS)
    assert hub.writes() == []


def test_update_widget_with_stale_expected_version_is_409(hub):
    with pytest.raises(srg.exceptions.ConflictError):
        hub_widgets.update_hub_profile_widget(HUB, W_TEXT, {"content": "New"}, WS, expected_version=2)
    assert len(hub.writes()) == 1
    assert hub.by_id(W_TEXT)["content"] == "Hello **world**"


def test_remove_widget_reports_what_went_and_keeps_the_rest(hub):
    out = hub_widgets.remove_hub_profile_widget(HUB, W_CARDS, WS, expected_version=4)

    (delete,) = hub.writes()
    assert delete["method"] == "DELETE" and delete["headers"] == {"If-Match": '"4"'}
    assert out["removed"]["id"] == W_CARDS and out["removed"]["count"] == 2
    assert W_CARDS not in hub.ids() and len(hub.ids()) == 6
    assert hub.contents[C[0]] == "Content 0"  # the contents themselves stay
    assert [w["id"] for w in out["widgets"]] == hub.ids()


def test_remove_unknown_widget_writes_nothing(hub):
    with pytest.raises(ValueError, match="no widget"):
        hub_widgets.remove_hub_profile_widget(HUB, MISSING, WS)
    assert hub.writes() == []


def test_reorder_puts_listed_widgets_first(hub):
    out = hub_widgets.reorder_hub_profile_widgets(HUB, [W_CARDS, W_TEXT], WS, expected_version=4)

    (put,) = hub.writes()
    assert put["json"] == {"widgetIds": [W_CARDS, W_TEXT]}
    assert put["headers"] == {"If-Match": '"4"'}
    assert [w["id"] for w in out["widgets"]] == [W_CARDS, W_TEXT, W_LINKS, W_FILES, W_HUBS, W_VIDEO, W_CONTACT]


@pytest.mark.parametrize(("ids", "message"), [([], "widget_ids"), ([W_TEXT, W_TEXT], "repeated"), (["x"], "24 hex")])
def test_reorder_refusals_write_nothing(hub, ids, message):
    with pytest.raises(ValueError, match=message):
        hub_widgets.reorder_hub_profile_widgets(HUB, ids, WS)
    assert hub.calls == []


# ---- update_hub_profile(widgets=...) / create_hub_profile(widgets=...) ------------------------------


def test_update_hub_profile_widgets_round_trips_the_read_shape(hub):
    read = hub_widgets.get_hub_profile_widgets(HUB, WS)["widgets"]
    read.reverse()
    read.append({"$type": "Text", "content": "New block"})

    out = hub_profiles.update_hub_profile(HUB, WS, widgets=read, expected_version=4)

    patch = hub.writes()[0]
    assert patch["method"] == "PATCH" and patch["headers"] == {"If-Match": '"4"'}
    sent = patch["json"]["widgets"]
    assert [w.get("id") for w in sent] == [W_CONTACT, W_VIDEO, W_HUBS, W_FILES, W_CARDS, W_LINKS, W_TEXT, None]
    assert sent[4] == {"$type": "ContentWidget", "id": W_CARDS, "title": None, "referenceType": "Content",
                       "referenceIds": [{"$type": "Content", "id": C[1]}, {"$type": "Content", "id": C[0]}]}
    assert sent[3]["referenceIds"] == [{"$type": "Asset", "id": A[0]}]
    assert sent[1] == {"$type": "Media", "id": W_VIDEO, "title": None, "assetId": A[1], "autoplay": True}
    for widget in sent:  # read-only fields never reach the API
        assert not {"position", "count", "references", "hubProfiles", "playableAsset"} & set(widget)
    assert out["updated_fields"] == ["widgets"]
    assert hub.ids()[:7] == [W_CONTACT, W_VIDEO, W_HUBS, W_FILES, W_CARDS, W_LINKS, W_TEXT]


def test_update_hub_profile_widgets_and_links_are_exclusive(hub):
    with pytest.raises(ValueError, match="either links or widgets"):
        hub_profiles.update_hub_profile(HUB, WS, links=[], widgets=[])
    with pytest.raises(ValueError, match="at most 20"):
        hub_profiles.update_hub_profile(HUB, WS, widgets=[{"$type": "Text", "content": "x"}] * 21)
    assert hub.calls == []


def test_create_hub_profile_takes_only_the_widgets_create_knows(monkeypatch):
    sent = {}

    class _Created:
        def model_dump(self, mode):
            return {"id": HUB}

    class _HubProfiles:
        def create(self, **kwargs):
            sent.update(kwargs)
            return _Created()

    monkeypatch.setattr(hub_profiles, "get_client", lambda: SimpleNamespace(hub_profiles=_HubProfiles()))

    with pytest.raises(ValueError, match="add_hub_profile_widget"):
        hub_profiles.create_hub_profile("Brand", "brand", WS, widgets=[
            {"$type": "ContentWidget", "referenceIds": [C[0]]},
        ])
    assert sent == {}

    hub_profiles.create_hub_profile("Brand", "brand", WS, widgets=[
        {"type": "text", "content": "Hi", "id": W_TEXT},
        {"$type": "LinkList", "links": [{"title": "IG", "url": "instagram.com/brand"}]},
    ])
    assert sent["widgets"] == [
        {"$type": "Text", "title": None, "content": "Hi"},
        {"$type": "LinkList", "title": None,
         "links": [{"$type": "KnownLink", "title": "IG", "url": "https://instagram.com/brand"}]},
    ]


# ---- guidance ---------------------------------------------------------------------------------


def test_guide_and_instructions_point_to_the_widget_tools():
    from srg_mcp._app import mcp
    from srg_mcp.guide import SRGPLUS_GUIDE
    from srg_mcp.serve.profiles import CORE_TOOL_NAMES

    tools = (
        "get_hub_profile_widgets", "add_hub_profile_widget", "update_hub_profile_widget",
        "set_hub_profile_content_widget", "remove_hub_profile_widget", "reorder_hub_profile_widgets",
    )
    text = " ".join(SRGPLUS_GUIDE.split())
    assert "## Hub profile widgets" in SRGPLUS_GUIDE
    for tool in tools:
        assert tool in CORE_TOOL_NAMES
        assert f"`{tool}(" in SRGPLUS_GUIDE, tool
        assert tool in mcp.instructions, tool
    assert "never the contents it shows" in text
    assert "REPLACES ALL widgets" in text
    assert "get_hub_profile_widgets" in hub_profiles.get_hub_profile.__doc__
    for tool in tools[1:]:
        doc = mcp._tool_manager.get_tool(tool).description
        assert "expected_version" in doc and "409" in doc, tool
