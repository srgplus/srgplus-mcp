"""Featured Assets / Featured Content tools (SRGDEV-756).

The bug: update_content(categories=[{..., "references": [...], "sections": [...]}])
returned 200 and the API silently kept only `options`. The items live behind
their own endpoints. These tests run the tools against a small in-memory model
of those endpoints that mirrors the backend rules that matter: a new batch is
prepended to its section, an item can be in only one section of a category
(409), foreign-hub ids are 403, unknown ids 404, and the default section can
be neither moved before, renamed nor deleted.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
import srg.exceptions

from srg_mcp import contents, featured

CID = "65f000000000000000000001"
HUB = "65f0000000000000000000aa"
WS = "ws-1"
FRAMES = [f"65f0000000000000000001{n:02x}" for n in range(0x10)]
FOREIGN = "65f0000000000000000002ff"
MISSING = "65f0000000000000000003ff"


def _error(cls, status: int, detail: str):
    return cls({"detail": detail}, SimpleNamespace(status_code=status))


class FakeContentHub:
    """Stands in for srg_mcp._raw.call; models one content's two categories."""

    def __init__(self, private: bool = False) -> None:
        self.private = private
        self.calls: list[tuple[str, str, object]] = []
        self.known = set(FRAMES) | {FOREIGN}
        self.sections = {
            kind: [{"$type": "SingleContentSection", "id": f"default-{kind}", "rank": 100.0}]
            for kind in ("Asset", "Content")
        }
        self.refs: dict[str, list[dict]] = {"Asset": [], "Content": []}
        self._next_section = 1

    # -- helpers ---------------------------------------------------------
    def writes(self) -> list[tuple[str, str, object]]:
        return [c for c in self.calls if c[0] != "GET"]

    def _section(self, kind: str, sid: str) -> dict:
        found = next((s for s in self.sections[kind] if s["id"] == sid), None)
        if found is None:
            raise _error(srg.exceptions.NotFoundError, 404, f"Section {sid} not found")
        return found

    def _ordered(self, kind: str) -> list[dict]:
        ranks = {s["id"]: s["rank"] for s in self.sections[kind]}
        return sorted(self.refs[kind], key=lambda r: (ranks[r["section_id"]], r["rank"]))

    def _item(self, kind: str, ref: dict) -> dict:
        section = self._section(kind, ref["section_id"])
        out = {"$type": section["$type"], "id": section["id"], "cursor": f"{section['rank']:012.4f}"}
        if "name" in section:
            out["name"] = section["name"]
        return {
            "$type": "Image" if kind == "Asset" else "Content",
            "id": ref["id"],
            "name": f"frame {ref['id'][-2:]}",
            "cursor": f"{ref['rank']:012.4f}",
            "section": out,
        }

    def section_ids(self, kind: str = "Asset", name: str | None = None) -> list[str]:
        sid = next(
            s["id"] for s in self.sections[kind] if s.get("name") == name or (
                name is None and s["$type"] == "SingleContentSection"
            )
        )
        return [r["id"] for r in self._ordered(kind) if r["section_id"] == sid]

    # -- the fake endpoints ---------------------------------------------
    def __call__(self, workspace_id, method, path, *, json=None, params=None, headers=None):
        self.calls.append((method, path, json))
        if method == "GET" and path == f"/api/v2/contents/{CID}":
            return self._get_v2()
        m = re.fullmatch(rf"/api/v1/contents/{CID}/(Asset|Content)(/.*)?", path)
        assert m, f"unexpected call {method} {path}"
        kind, rest = m.group(1), m.group(2) or ""

        if method == "GET" and rest == "/references":
            if self.private:
                raise _error(srg.exceptions.ForbiddenError, 403, "Forbidden")
            items = [self._item(kind, r) for r in self._ordered(kind)]
            start = int(params.get("cursor") or 0)
            size = params["pageSize"]
            page = items[start : start + size]
            more = start + size < len(items)
            return {"items": page, "nextCursor": str(start + size) if more else None,
                    "hasNext": more, "totalCount": len(items)}
        if method == "POST" and rest == "/sections":
            return self._create_section(kind, json["name"])
        m = re.fullmatch(r"/sections/([^/]+)(/move)?", rest)
        if m:
            return self._section_op(kind, method, m.group(1), bool(m.group(2)), json)
        m = re.fullmatch(r"/([^/]+)/references(?:/(move|[0-9a-f]{24}))?", rest)
        if m:
            return self._ref_op(kind, method, m.group(1), m.group(2), json)
        raise AssertionError(f"unexpected call {method} {path}")

    def _get_v2(self) -> dict:
        categories = []
        for kind in ("Content", "Asset"):
            refs = self._ordered(kind)
            sections = []
            for s in self.sections[kind]:
                row = {"$type": s["$type"], "id": s["id"], "cursor": f"{s['rank']:012.4f}",
                       "isEmpty": not any(r["section_id"] == s["id"] for r in refs)}
                if "name" in s:
                    row["name"] = s["name"]
                sections.append(row)
            categories.append({
                "$type": kind,
                "options": {"expandable": True},
                "references": [self._item(kind, r) for r in refs[:15]],
                "sections": sections,
                "totalCount": len(refs),
                "hasNext": len(refs) > 15,
            })
        return {"id": CID, "hubProfileId": HUB, "categories": categories, "version": 3}

    def _create_section(self, kind: str, name: str) -> dict:
        sections = self.sections[kind]
        if any(s.get("name") == name for s in sections):
            raise _error(srg.exceptions.BadRequestError, 400, "Section name must be unique")
        ordered = sorted(sections, key=lambda s: s["rank"])
        default = ordered[0]["rank"]
        second = ordered[1]["rank"] if len(ordered) > 1 else default + 2
        sid = f"section-{self._next_section}"
        self._next_section += 1
        sections.append({"$type": "Section", "id": sid, "name": name, "rank": (default + second) / 2})
        return {"id": sid}

    def _section_op(self, kind, method, sid, move, body):
        section = self._section(kind, sid)
        if move:
            previous = body.get("previousSectionId")
            if previous is None:
                raise _error(srg.exceptions.BadRequestError, 400, "Cannot move before default")
            ordered = sorted(self.sections[kind], key=lambda s: s["rank"])
            prev = self._section(kind, previous)
            after = [s for s in ordered if s["rank"] > prev["rank"] and s["id"] != sid]
            section["rank"] = (prev["rank"] + after[0]["rank"]) / 2 if after else prev["rank"] + 1
            return None
        if section["$type"] == "SingleContentSection":
            raise _error(srg.exceptions.BadRequestError, 400, "Cannot change the default section")
        if method == "PUT":
            section["name"] = body["name"]
        elif method == "DELETE":
            self.sections[kind].remove(section)
            self.refs[kind] = [r for r in self.refs[kind] if r["section_id"] != sid]
        return None

    def _ref_op(self, kind, method, sid, tail, body):
        self._section(kind, sid)
        in_section = sorted((r for r in self.refs[kind] if r["section_id"] == sid), key=lambda r: r["rank"])
        if method == "POST" and tail is None:
            ids = body["referenceIds"]
            clash = [i for i in ids if any(r["id"] == i for r in self.refs[kind])]
            if clash:
                raise _error(srg.exceptions.ConflictError, 409, f"References {clash} already exist")
            if FOREIGN in ids:
                raise _error(srg.exceptions.ForbiddenError, 403, "No Edit on the source hub")
            unknown = [i for i in ids if i not in self.known]
            if unknown:
                raise _error(srg.exceptions.NotFoundError, 404, f"References {unknown} not found")
            top = in_section[0]["rank"] if in_section else 1000.0
            for offset, ref_id in enumerate(reversed(ids), 1):
                self.refs[kind].append({"id": ref_id, "section_id": sid, "rank": top - offset})
            return None
        if method == "DELETE":
            self.refs[kind] = [r for r in self.refs[kind] if not (r["id"] == tail and r["section_id"] == sid)]
            return None
        if method == "POST" and tail == "move":
            moving = next(r for r in in_section if r["id"] == body["referenceId"])
            others = [r for r in in_section if r is not moving]
            previous = body.get("previousReferenceId")
            if previous is None:
                moving["rank"] = others[0]["rank"] - 1 if others else moving["rank"]
            else:
                idx = next(i for i, r in enumerate(others) if r["id"] == previous)
                nxt = others[idx + 1]["rank"] if idx + 1 < len(others) else others[idx]["rank"] + 2
                moving["rank"] = (others[idx]["rank"] + nxt) / 2
            return None
        raise AssertionError(f"unexpected ref op {method} {tail}")


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> FakeContentHub:
    fake = FakeContentHub()
    monkeypatch.setattr(featured._raw, "call", fake)
    return fake


