#!/usr/bin/env python3
"""Generate content-free cross-language chat resource fixtures from the installed worker contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from zoop_ai.chat_resources import capabilities
from zoop_ai.contracts import digest

ROOT = Path(__file__).absolute().parents[3]
TARGET = ROOT / "docs/api/fixtures/chat-internal-contracts.json"
PACKAGE_TARGET = ROOT / "ai/service/src/zoop_ai_service/chat_resource_examples.json"
ENV = {"ZOOP_AI_CHAT_ANSWER_MODEL": "gpt-6-luna", "ZOOP_AI_CHAT_AGENT_MODEL": "gpt-6-luna",
       "ZOOP_AI_CHAT_JEV_MODEL": "jev-1.14.0", "ZOOP_AI_CHAT_MCP_SERVER_URL": "https://api.zoop.example/mcp"}
POLICY = {"schemaVersion": "zoop-chat-resource-policy-1", "policyRevision": "expanded-local-2026-11-05.1",
          "maxInputTokens": 512000, "maxOutputTokens": 64000, "maxVisibleOutputTokens": 16000,
          "maxAnswerChars": 48000, "reasoningEffort": "high", "jobTimeoutMs": 1200000,
          "routerProviderTimeoutMs": 15000, "generationProviderTimeoutMs": 600000,
          "verificationProviderTimeoutMs": 45000, "directRetrievalTimeoutMs": 120000, "webSupplementTimeoutMs": 240000}


def generate() -> dict:
    manifest = capabilities(ENV)
    policy_digest = digest(POLICY)
    allocations = {}
    for stage in manifest["runtime"]["stages"]:
        luna = None
        if stage in ("chat-answer", "chat-agent"):
            luna = {key: POLICY[key] for key in ("maxInputTokens", "maxOutputTokens", "maxVisibleOutputTokens", "maxAnswerChars", "reasoningEffort")}
            luna["generatedTextMaxChars"] = POLICY["maxAnswerChars"] - 1024
        for mode in ("replay", "live"):
            resources = {"schemaVersion": "zoop-chat-resource-1", "policyRevision": POLICY["policyRevision"],
                         "policyDigest": policy_digest, "runtimeFingerprint": manifest["runtimeFingerprint"],
                         "providerTimeoutMs": {"chat-router": 15000, "chat-verification": 45000}.get(stage, 600000),
                         "finalizing": stage == "chat-answer", "luna": luna}
            preimage = {"schemaVersion": "zoop-chat-resource-allocation-1", "stage": stage, "mode": mode, "resources": resources}
            allocation_digest = digest(preimage)
            allocations[stage + ":" + mode] = {"preimage": preimage, "resources": {**resources, "allocationDigest": allocation_digest},
                "binding": {"schemaVersion": "zoop-chat-resource-binding-1", "policyDigest": policy_digest,
                            "runtimeFingerprint": manifest["runtimeFingerprint"], "allocationDigest": allocation_digest}}
    return {"policy": POLICY, "policyDigest": policy_digest, "capabilities": manifest, "allocations": allocations}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json.loads(TARGET.read_text(encoding="utf-8"))
    value = generate()
    packaged = {key: {"resources": entry["resources"], "binding": entry["binding"]}
                for key, entry in value["allocations"].items()
                if key in ("chat-router:replay", "chat-answer:replay", "chat-agent:replay")}
    package_text = json.dumps(packaged, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        return 0 if (data.get("resourceContracts") == value and PACKAGE_TARGET.is_file()
                     and PACKAGE_TARGET.read_text(encoding="utf-8") == package_text) else 1
    data["resourceContracts"] = value
    TARGET.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PACKAGE_TARGET.write_text(package_text, encoding="utf-8")
    print("wrote " + str(TARGET.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
