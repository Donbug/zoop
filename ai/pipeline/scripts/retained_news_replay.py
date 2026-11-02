"""Offline-only retained Markdown publication and exact Actor-unsent preparation."""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
for package in ("ai/worker/src", "ai/pipeline/src"):
    sys.path.insert(0, str(ROOT / package))

from zoop_ai_pipeline import private_intake as intake
from zoop_ai_pipeline.extraction_fallback import verify_extracted_page
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, canonical, digest
from zoop_ai_pipeline.private_continuation import immutable_db, pin, prepare_bundle, require_pin, verify_bundle, _rows
from zoop_ai_pipeline.publication_evidence import publication_evidence
import overnight_collect as collector


def offline_only(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("offline_replay_network_forbidden")


class RetainedPackage:
    """A new immutable record package, not a resumable discovery queue."""
    def __init__(self, config):
        root = Path(config.state_dir)
        root.mkdir(mode=0o700)
        self.fd = intake._directory(root)
        binding = intake._binding(config)
        self.data = {"planDigest": digest(binding)}
        intake._publish(self.fd, "PLAN.json", canonical(binding).encode(), immutable=True)

    def exists(self, name):
        try:
            os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    def close(self):
        os.close(self.fd)


def replay(root, output, approval_ref, limit):
    root = root.resolve(strict=True)
    output = output.absolute()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("fresh_replay_namespace_required")
    pins = {name: pin(root / name) for name in ("PLAN.json", "STATE.json", "QUEUE.sqlite3")}
    binding = collector.load(root / "PLAN.json")
    snapshot = collector.load(root / "STATE.json")
    if snapshot["sha256"] != digest(snapshot["state"]) or snapshot["state"]["planDigest"] != digest(binding):
        raise ValueError("retained_state_pin_invalid")
    with immutable_db(root / "QUEUE.sqlite3") as db:
        if db.execute("SELECT digest FROM binding").fetchall() != [(digest(binding),)]:
            raise ValueError("retained_queue_pin_invalid")
        attempts = [(key, row) for key, row in _rows(db, "attempts")
                    if row.get("code") == "article_date_unknown" and row.get("status") == "refused"
                    and row.get("providerOutcome") == "success" and row.get("extractionArtifact")]
        candidates = dict(_rows(db, "candidates"))
    config_value = copy.deepcopy(binding["config"])
    for key in ("fallback", "predecessor", "knownUnsent"):
        config_value.pop(key, None)
    config_value.update(planId="markdown-" + digest(pins)[:40], stateDir=str(output / "state"), operatorApprovalRef=approval_ref)
    config = intake.Config.model_validate(config_value)
    output.mkdir(mode=0o700, parents=True)
    state = RetainedPackage(config)
    outcomes, references = [], []
    try:
        for _, attempt in attempts[:limit]:
            identifier = attempt["key"]
            candidate = candidates[identifier]
            artifact = attempt["extractionArtifact"]
            if artifact["file"] != identifier + ".extraction.json" or (root / (identifier + ".json")).exists():
                raise ValueError("retained_replay_identity_invalid")
            reference = {"path": str(root / artifact["file"]), "sha256": artifact["sha256"]}
            envelope_raw = require_pin(reference).read_bytes()
            envelope = json.loads(envelope_raw)
            page = verify_extracted_page(envelope, allowed_hosts=tuple(config.exact_article_hosts))
            if (page.backend != "deepseek-fetch" or page.requested_url != candidate["url"]
                    or page.provider_receipt.attempt_id != attempt["providerAttemptId"]):
                raise ValueError("retained_replay_provider_mismatch")
            source = next(source for source in config.sources if source.name == candidate["refs"][0]["source"])
            try:
                evidence = publication_evidence(source.name, page, descriptor=source.descriptor)
                publication = intake._publication(evidence["publishedAt"])
                if publication["day"] is None:
                    raise IngestionFailure("article_date_unresolved")
                if not config.from_day <= publication["day"] <= config.through_day:
                    raise IngestionFailure("article_outside_window")
                for ref in candidate["refs"]:
                    if ref.get("published_at") and intake._publication(ref["published_at"])["day"] != publication["day"]:
                        raise IngestionFailure("article_discovery_date_conflict")
                causal = envelope["nativeObservation"]["knownUnsent"]
                if causal is not None:
                    causal_raw = require_pin({"path": str(root / causal["receiptRef"]), "sha256": causal["receiptSha256"]}).read_bytes()
                    intake._publish(state.fd, causal["receiptRef"], causal_raw, immutable=True)
                    references.append({"path": str(root / causal["receiptRef"]), "sha256": causal["receiptSha256"]})
                meta = intake.archives.ArticleMeta(page.metadata.title, evidence["publishedAt"], None, None,
                                                  page.metadata.publisher, source.source_type)
                new_id = "private-news-" + digest([config.plan_id, candidate["url"]])
                item = {"url": candidate["url"], "refs": candidate["refs"], "status": "pending"}
                intake._retain_extracted(config, state, new_id, item, source.name, source, meta, publication, page, [])
                outcomes.append({"oldPrivateId": identifier, "privateId": new_id, "status": "retained",
                                 "publication": publication, "evidenceMethod": evidence["method"]})
            except IngestionFailure as exc:
                outcomes.append({"oldPrivateId": identifier, "status": "unrecovered", "reasonCode": exc.code})
            references.append(reference)
    finally:
        state.close()
    for reference in pins.values():
        require_pin(reference)
    items = collector.private_items(output / "state")
    result = {"schemaVersion": "zoop-retained-markdown-replay-1", "mode": "offline-retained-replay",
              "originalPins": pins, "evidencePins": references, "approvalRef": approval_ref,
              "considered": len(outcomes), "available": len(attempts), "retained": len(items),
              "unrecovered": dict(Counter(row["reasonCode"] for row in outcomes if row["status"] == "unrecovered")),
              "outcomes": outcomes, "privateItems": items, "externalCalls": 0, "originalsModified": False}
    collector.atomic(output / "INDEX.json", result, immutable=True)
    return result


def main(argv=None):
    os.umask(0o077)
    sys.addaudithook(offline_only)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare-unsent")
    for name in ("pending", "actor-proof", "historical-source", "collection-plan", "budget"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--approval-ref", required=True)
    r = sub.add_parser("replay-markdown")
    r.add_argument("--state-dir", type=Path, required=True)
    r.add_argument("--output", type=Path, required=True)
    r.add_argument("--approval-ref", required=True)
    r.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args(argv)
    if args.command == "prepare-unsent":
        result = prepare_bundle(args.pending, args.actor_proof, args.historical_source,
                                args.collection_plan, args.budget, args.approval_ref)
        collector.atomic(args.output, result, immutable=True)
        verify_bundle(pin(args.output))
        print(canonical({"prepared": True, "proof": pin(args.output),
                         "eligible": sum(len(group["members"]) for group in result["groups"]),
                         "refused": len(result["refused"]), "externalCalls": 0}))
    else:
        if not 1 <= args.limit <= 10000:
            parser.error("--limit must be between 1 and 10000")
        result = replay(args.state_dir, args.output, args.approval_ref, args.limit)
        print(canonical({key: result[key] for key in ("considered", "available", "retained", "unrecovered", "externalCalls", "originalsModified")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
