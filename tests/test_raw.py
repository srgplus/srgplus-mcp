"""_raw.call goes through the SDK's real authenticated client (no mocks of it)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import srg.exceptions
from srg._http import SyncHTTPClient

from srg_mcp import _raw


def _client_with(handler) -> SyncHTTPClient:
    client = SyncHTTPClient(
        api_key="srgplus_test_key", base_url="https://gateway.test", timeout=5
    )
    client._client = httpx.Client(
        base_url="https://gateway.test",
        headers=client._default_headers("srgplus_test_key"),
        transport=httpx.MockTransport(handler),
    )
    return client


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch):
    seen: list[httpx.Request] = []
    state = {"status": 200, "body": {"id": "c1"}}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(state["status"], json=state["body"])

    client = _client_with(handler)
    fake = SimpleNamespace(contents=SimpleNamespace(_get_http=lambda ws: client))
    monkeypatch.setattr(_raw, "get_client", lambda: fake)
    return seen, state


def test_patch_goes_out_with_auth_query_and_json(wire) -> None:
    seen, _ = wire

    out = _raw.call(
        "ws1",
        "PATCH",
        "/api/v1/contents/c1",
        json={"context": []},
        params={"hubProfileId": "h1"},
        headers={"If-Match": '"7"'},
    )

    assert out == {"id": "c1"}
    request = seen[0]
    assert request.method == "PATCH"
    assert request.url.path == "/api/v1/contents/c1"
    assert request.url.params["hubProfileId"] == "h1"
    assert request.headers["Authorization"] == "Bearer srgplus_test_key"
    assert request.headers["If-Match"] == '"7"'
    assert json.loads(request.content) == {"context": []}


def test_errors_surface_as_sdk_exceptions(wire) -> None:
    _, state = wire
    state["status"], state["body"] = 409, {"title": "Conflict"}

    with pytest.raises(srg.exceptions.ConflictError):
        _raw.call("ws1", "PATCH", "/api/v1/contents/c1", json={})