# --------------------------------------------------------------------------
# set_featured_assets
# --------------------------------------------------------------------------


def test_eight_frames_land_in_a_new_named_section_in_order(hub: FakeContentHub) -> None:
    frames = FRAMES[:8]

    out = featured.set_featured_assets(CID, WS, frames, section_name="Version 1")

    assert out["created_section"] is True
    assert out["section_name"] == "Version 1"
    assert out["ids"] == frames and out["count"] == 8
    assert out["added"] == 8 and out["removed"] == 0 and out["skipped"] == []
    assert out["in_requested_order"] is True
    assert hub.section_ids(name="Version 1") == frames
    # One batch add, no per-item fallback.
    adds = [c for c in hub.writes() if c[1].endswith("/references")]
    assert len(adds) == 1 and adds[0][2] == {"referenceIds": frames}


def test_versions_accumulate_and_the_newest_named_section_comes_first(hub) -> None:
    featured.set_featured_assets(CID, WS, FRAMES[:8], section_name="Version 1")
    featured.set_featured_assets(CID, WS, FRAMES[8:16], section_name="Version 2")

    listing = featured.list_featured_sections(CID, WS)

    names = [s["name"] for s in listing["sections"]]
    assert names == [None, "Version 2", "Version 1"]  # default always first
    by_name = {s["name"]: s for s in listing["sections"]}
    assert by_name["Version 1"]["ids"] == FRAMES[:8]
    assert by_name["Version 2"]["ids"] == FRAMES[8:16]
    assert listing["total"] == 16
    assert all("url" not in item for s in listing["sections"] for item in s["items"])


