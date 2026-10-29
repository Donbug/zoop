"""Whether the operator's ZOOP MCP server answers at its configured URL (`ZOOP_AI_CHAT_MCP_SERVER_URL`), for the
application's preflight before an agent run (MCP actions contract 3.4).

The probe carries nothing: an MCP `ping` with no grant, so no token and no data leave and nothing is run. The server must refuse
it as unauthenticated (401 with a Bearer challenge): that proves the request reached the ZOOP MCP endpoint itself, through
DNS, TLS and any proxy in front of it, the way the model provider reaches it. Anything else is `unreachable` with a reason:
`mcp_timeout`, `mcp_connect_failed` or `mcp_status_unexpected` (another status, or 401 without the challenge). No redirect is
followed. No model is called and nothing is counted against the live budget.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from . import chat_agent
from .chat_contracts import CHAT_SCHEMA_VERSION
from .provider import ProviderError

PROBE_TIMEOUT = 3.0
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def server_url(env: dict[str, str] | None = None) -> str:
    """The operator's canonical MCP server URL, or ProviderError `mcp_server_url_required` / `mcp_server_url_invalid`."""
    env = os.environ if env is None else env
    configured = env.get("ZOOP_AI_CHAT_MCP_SERVER_URL", "").strip()
    if not configured:
        raise ProviderError("mcp_server_url_required")
    try:
        return chat_agent.server_url(configured)
    except ValueError:
        raise ProviderError("mcp_server_url_invalid") from None


def probe(env: dict[str, str] | None = None, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """`{"schemaVersion", "mcp": "reachable"}` or `{"schemaVersion", "mcp": "unreachable", "reason": <code>}`. Raises
    ProviderError for a missing or invalid URL (the operator's configuration, not the server's health)."""
    url = server_url(env)
    reason = None
    try:
        with httpx.Client(timeout=PROBE_TIMEOUT, follow_redirects=False, transport=transport) as client:
            response = client.post(url, json=PING, headers={"Accept": "application/json, text/event-stream"})
        challenge = response.headers.get("www-authenticate", "").split(None, 1)
        if response.status_code != 401 or not challenge or challenge[0].lower() != "bearer":
            reason = "mcp_status_unexpected"
    except httpx.TimeoutException:
        reason = "mcp_timeout"
    except httpx.TransportError:
        reason = "mcp_connect_failed"
    if reason is None:
        return {"schemaVersion": CHAT_SCHEMA_VERSION, "mcp": "reachable"}
    return {"schemaVersion": CHAT_SCHEMA_VERSION, "mcp": "unreachable", "reason": reason}
