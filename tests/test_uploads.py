"""create_upload / complete_upload / set_cover(s) / list_drive_files (SRGDEV-741).

The generated upload script is exercised for real (bash + curl + dd) against a
throwaway local HTTP server that plays the storage role.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import shutil
import subprocess
import threading
from types import SimpleNamespace

import pytest
import srg.exceptions

from srg_mcp import uploads

WS = "ws-1"
HUB = "65f0000000000000000000aa"


class _Api:
    """Stands in for srg_mcp._raw.call; answers by (method, path)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.routes: dict = {}

    def __call__(self, workspace_id, method, path, *, json=None, params=None, headers=None):
        self.calls.append({"method": method, "path": path, "json": json, "params": params})
        answer = self.routes.get((method, path))
        if callable(answer):
            return answer(json)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> _Api:
    fake = _Api()
    monkeypatch.setattr(uploads._raw, "call", fake)
    monkeypatch.setattr(uploads.time, "sleep", lambda s: None)
    return fake


def _http_error(cls, status: int, detail: str):
    response = SimpleNamespace(status_code=status)
    return cls({"detail": detail}, response)


# --------------------------------------------------------------------------
# create_upload
# --------------------------------------------------------------------------


def test_create_upload_registers_files_with_type_first(api: _Api) -> None:
    api.routes[("POST", "/api/v1/assets/batch")] = lambda body: [
        {"$type": a["$type"], "id": f"asset-{i}", "uploadId": f"up-{i}", "urls": [f"https://s3/p{i}"]}
        for i, a in enumerate(body["assets"], 1)
    ]

    out = uploads.create_upload(
        HUB,
        WS,
        files=[
            {"path": "/Users/me/Covers A/Reel 01.jpg", "size": 312345, "width": 1080, "height": 1920},
            {"path": "/Users/me/clip.mov", "size": 12_000_000},
        ],
    )

    body = api.calls[0]["json"]
    assert body["hubProfileId"] == HUB
    image, video = body["assets"]
    assert list(image)[0] == "$type"  # discriminator must come first for .NET
    assert image == {
        "$type": "Image",
        "name": "Reel 01.jpg",
        "extension": "jpg",
        "memorySizeInBytes": 312345,
        "uploadPartSizeInBytes": 5 * 1024 * 1024,
        "readOnly": False,
        "width": 1080.0,
        "height": 1920.0,
    }
    assert video["$type"] == "Video" and "width" not in video
    assert [u["asset_id"] for u in out["uploads"]] == ["asset-1", "asset-2"]
    # Paths with spaces are shell-quoted in the script; URLs are embedded.
    assert "'/Users/me/Covers A/Reel 01.jpg'" in out["script"]
    assert "https://s3/p1" in out["script"] and "complete_upload" in out["next"]


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"path": "/x/a.jpg", "width": 10, "height": 10}, "size"),
        ({"path": "/x/a.jpg", "size": 10}, "width"),
        ({"path": "/x/noext", "size": 10}, "extension"),
        ({"size": 10}, "path"),
        ({"path": "/x/a.bin", "size": 10, "type": "Folder"}, "type"),
    ],
)
def test_create_upload_validates_before_any_call(api: _Api, spec: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        uploads.create_upload(HUB, WS, files=[spec])
    assert api.calls == []


def test_create_upload_urls_mode_lists_parts(api: _Api) -> None:
    size = 12 * 1024 * 1024 + 1  # -> two parts of 6 MiB (+1 byte), last one shorter
    api.routes[("POST", "/api/v1/assets/batch")] = lambda body: [
        {"$type": "Video", "id": "a1", "uploadId": "u1", "urls": ["https://s3/1", "https://s3/2"]}
    ]

    out = uploads.create_upload(HUB, WS, files=[{"path": "v.mp4", "size": size}], output="urls")

    assert "script" not in out
    row = out["uploads"][0]
    part_size = api.calls[0]["json"]["assets"][0]["uploadPartSizeInBytes"]
    assert row["part_size"] == part_size == 6 * 1024 * 1024 + 1
    assert [p["length"] for p in row["parts"]] == [part_size, size - part_size]
    assert [p["part_number"] for p in row["parts"]] == [1, 2]


@pytest.mark.parametrize(
    "size",
    [1, 5 * 1024**2, 5 * 1024**2 + 1, 99 * 1024**2, 300 * 1024**2, 3 * 1024**3, 60 * 1024**3],
)
def test_part_size_matches_sdk_and_clients(size: int) -> None:
    from srg._upload_multipart import calculate_upload_part_size

    assert uploads._part_size(size) == calculate_upload_part_size(size)


def test_create_upload_splits_batches_of_100(api: _Api) -> None:
    api.routes[("POST", "/api/v1/assets/batch")] = lambda body: [
        {"$type": "File", "id": f"a{i}", "uploadId": f"u{i}", "urls": ["https://s3/x"]}
        for i, _ in enumerate(body["assets"])
    ]
    files = [{"path": f"/f/{i}.pdf", "size": 100} for i in range(150)]

    out = uploads.create_upload(HUB, WS, files=files)

    assert [len(c["json"]["assets"]) for c in api.calls] == [100, 50]
    assert len(out["uploads"]) == 150


# --------------------------------------------------------------------------
# The generated script, for real
# --------------------------------------------------------------------------


class _Storage(http.server.BaseHTTPRequestHandler):
    received: dict[str, bytes] = {}

    def do_PUT(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers["Content-Length"])
        data = self.rfile.read(length)
        _Storage.received[self.path] = data
        self.send_response(200)
        self.send_header("ETag", f'"{hashlib.md5(data).hexdigest()}"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args) -> None:  # silence
        pass


@pytest.mark.skipif(
    not all(shutil.which(t) for t in ("bash", "curl", "dd")),
    reason="needs bash, curl and dd",
)
def test_generated_script_uploads_parts_and_prints_complete_json(tmp_path) -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Storage)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    _Storage.received = {}
    try:
        small = tmp_path / "Reel 01.jpg"
        small.write_bytes(b"\xff\xd8\xff" + b"a" * 100)
        big = tmp_path / "clip.mp4"
        big.write_bytes(bytes(range(256)) * 40)  # 10240 bytes -> 3 parts of 4096
        entries = [
            {"local_path": str(small), "asset_id": "a1", "upload_id": "u1", "part_size": 4096,
             "urls": [f"{base}/a1?part=1&X-Amz-Signature=s"]},
            {"local_path": str(big), "asset_id": "a2", "upload_id": "u/2+x=", "part_size": 4096,
             "urls": [f"{base}/a2?part={n}" for n in (1, 2, 3)]},
        ]
        script = tmp_path / "up.sh"
        script.write_text(uploads._script(entries))

        run = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60)

        assert run.returncode == 0, run.stderr
        printed = json.loads(run.stdout.strip().splitlines()[-1])
        assert printed == [
            {"asset_id": "a1", "upload_id": "u1", "parts": [
                {"part_number": 1, "etag": hashlib.md5(small.read_bytes()).hexdigest()}]},
            {"asset_id": "a2", "upload_id": "u/2+x=", "parts": [
                {"part_number": n, "etag": hashlib.md5(big.read_bytes()[(n - 1) * 4096:n * 4096]).hexdigest()}
                for n in (1, 2, 3)]},
        ]
        reassembled = b"".join(_Storage.received[f"/a2?part={n}"] for n in (1, 2, 3))
        assert reassembled == big.read_bytes()
    finally:
        server.shutdown()


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
def test_generated_script_fails_loudly_for_a_missing_file(tmp_path) -> None:
    entries = [{"local_path": str(tmp_path / "missing.jpg"), "asset_id": "a1", "upload_id": "u1",
                "part_size": 4096, "urls": ["http://127.0.0.1:9/never"]}]
    script = tmp_path / "up.sh"
    script.write_text(uploads._script(entries))

    run = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60)

    assert run.returncode == 1
    assert "no such file" in run.stderr
    assert run.stdout.strip() == "[]"


