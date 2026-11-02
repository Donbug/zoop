"""`zoop-ai-chat probe-mcp`: the content-free reachability check of the operator's ZOOP MCP server URL. No network: every probe
goes to an in-process `httpx.MockTransport`."""
from __future__ import annotations

import json

import httpx
import pytest

from zoop_ai import chat_cli, chat_probe
from zoop_ai.provider import ProviderError

URL = "https://api.zoop.example/mcp"
ENV = {"ZOOP_AI_CHAT_MCP_SERVER_URL": URL}


def transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_an_unauthenticated_refusal_with_a_bearer_challenge_is_the_zoop_endpoint_answering():
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(401, headers={"WWW-Authenticate": "Bearer"})

    assert chat_probe.probe(ENV, transport(handle)) == {"schemaVersion": "zoop-ai-chat-5", "mcp": "reachable"}
    request = seen[0]
    assert str(request.url) == URL and request.method == "POST"
    assert "authorization" not in request.headers, "the probe carries no grant"
    assert "origin" not in request.headers
    assert json.loads(request.content) == {"jsonrpc": "2.0", "id": 1, "method": "ping"}


@pytest.mark.parametrize("response,reason", [
    (httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}}), "mcp_status_unexpected"),
    (httpx.Response(401), "mcp_status_unexpected"),
    (httpx.Response(401, headers={"WWW-Authenticate": "Bearerish"}), "mcp_status_unexpected"),
    (httpx.Response(404), "mcp_status_unexpected"),
    # A gateway in front answering for a backend it could not reach is a connection failure, not the endpoint answering.
    (httpx.Response(502), "mcp_unavailable"),
    (httpx.Response(503), "mcp_unavailable"),
    (httpx.Response(504), "mcp_unavailable"),
    (httpx.Response(500), "mcp_status_unexpected"),
    (httpx.Response(403), "mcp_status_unexpected"),
    (httpx.Response(302, headers={"Location": "https://elsewhere.example/mcp"}), "mcp_status_unexpected"),
])
def test_anything_but_the_endpoints_own_refusal_is_unreachable(response, reason):
    result = chat_probe.probe(ENV, transport(lambda request: response))
    assert result == {"schemaVersion": "zoop-ai-chat-5", "mcp": "unreachable", "reason": reason}


@pytest.mark.parametrize("error,reason", [
    (httpx.ConnectTimeout("slow"), "mcp_timeout"),
    (httpx.ReadTimeout("slow"), "mcp_timeout"),
    (httpx.ConnectError("refused"), "mcp_connect_failed"),
])
def test_a_transport_failure_is_unreachable_with_its_kind(error, reason):
    def handle(request: httpx.Request) -> httpx.Response:
        raise error

    assert chat_probe.probe(ENV, transport(handle))["reason"] == reason


@pytest.mark.parametrize("env,code", [
    ({}, "mcp_server_url_required"),
    ({"ZOOP_AI_CHAT_MCP_SERVER_URL": "http://api.zoop.example/mcp"}, "mcp_server_url_invalid"),
    ({"ZOOP_AI_CHAT_MCP_SERVER_URL": "https://user@api.zoop.example/mcp"}, "mcp_server_url_invalid"),
])
def test_a_missing_or_invalid_url_is_the_operators_configuration_not_the_servers_health(env, code):
    with pytest.raises(ProviderError) as refused:
        chat_probe.probe(env, transport(lambda request: httpx.Response(401, headers={"WWW-Authenticate": "Bearer"})))
    assert refused.value.code == code


def test_the_cli_exits_by_outcome(monkeypatch, capsys):
    monkeypatch.setattr(chat_probe, "probe", lambda: {"schemaVersion": "zoop-ai-chat-5", "mcp": "reachable"})
    assert chat_cli.main(["probe-mcp"]) == 0
    assert json.loads(capsys.readouterr().out)["mcp"] == "reachable"

    monkeypatch.setattr(chat_probe, "probe", lambda: {"schemaVersion": "zoop-ai-chat-5", "mcp": "unreachable",
                                                      "reason": "mcp_timeout"})
    assert chat_cli.main(["probe-mcp"]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "mcp_timeout"

    def unconfigured():
        raise ProviderError("mcp_server_url_required")

    monkeypatch.setattr(chat_probe, "probe", unconfigured)
    assert chat_cli.main(["probe-mcp"]) == 64
    assert json.loads(capsys.readouterr().out) == {"error": "mcp_server_url_required"}


def test_invoke_still_needs_its_state_dir(capsys):
    assert chat_cli.main(["invoke"]) == 64
    assert json.loads(capsys.readouterr().out) == {"error": "state_dir_invalid"}
