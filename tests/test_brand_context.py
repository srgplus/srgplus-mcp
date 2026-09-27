"""Brand context tools (SRGDEV-824 / SRGDEV-825): brand index + brand memory page.

The memory append must never damage the page: PATCH /contents replaces the
whole widget list, so every widget is re-sent exactly, a page with widgets that
can't be re-sent losslessly is refused, and a concurrent edit (409) is re-read
and re-applied. No network: srg_mcp._raw.call is replaced by a fake API.
"""

from __future__ import annotations

import pytest
import srg

from srg_mcp import brand_context

WS = "65f0000000000000000000ff"
HUB = "65f0000000000000000000aa"
CHANNEL = "65f0000000000000000000c1"
CATEGORY = "65f0000000000000000000k1"
PAGE = "65f000000000000000000p01"


class FakeAPI:
    """Answers the few routes the tools use and records every call."""

    def __init__(self, channels=None, references=None, contents=None, index=None):
        self.channels = channels if channels is not None else []
        self.references = references or []
        self.contents = contents or {}
        self.index = index
        self.calls: list[tuple] = []
        self.patch_conflicts = 0

    def __call__(self, workspace_id, method, path, *, json=None, params=None, headers=None):
        self.calls.append((method, path, json, params, headers))
        if method == "GET" and path == f"/api/v1/contents/{HUB}/index":
            if self.index is None:
                raise srg.exceptions.NotFoundError({"title": "Not Found"}, _Response(404))
            return self.index
        if method == "GET" and path == f"/api/v1/channels/{HUB}":
            return self.channels
        if method == "GET" and path.endswith("/references"):
            return {"items": self.references}
        if method == "GET" and path.startswith("/api/v2/contents/"):
            return self.contents[path.rsplit("/", 1)[1]]
        if method == "PATCH" and path == f"/api/v1/contents/{PAGE}":
            if self.patch_conflicts:
                self.patch_conflicts -= 1
                self.contents[PAGE]["version"] += 1
                raise srg.exceptions.ConflictError({"title": "Conflict"}, _Response(409))
            return {"id": PAGE}
        if method == "POST" and path == "/api/v1/channels":
            self.channels.append({"id": CHANNEL, "name": "Agent", "categories": []})
            return CHANNEL
        if method == "POST" and path == f"/api/v1/channels/{CHANNEL}/categories":
            return CATEGORY
        if method == "POST" and path == "/api/v1/contents":
            self.contents[PAGE] = {"id": PAGE, "version": 0, "hubProfileId": HUB,
                                   "context": [dict(json["context"][0])], "tags": []}
            return {"id": PAGE}
        if method == "PATCH" and path == f"/api/v1/contents/{PAGE}/metadata":
            return None
        raise AssertionError(f"unexpected call {method} {path}")


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.headers: dict = {}
        self.text = ""

    def json(self):
        return {}


def _page(context, version=4):
    return {"id": PAGE, "version": version, "hubProfileId": HUB, "tags": ["brand-memory"], "context": context}


def _memory_channel():
    return [{"id": CHANNEL, "name": "Agent", "categories": [{"id": CATEGORY, "name": "Memory"}]}]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    def install(fake: FakeAPI) -> FakeAPI:
        monkeypatch.setattr(brand_context._raw, "call", fake)
        monkeypatch.setattr(brand_context.time, "sleep", lambda _seconds: None)
        return fake

    return install


def test_append_adds_a_dated_line_and_resends_everything_else_unchanged(api):
    text = {"$type": "Text", "id": "t1", "title": None, "content": "Intro\n\n## Log\n- 2026-09-01 · Serge · 4:5 covers"}
    media = {"$type": "Media", "id": "m1", "title": "Reel", "autoplay": False, "playableAsset": {"id": "a1", "name": "x"}}
    fake = api(FakeAPI(channels=_memory_channel(), references=[{"id": PAGE, "name": "Brand memory"}],
                       contents={PAGE: _page([text, media])}))

    result = brand_context.append_brand_memory(HUB, WS, "No emojis in captions", author="Claude")

    method, path, body, params, headers = next(c for c in fake.calls if c[0] == "PATCH")
    assert headers == {"If-Match": '"4"'}
    assert params == {"hubProfileId": HUB}
    written_text, written_media = body["context"]
    assert written_text["id"] == "t1"
    assert written_text["content"].startswith(text["content"] + "\n- ")
    assert written_text["content"].endswith("· Claude · No emojis in captions")
    assert written_media == {"$type": "Media", "id": "m1", "title": "Reel", "assetId": "a1", "autoplay": False}
    assert result["content_id"] == PAGE


def test_append_refuses_a_page_with_widgets_it_cannot_resend(api):
    links = {"$type": "LinkList", "id": "l1", "title": None, "links": [{"$type": "CustomLink", "title": "x", "url": "https://x"}]}
    fake = api(FakeAPI(channels=_memory_channel(), references=[{"id": PAGE, "name": "Brand memory"}],
                       contents={PAGE: _page([links])}))

    with pytest.raises(RuntimeError, match="LinkList"):
        brand_context.append_brand_memory(HUB, WS, "anything")
    assert not [c for c in fake.calls if c[0] == "PATCH"]


