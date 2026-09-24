"""Raw calls to the SRG+ REST API through the SDK's authenticated client.

Tools use this for endpoints the pinned SDK release does not wrap yet (or
wraps unsafely), so a connector fix never has to wait for an SDK publish.
Errors surface as the SDK's typed ``srg.exceptions`` (401/404/409/...), which
the hosted server's tool-error wrapper turns into one actionable line.
"""

from __future__ import annotations

from typing import Any

from srg_mcp._client import get_client


def http(workspace_id: str) -> Any:  # noqa: ANN401 - SDK internal client type
    """The SDK's authenticated sync HTTP client for this workspace's key."""
    return get_client().contents._get_http(workspace_id)


def call(
    workspace_id: str,
    method: str,
    path: str,
    *,
    json: Any = None,  # noqa: ANN401
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:  # noqa: ANN401
    """Send one request with the workspace's key; return the parsed JSON body.

    Returns ``None`` for 204/empty responses; raises ``srg.exceptions`` errors
    for 4xx/5xx exactly like the SDK's own resource methods.
    """
    client = http(workspace_id)
    response = client._client.request(
        method, path, json=json, params=params, headers=headers
    )
    return client._process(response)