# --------------------------------------------------------------------------
# complete_upload
# --------------------------------------------------------------------------


def test_complete_upload_sends_int_part_numbers_and_bare_etags(api: _Api) -> None:
    api.routes[("GET", "/api/v1/assets/a1")] = {
        "$type": "Image", "name": "Reel 01.jpg", "memorySizeInBytes": 10, "width": 1080, "height": 1920,
    }

    out = uploads.complete_upload(
        WS, uploads=[{"asset_id": "a1", "upload_id": "u1", "parts": [
            {"part_number": "2", "etag": '"e2"'}, {"part_number": 1, "etag": "e1"}]}]
    )

    complete = api.calls[0]
    assert complete["path"] == "/api/v1/files/upload/complete"
    assert complete["json"] == {
        "nodeId": "a1",
        "uploadId": "u1",
        "partTags": [{"partNumber": 1, "eTag": "e1"}, {"partNumber": 2, "eTag": "e2"}],
    }
    assert out["completed"] == 1 and out["failed"] == 0
    assert out["assets"][0] == {
        "asset_id": "a1", "status": "completed", "name": "Reel 01.jpg", "type": "Image",
        "size": 10, "width": 1080, "height": 1920,
    }


def test_complete_upload_is_idempotent_and_reports_failures(api: _Api) -> None:
    api.routes[("POST", "/api/v1/files/upload/complete")] = lambda body: (
        (_ for _ in ()).throw(_http_error(srg.exceptions.ConflictError, 409, "done"))
        if body["nodeId"] == "a1"
        else (_ for _ in ()).throw(_http_error(srg.exceptions.ServerError, 500, "boom"))
    )
    api.routes[("GET", "/api/v1/assets/a1")] = {"$type": "Image", "name": "x"}

    out = uploads.complete_upload(
        WS,
        uploads=[
            {"asset_id": "a1", "upload_id": "u1", "parts": [{"part_number": 1, "etag": "e"}]},
            {"asset_id": "a2", "upload_id": "u2", "parts": [{"part_number": 1, "etag": "e"}]},
            {"asset_id": "a3"},
        ],
    )

    statuses = [r["status"] for r in out["assets"]]
    assert statuses == ["already_completed", "failed", "failed"]
    assert out["completed"] == 1 and out["failed"] == 2


