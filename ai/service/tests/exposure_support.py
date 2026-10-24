"""Synthetic identity-only reports and opt-in environment for both scripted and installed-CLI tests."""
from handoff_support import HANDOFF, HANDOFF_VARS, HandoffWorkspace, export_entry
from zoop_ai_service.handoff_doc import example_bundle, pins
from zoop_ai_service.handoff_exposure_wire import BASIS, CONSISTENCY, EFFECT, NOT_COVERED

URL = "/internal/v1/graph-handoffs/exposure"
SCHEMA = "zoop-handoff-exposure-1"


def query(changed=None, ids=None):
    return {"schemaVersion": SCHEMA, "handoffIds": ids or [HANDOFF], "changed": changed or {"kind": "source", "sourceId": "synthetic-source"}}


def exposure_env(ws, command=None, *, only=False):
    env = {"ZOOP_AI_SERVICE_HANDOFF_EXPOSURE_COMMAND": str(command or ws.command),
           "ZOOP_AI_HANDOFF_EXPOSURE_STATE_DIR": str(ws.handoff_state),
           "ZOOP_AI_HANDOFF_EXPOSURE_EXTRACTION_STATE_DIR": str(ws.extraction_state),
           "ZOOP_AI_HANDOFF_EXPOSURE_INGESTION_STATE_DIR": str(ws.ingestion_state),
           "ZOOP_AI_SERVICE_HANDOFF_EXPOSURE_EXPORTS": str(ws.exports)}
    if only:
        env.update({name: None for name in HANDOFF_VARS})
    return env


def report(request=None):
    request = request or query()
    bundle = example_bundle()
    fixed = pins(bundle)
    relation = request["changed"]["kind"] == "s3-relation"
    cause = "relation-retraction" if relation else "source-change"
    return {"schemaVersion": SCHEMA, "changed": request["changed"], "cause": cause,
            "identity": {"boundInSelection": True, "recordedInIngestion": None if relation else True},
            "scope": {"selection": "explicit", "handoffIds": sorted(request["handoffIds"]), "notCovered": list(NOT_COVERED)},
            "basis": BASIS[cause], "consistency": CONSISTENCY, "effect": EFFECT, "usage": {"providerCalls": 0, "modelCalls": 0},
            "handoffs": [{"handoffId": ident, "bundleSchema": "zoop-graph-handoff-bundle-7", "manifestDigest": fixed["manifestDigest"],
                          "bundleDigest": fixed["bundleDigest"], "contentDigest": fixed["contentDigest"], "bound": True, "exposed": True,
                          "articles": [], "evidenceIds": [], "issues": [{"id": "issue:synthetic", "reasons": ["involvement-lost"]}],
                          "relations": [{"id": "edge:synthetic", "type": "INVOLVES", "reasons": ["source-relation" if relation else "upstream-input"]}],
                          "counts": {"articles": 0, "evidence": 0, "issues": 1, "relations": 1}} for ident in sorted(request["handoffIds"])]}


def workspace(root, **kwargs):
    ws = HandoffWorkspace(root, exports=[export_entry(principal="alpha")], **kwargs)
    ws.credentials.scopes["viewer"] = ["handoff.exposure"]
    ws.script({"output": report()})
    return ws
