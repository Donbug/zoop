"""Synthetic Java-owned permits used through the real worker invocation boundary."""
import pytest

from zoop_ai.chat_resources import capabilities
from zoop_ai.contracts import digest

PUBLIC = {"ZOOP_AI_CHAT_ANSWER_MODEL": "gpt-6-luna", "ZOOP_AI_CHAT_AGENT_MODEL": "gpt-6-luna",
          "ZOOP_AI_CHAT_JEV_MODEL": "jev-1.14.0", "ZOOP_AI_CHAT_MCP_SERVER_URL": "https://api.zoop.example/mcp"}
POLICY = {"schemaVersion": "zoop-chat-resource-policy-1", "policyRevision": "expanded-local-2026-11-05.1",
          "maxInputTokens": 512000, "maxOutputTokens": 64000, "maxVisibleOutputTokens": 16000,
          "maxAnswerChars": 48000, "reasoningEffort": "high", "jobTimeoutMs": 1200000,
          "routerProviderTimeoutMs": 15000, "generationProviderTimeoutMs": 600000,
          "verificationProviderTimeoutMs": 45000, "directRetrievalTimeoutMs": 120000,
          "webSupplementTimeoutMs": 240000}


@pytest.fixture(autouse=True)
def configured_chat(monkeypatch):
    for name, value in PUBLIC.items():
        monkeypatch.setenv(name, value)
    for name in ("ZOOP_AI_CHAT_ANSWER_REASONING_EFFORT", "ZOOP_AI_CHAT_AGENT_REASONING_EFFORT"):
        monkeypatch.delenv(name, raising=False)


def resources(stage, mode="live", *, env=None, finalizing=None, **luna_changes):
    luna = None
    policy = dict(POLICY)
    if stage in ("chat-answer", "chat-agent"):
        luna = {key: policy[key] for key in ("maxInputTokens", "maxOutputTokens", "maxVisibleOutputTokens", "maxAnswerChars", "reasoningEffort")}
        luna["generatedTextMaxChars"] = 46976
        luna.update(luna_changes)
        for key in policy.keys() & luna.keys():
            policy[key] = luna[key]
    value = {"schemaVersion": "zoop-chat-resource-1", "policyRevision": policy["policyRevision"],
             "policyDigest": digest(policy), "runtimeFingerprint": capabilities(PUBLIC if env is None else env)["runtimeFingerprint"],
             "providerTimeoutMs": {"chat-router": 15000, "chat-verification": 45000}.get(stage, 600000),
             "finalizing": stage == "chat-answer" if finalizing is None else finalizing, "luna": luna}
    value["allocationDigest"] = digest({"schemaVersion": "zoop-chat-resource-allocation-1", "stage": stage, "mode": mode, "resources": value})
    return value