# --------------------------------------------------------------------------
# set_cover / set_covers
# --------------------------------------------------------------------------


def test_set_cover_waits_out_still_uploading(api: _Api) -> None:
    attempts = {"n": 0}

    def cover(body):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _http_error(
                srg.exceptions.BadRequestError, 400,
                "The selected image is still uploading. Try again once it finishes.",
            )
        return None

    api.routes[("POST", "/api/v1/contents/c1/cover/from-asset")] = cover

    out = uploads.set_cover("c1", "img-1", WS, hub_profile_id=HUB)

    assert out == {"content_id": "c1", "asset_id": "img-1", "status": "cover_set"}
    assert attempts["n"] == 3
    assert api.calls[-1]["json"] == {"coverAssetId": "img-1"}
    assert api.calls[-1]["params"] == {"hubProfileId": HUB}


def test_set_cover_does_not_retry_other_errors(api: _Api) -> None:
    api.routes[("POST", "/api/v1/contents/c1/cover/from-asset")] = _http_error(
        srg.exceptions.BadRequestError, 400, "Asset with CoverAssetId: x is not an image."
    )
    with pytest.raises(srg.exceptions.BadRequestError):
        uploads.set_cover("c1", "x", WS, hub_profile_id=HUB)
    assert len(api.calls) == 1


