"""Shared pytest fixtures for the test suite.

The Starlette app's lifespan starts a ``StreamableHTTPSessionManager``
context, and that manager refuses to be re-entered (``can only be called
once per instance``). When two test modules each defined their own
session-scoped ``_lifespan`` fixture pytest still treated them as
independent, so the second module's fixture tried to call ``.run()`` on
the same already-started manager and the whole module failed to collect.

Hoisting the lifespan + client fixtures into ``conftest.py`` gives every
module a single shared instance — the manager is started once for the
entire pytest run and torn down at the end.
"""

from __future__ import annotations

import asyncio
import base64
import os

import httpx
import pytest_asyncio

# Set OAuth env defaults BEFORE the app is imported so the random-fallback
# warning doesn't fire and signing keys are stable across the suite.
os.environ.setdefault("OAUTH_ISSUER", "http://localhost:8090")
os.environ.setdefault(
    "OAUTH_CLIENT_REGISTRATION_KEY",
    "test-client-reg-key-for-pytest-only-please",
)
os.environ.setdefault(
    "OAUTH_TOKEN_SIGNING_KEY",
    "test-token-signing-key-for-pytest-only-please",
)
os.environ.setdefault(
    "OAUTH_API_KEY_ENCRYPTION_KEY",
    base64.urlsafe_b64encode(b"x" * 32).decode(),
)


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def _lifespan():
    """Run the Starlette lifespan once for the entire pytest session."""
    from srg_mcp.serve.main import app  # imported lazily so env defaults apply

    state = {"shutdown": False, "events": [], "startup_sent": False}

    async def receive():
        if not state["startup_sent"]:
            state["startup_sent"] = True
            return {"type": "lifespan.startup"}
        while not state["shutdown"]:
            await asyncio.sleep(0.01)
        return {"type": "lifespan.shutdown"}

    async def send(msg):
        state["events"].append(msg)

    lifespan_task = asyncio.create_task(app({"type": "lifespan"}, receive, send))

    for _ in range(500):
        if any(e["type"] == "lifespan.startup.complete" for e in state["events"]):
            break
        if any(e["type"] == "lifespan.startup.failed" for e in state["events"]):
            raise RuntimeError(f"App lifespan startup failed: {state['events']}")
        await asyncio.sleep(0.01)
    else:
        raise RuntimeError("App lifespan did not complete startup in time")

    try:
        yield
    finally:
        state["shutdown"] = True
        try:
            await asyncio.wait_for(lifespan_task, timeout=2)
        except Exception:
            lifespan_task.cancel()


@pytest_asyncio.fixture
async def client(_lifespan):
    """An async httpx client backed by the ASGI app — shares one lifespan."""
    from srg_mcp.serve.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as c:
        yield c