def test_append_rereads_and_retries_after_a_concurrent_edit(api):
    text = {"$type": "Text", "id": "t1", "title": None, "content": "## Log"}
    fake = api(FakeAPI(channels=_memory_channel(), references=[{"id": PAGE, "name": "Brand memory"}],
                       contents={PAGE: _page([text], version=7)}))
    fake.patch_conflicts = 1

    brand_context.append_brand_memory(HUB, WS, "entry")

    patches = [c for c in fake.calls if c[0] == "PATCH"]
    assert [p[4]["If-Match"] for p in patches] == ['"7"', '"8"']


def test_first_append_creates_the_private_agent_memory_page(api):
    fake = api(FakeAPI(channels=[]))

    brand_context.append_brand_memory(HUB, WS, "first fact")

    posts = {c[1]: c[2] for c in fake.calls if c[0] == "POST"}
    assert posts["/api/v1/channels"] == {"name": "Agent", "hubProfileId": HUB, "privacy": "Private"}
    assert posts[f"/api/v1/channels/{CHANNEL}/categories"]["notificationsEnabled"] is False
    content = posts["/api/v1/contents"]
    assert content["privacy"] == "Private"
    assert content["channels"] == [{"channelId": CHANNEL, "categoryIds": [CATEGORY]}]
    metadata = next(c for c in fake.calls if c[1].endswith("/metadata"))
    assert metadata[2] == {"tags": ["brand-memory"]}


def test_a_full_text_block_rolls_over_into_a_new_one():
    widgets = [{"$type": "Text", "id": "t1", "title": None, "content": "x" * (brand_context.TEXT_LIMIT - 5)}]

    result = brand_context._append(widgets, "- 2026-09-27 · agent · entry")

    assert len(result) == 2
    assert result[0] == widgets[0]
    assert result[1]["$type"] == "Text" and result[1]["content"] == "- 2026-09-27 · agent · entry"
    assert len(result[1]["id"]) == 24


def test_multiline_entries_are_indented_under_their_bullet():
    entry = brand_context._entry("Summary line\nDetail one\n\nDetail two", "Serge")

    lines = entry.splitlines()
    assert lines[0].endswith("· Serge · Summary line")
    assert lines[1:] == ["  Detail one", "", "  Detail two"]


def test_get_brand_memory_without_a_page_says_so(api):
    api(FakeAPI(channels=[]))

    result = brand_context.get_brand_memory(HUB, WS)

    assert result["content_id"] is None
    assert "append_brand_memory" in result["note"]


def test_get_brand_memory_returns_the_text(api):
    text = {"$type": "Text", "id": "t1", "title": None, "content": "## Log\n- fact"}
    api(FakeAPI(channels=_memory_channel(), references=[{"id": PAGE, "name": "Brand memory"}],
                contents={PAGE: {**_page([text]), "modified": "2026-09-20T09:01:44Z"}}))

    result = brand_context.get_brand_memory(HUB, WS)

    assert result == {"content_id": PAGE, "version": 4, "updated": "2026-09-20T09:01:44Z", "text": "## Log\n- fact"}


def test_brand_index_outline_nests_sub_contents_and_counts_files(api):
    index = {
        "hubProfileId": HUB, "revision": "abc", "updated": "2026-09-26T22:14:03Z", "memoryContentId": None,
        "channels": [{"id": CHANNEL, "name": "D6 PR", "privacy": "Private", "categories": [
            {"id": CATEGORY, "name": "Press", "contentIds": ["c1"]}]}],
        "contents": [
            {"id": "c1", "name": "USING CRM 3", "created": "2026-05-03T14:22:10Z", "privacy": "Preview",
             "childContentIds": ["c2"], "assetIds": ["a1"], "widgetAssetIds": [], "mainAssetId": None},
            {"id": "c2", "name": "Part 1", "created": "2026-05-04T10:00:00Z", "privacy": "Preview",
             "childContentIds": ["c1"], "assetIds": [], "widgetAssetIds": [], "mainAssetId": None},
        ],
        "assets": [{"id": "a1", "size": 10}],
    }
    api(FakeAPI(index=index))

    result = brand_context.get_brand_index(HUB, WS)

    assert result["totals"] == {"channels": 1, "categories": 1, "contents": 2, "files": 1, "file_bytes": 10}
    assert result["outline"].splitlines() == [
        f"## D6 PR (Private) · {CHANNEL}",
        f"- Press · {CATEGORY} · 1 contents",
        "  - USING CRM 3 · c1 · 2026-05-03 · Preview · 1 sub, 1 files",
        "    - Part 1 · c2 · 2026-05-04 · Preview · 1 sub",
    ]


def test_brand_index_on_an_older_server_explains_the_fallback(api):
    api(FakeAPI(index=None))

    with pytest.raises(RuntimeError, match="no brand index yet"):
        brand_context.get_brand_index(HUB, WS)


def test_a_key_without_a_user_gets_a_clear_explanation(api, monkeypatch):
    def forbidden(workspace_id, method, path, **kwargs):
        if method == "GET" and path == f"/api/v1/channels/{HUB}":
            return _memory_channel()
        raise srg.exceptions.ForbiddenError({"title": "Forbidden"}, _Response(403))

    monkeypatch.setattr(brand_context._raw, "call", forbidden)

    with pytest.raises(RuntimeError, match="treat API keys like a visitor"):
        brand_context.get_brand_memory(HUB, WS)