def test_set_covers_continues_past_failures(api: _Api, monkeypatch) -> None:
    api.routes[("POST", "/api/v1/contents/c1/cover/from-asset")] = None
    api.routes[("POST", "/api/v1/contents/c2/cover/from-asset")] = _http_error(
        srg.exceptions.NotFoundError, 404, "Content not found"
    )
    lookups: list[str] = []
    monkeypatch.setattr(uploads, "_hub_of", lambda cid, ws: lookups.append(cid) or HUB)

    out = uploads.set_covers(
        [{"content_id": "c1", "asset_id": "i1"}, {"content_id": "c2", "asset_id": "i2"},
         {"content_id": "c3"}],
        WS,
    )

    assert [r["status"] for r in out["results"]] == ["cover_set", "failed", "failed"]
    assert out["set"] == 1 and out["failed"] == 2
    assert sorted(lookups) == ["c1", "c2"]  # hub resolved per item when not passed


def test_set_covers_skips_lookups_when_hub_is_given(api: _Api, monkeypatch) -> None:
    api.routes[("POST", "/api/v1/contents/c1/cover/from-asset")] = None
    monkeypatch.setattr(uploads, "_hub_of", lambda cid, ws: pytest.fail("no lookup expected"))

    out = uploads.set_covers([{"content_id": "c1", "asset_id": "i1"}], WS, hub_profile_id=HUB)

    assert out["set"] == 1


# --------------------------------------------------------------------------
# list_drive_files
# --------------------------------------------------------------------------


def test_list_drive_files_pages_compact_rows(api: _Api) -> None:
    api.routes[("POST", f"/api/v1/assets/{HUB}/filter/")] = {
        "items": [
            {"$type": "Image", "id": "i1", "name": "Reel 01.jpg", "extension": "jpg",
             "memorySizeInBytes": 312345, "width": 1080, "height": 1920,
             "url": "https://signed/long", "cover": {"urls": {}}},
            {"$type": "Video", "id": "v1", "name": "clip.mov", "extension": "mov",
             "memorySizeInBytes": 9, "status": "Ready"},
        ],
        "cursor": "next-page",
    }

    out = uploads.list_drive_files(HUB, WS, types=["Image", "Video"])

    assert api.calls[0]["json"]["type"] == ["Image", "Video"]
    assert out == {
        "items": [
            {"id": "i1", "name": "Reel 01.jpg", "type": "Image", "extension": "jpg",
             "size": 312345, "width": 1080, "height": 1920},
            {"id": "v1", "name": "clip.mov", "type": "Video", "extension": "mov",
             "size": 9, "status": "Ready"},
        ],
        "cursor": "next-page",
    }


def test_list_drive_files_search_and_type_validation(api: _Api) -> None:
    api.routes[("POST", f"/api/v1/assets/{HUB}/search")] = [{"$type": "Image", "id": "i1", "name": "Reel 01.jpg"}]

    out = uploads.list_drive_files(HUB, WS, search="Reel")

    assert api.calls[0]["json"] == {"search": "Reel", "type": []}
    assert out["items"][0]["id"] == "i1" and out["cursor"] is None
    with pytest.raises(ValueError, match="Unknown type"):
        uploads.list_drive_files(HUB, WS, types=["Folder"])


def test_set_cover_sends_if_match_when_expected_version_given(api: _Api) -> None:
    api.routes[("POST", "/api/v1/contents/c1/cover/from-asset")] = None
    seen: list = []
    original = api.__call__

    def spy(workspace_id, method, path, *, json=None, params=None, headers=None):
        seen.append(headers)
        return original(workspace_id, method, path, json=json, params=params, headers=headers)

    uploads._raw.call = spy  # monkeypatched back by the fixture teardown
    uploads.set_cover("c1", "img-1", WS, hub_profile_id=HUB, expected_version=3)
    uploads.set_cover("c1", "img-1", WS, hub_profile_id=HUB)

    assert seen == [{"If-Match": '"3"'}, None]