def test_replace_within_a_section_keeps_other_sections(hub) -> None:
    a, b, c, d, e = FRAMES[:5]
    featured.set_featured_assets(CID, WS, [e], section_name="Version 1")
    featured.set_featured_assets(CID, WS, [a, b, c], section_name="Version 2")

    out = featured.set_featured_assets(CID, WS, [c, a, d], section_name="Version 2")

    assert out["created_section"] is False
    assert out["ids"] == [c, a, d]
    assert out["added"] == 1 and out["removed"] == 1
    assert hub.section_ids(name="Version 1") == [e]


def test_same_call_twice_makes_no_second_write(hub) -> None:
    featured.set_featured_assets(CID, WS, FRAMES[:3], section_name="Version 1")
    writes = len(hub.writes())

    out = featured.set_featured_assets(CID, WS, FRAMES[:3], section_name="Version 1")

    assert len(hub.writes()) == writes
    assert out["added"] == 0 and out["removed"] == 0 and out["ids"] == FRAMES[:3]


def test_item_already_in_another_section_is_skipped_not_moved(hub) -> None:
    a, b, c = FRAMES[:3]
    featured.set_featured_assets(CID, WS, [a, b], section_name="Version 1")

    out = featured.set_featured_assets(CID, WS, [b, c], section_name="Version 2")

    assert out["ids"] == [c]
    assert out["skipped"] == [
        {
            "id": b,
            "reason": "already in section 'Version 1' of this content's Featured Assets; "
            "an item can be in only one section — remove it there first",
        }
    ]
    assert hub.section_ids(name="Version 1") == [a, b]


def test_blocked_ids_are_skipped_and_the_rest_still_go_in_order(hub) -> None:
    a, b, c = FRAMES[:3]

    out = featured.set_featured_assets(
        CID, WS, [a, FOREIGN, b, "not-an-id", MISSING, c, a], section_name="V"
    )

    assert out["ids"] == [a, b, c] and out["in_requested_order"] is True
    reasons = {s["id"]: s["reason"] for s in out["skipped"]}
    assert set(reasons) == {FOREIGN, "not-an-id", MISSING, a}
    assert "403" in reasons[FOREIGN] and "404" in reasons[MISSING]
    assert "24 hex" in reasons["not-an-id"] and "twice" in reasons[a]
    # The invalid id never reached the API.
    assert not any("not-an-id" in str(call) for call in hub.calls)


def test_default_section_when_no_name_and_empty_list_clears(hub) -> None:
    out = featured.set_featured_assets(CID, WS, FRAMES[:2])
    assert out["section_name"] is None and out["created_section"] is False
    assert hub.section_ids() == FRAMES[:2]

    cleared = featured.set_featured_assets(CID, WS, [])

    assert cleared["ids"] == [] and cleared["removed"] == 2
    assert hub.section_ids() == []


def test_section_id_plus_name_renames_the_section(hub) -> None:
    first = featured.set_featured_assets(CID, WS, FRAMES[:1], section_name="Draft")

    out = featured.set_featured_assets(
        CID, WS, FRAMES[:1], section_id=first["section_id"], section_name="Version 1"
    )

    assert out["section_name"] == "Version 1"
    assert hub.section_ids(name="Version 1") == FRAMES[:1]


def test_unknown_section_id_fails_before_any_write(hub) -> None:
    with pytest.raises(ValueError, match="No section nope"):
        featured.set_featured_assets(CID, WS, FRAMES[:1], section_id="nope")
    assert hub.writes() == []


def test_featured_contents_use_the_content_category(hub) -> None:
    out = featured.set_featured_contents(CID, WS, FRAMES[:2], section_name="Chapter 1")

    assert out["featured"] == "Featured Content"
    assert hub.section_ids("Content", "Chapter 1") == FRAMES[:2]
    assert hub.refs["Asset"] == []


def test_private_content_falls_back_to_the_v2_copy(hub) -> None:
    featured.set_featured_assets(CID, WS, FRAMES[:2], section_name="V1")
    hub.private = True

    listing = featured.list_featured_sections(CID, WS)

    assert {s["name"]: s["ids"] for s in listing["sections"]}["V1"] == FRAMES[:2]


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------


def test_reorder_and_delete_named_sections(hub) -> None:
    v1 = featured.set_featured_assets(CID, WS, FRAMES[:1], section_name="Version 1")
    v2 = featured.set_featured_assets(CID, WS, FRAMES[1:2], section_name="Version 2")

    out = featured.reorder_featured_sections(CID, [v1["section_id"], v2["section_id"]], WS)
    assert [s["name"] for s in out["sections"]] == [None, "Version 1", "Version 2"]

    gone = featured.delete_featured_section(CID, v1["section_id"], WS)
    assert gone == {"deleted_section_id": v1["section_id"], "section_name": "Version 1", "unlinked": 1}
    names = [s["name"] for s in featured.list_featured_sections(CID, WS)["sections"]]
    assert names == [None, "Version 2"]


def test_default_section_cannot_be_deleted_or_reordered(hub) -> None:
    with pytest.raises(ValueError, match="cannot be deleted"):
        featured.delete_featured_section(CID, "default-Asset", WS)
    with pytest.raises(ValueError, match="always stays first"):
        featured.reorder_featured_sections(CID, ["default-Asset"], WS)
    assert hub.writes() == []


def test_kind_accepts_friendly_names_and_rejects_others(hub) -> None:
    assert featured.list_featured_sections(CID, WS, kind="featured content")["featured"] == "Featured Content"
    with pytest.raises(ValueError, match='"Asset"'):
        featured.list_featured_sections(CID, WS, kind="Media")


# --------------------------------------------------------------------------
# update_content no longer drops Featured writes silently
# --------------------------------------------------------------------------


@pytest.fixture
def patch_hub(monkeypatch: pytest.MonkeyPatch, hub: FakeContentHub) -> FakeContentHub:
    def call(workspace_id, method, path, *, json=None, params=None, headers=None):
        if method == "PATCH":
            hub.calls.append((method, path, json))
            return {"id": CID, "coverSignedUrl": None, "context": [], "metadataHeaders": None}
        return hub(workspace_id, method, path, json=json, params=params, headers=headers)

    monkeypatch.setattr(contents._raw, "call", call)
    monkeypatch.setattr(
        contents, "get_client", lambda: pytest.fail("hub id should come from the v2 read")
    )
    return hub


def test_update_content_rejects_references_it_cannot_write(patch_hub) -> None:
    category = {
        "$type": "Asset",
        "options": {"expandable": False},
        "references": [{"$type": "Asset", "id": FRAMES[0]}],
        "sections": [{"$type": "SingleContentSection", "name": "Version 1"}],
    }

    with pytest.raises(ValueError, match=r"cannot change \['references', 'sections'\].*set_featured_assets"):
        contents.update_content(CID, WS, categories=[category])

    assert patch_hub.writes() == []  # nothing half-applied


def test_update_content_rejects_bare_id_references_too(patch_hub) -> None:
    with pytest.raises(ValueError, match="set_featured_contents"):
        contents.update_content(
            CID, WS, categories=[{"$type": "Content", "references": [FRAMES[0]]}]
        )


def test_echoed_v2_categories_send_only_options(patch_hub) -> None:
    featured.set_featured_assets(CID, WS, FRAMES[:2], section_name="V1")
    echoed = patch_hub._get_v2()["categories"]
    echoed[1]["options"] = {"expandable": False}

    out = contents.update_content(CID, WS, categories=echoed)

    method, path, body = patch_hub.calls[-1]
    assert method == "PATCH"
    assert body == {
        "categories": [
            {"$type": "Content", "options": {"expandable": True}},
            {"$type": "Asset", "options": {"expandable": False}},
        ]
    }
    assert [list(c)[0] for c in body["categories"]] == ["$type", "$type"]
    assert out["updated_fields"] == ["categories"]


def test_update_content_rejects_unknown_category_keys(patch_hub) -> None:
    with pytest.raises(ValueError, match=r"\['title'\] cannot be written"):
        contents.update_content(CID, WS, categories=[{"$type": "Asset", "title": "x"}])


def test_category_without_options_is_not_reported_as_updated(patch_hub) -> None:
    with pytest.raises(ValueError, match="Nothing to update"):
        contents.update_content(CID, WS, categories=[{"$type": "Asset"}])

    out = contents.update_content(
        CID, WS, name="Carousel", categories=[{"$type": "Asset"}], hub_profile_id=HUB
    )
    assert out["updated_fields"] == ["name"]
