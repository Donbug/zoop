#!/usr/bin/env python3
"""Replay stored Jev observations under other decision thresholds and rule R1 (no model call, no database).

    uv run python scripts/simulate_thresholds.py [inspect.json] [--json OUT]

Input is an ``inspect()``-shaped payload (default ``fixtures/poc-real-inspect.json``). Every active candidate's
stored ``validation.trace.observations`` are folded into verdicts exactly as ``investmate.jev.parse_response``
does (``investmate.decision.classify_observation`` per check, REJECT > HOLD > ALLOW per target). The fold is
first checked against the verdicts the ledger recorded at the policy of record; any mismatch aborts.
Rule R1 is then evaluated by the production ``zoop_bff.review_rules.r1_effect`` on rows carrying the
re-folded verdicts. The numbers are what the *same stored model answers* would decide, not accuracy against
a human ground truth.
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import sys
from pathlib import Path
from typing import Any

from investmate.decision import classify_observation
from investmate.domain import DecisionPolicy, VerificationObservation

from zoop_bff.review_rules import r1_effect

ROOT = Path(__file__).resolve().parents[1]
SUPPORT_GRID = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
CONTRADICTION_GRID = (0.05, 0.10, 0.15, 0.20)
REVIEW = "Support or contradiction probability requires review: "


def fold(row: dict[str, Any], policy: DecisionPolicy) -> tuple[dict[str, tuple[str, list[str]]], dict[str, str]]:
    """({target: (decision, held checks)}, {optional field: decision}) as jev.parse_response folds them."""
    by_target: dict[str, list[VerificationObservation]] = collections.OrderedDict()
    for raw in row["validation"]["trace"]["observations"]:
        by_target.setdefault(raw["target"], []).append(VerificationObservation.model_validate(raw))
    verdicts: dict[str, tuple[str, list[str]]] = {}
    fields: dict[str, str] = {}
    for target, checks in by_target.items():
        results = [classify_observation(check, policy) for check in checks]
        held = [c.check for c, r in zip(checks, results, strict=True) if r == "HOLD"]
        decision = "REJECT" if "REJECT" in results else "HOLD" if "HOLD" in results else "ALLOW"
        if target.startswith("field:"):
            fields[target.removeprefix("field:")] = decision
        else:
            verdicts[target] = (decision, held if decision == "HOLD" else [])
    withheld = {f for f, d in fields.items() if d != "ALLOW"}
    for relation in row["candidate"]["relations"]:
        decision, _ = verdicts.get(relation["relation_id"], ("", []))
        structural = relation["relation_type"] == "STRUCTURALLY_RELATED_TO" and any(
            ("countries" in withheld and b.get("countries"))
            or ("event_time" in withheld and (b.get("valid_from") or b.get("valid_until")))
            for b in relation.get("basis") or []
        )
        if decision == "ALLOW" and (
            (relation["relation_type"] == "FOLLOWS" and withheld & {"event_time", "period"}) or structural
        ):
            verdicts[relation["relation_id"]] = ("HOLD", ["Required optional field was withheld."])
    return verdicts, fields


def recorded(row: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    validation = row["validation"]
    return (
        {v["target"]: v["decision"] for v in validation["verdicts"]},
        {f["field"]: f["decision"] for f in validation.get("field_verdicts") or []},
    )


def with_verdicts(row: dict[str, Any], verdicts: dict[str, tuple[str, list[str]]], fields: dict[str, str]) -> dict[str, Any]:
    """The row as the ledger would have recorded it under the folded verdicts (reasons in the PoC wording)."""
    out = copy.deepcopy(row)
    out["status"] = verdicts["issue"][0]
    out["validation"]["verdicts"] = [
        {
            "target": target,
            "decision": decision,
            "reason": (held[0] if held and held[0].endswith(".") else REVIEW + ", ".join(held))
            if decision == "HOLD"
            else "Source contradiction probability meets rejection policy."
            if decision == "REJECT"
            else "Every required check satisfies the configured probability policy.",
        }
        for target, (decision, held) in verdicts.items()
    ]
    out["validation"]["field_verdicts"] = [{"field": f, "decision": d, "reason": ""} for f, d in fields.items()]
    return out


def outcome(row: dict[str, Any], support_min: float, contradiction_max: float, reject_min: float = 0.90) -> str:
    """ALLOW | R1 | HOLD | REJECT for one candidate under the thresholds (R1 = published by rule R1)."""
    policy = DecisionPolicy(support_min=support_min, contradiction_max=contradiction_max, reject_min=reject_min)
    verdicts, fields = fold(row, policy)
    status = verdicts["issue"][0]
    if status == "HOLD" and r1_effect(with_verdicts(row, verdicts, fields)) is not None:
        return "R1"
    return status


def causes(row: dict[str, Any]) -> set[str]:
    """Check names (index stripped) behind the recorded non-ALLOW verdicts of a HOLD candidate."""
    names: set[str] = set()
    for verdict in row["validation"]["verdicts"]:
        if verdict["decision"] == "ALLOW":
            continue
        reason = verdict["reason"]
        if reason.startswith(REVIEW):
            names |= {c.split(":")[0].strip() for c in reason[len(REVIEW) :].split(" Numerical")[0].rstrip(".").split(",")}
        else:
            names.add(reason)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("inspect", nargs="?", type=Path, default=ROOT / "fixtures" / "poc-real-inspect.json")
    parser.add_argument("--json", type=Path, help="also write the full result (grid, cause counts, released candidates)")
    args = parser.parse_args()

    payload = json.loads(args.inspect.read_text(encoding="utf-8"))
    rows = [r for r in payload["candidates"] if r.get("active") and (r.get("validation") or {}).get("trace")]
    record = rows[0]["validation"]["trace"]["decision_policy"]
    of_record = DecisionPolicy(**record)
    for row in rows:
        verdicts, fields = fold(row, of_record)
        if ({t: d for t, (d, _) in verdicts.items()}, fields) != recorded(row):
            print(f"replay differs from the recorded verdicts: {row['candidate']['candidate_id']}", file=sys.stderr)
            return 1
    print(f"{args.inspect.name}: {len(rows)} active candidates with stored observations; replay at the policy of record {record} reproduces every recorded verdict")

    now = {r["candidate"]["candidate_id"]: outcome(r, record["support_min"], record["contradiction_max"], record["reject_min"]) for r in rows}
    held = [r for r in rows if r["status"] == "HOLD"]
    cause_counts = collections.Counter(c for r in held for c in causes(r))
    only_roles = sum(1 for r in held if now[r["candidate"]["candidate_id"]] == "R1")
    print(f"\nAt the policy of record: {collections.Counter(r['status'] for r in rows)}; HOLD candidates by cause (a candidate can have several):")
    for name, n in cause_counts.most_common():
        print(f"  {name}: {n}")
    print(f"  role checks alone (rule R1 applies): {only_roles}")

    print("\n| support_min | contradiction_max | ALLOW/HOLD/REJECT | with R1: ALLOW+R1 / HOLD / REJECT | released beyond now+R1 |")
    print("|---|---|---|---|---|")
    grid: list[dict[str, Any]] = []
    released: dict[str, list[tuple[float, float]]] = {}
    for c in CONTRADICTION_GRID:
        for s in SUPPORT_GRID:
            result = {r["candidate"]["candidate_id"]: outcome(r, s, c) for r in rows}
            count = collections.Counter(result.values())
            extra = [i for i, o in result.items() if o in ("ALLOW", "R1") and now[i] not in ("ALLOW", "R1")]
            lost = [i for i, o in result.items() if o not in ("ALLOW", "R1") and now[i] in ("ALLOW", "R1")]
            for i in extra:
                released.setdefault(i, []).append((s, c))
            grid.append({"supportMin": s, "contradictionMax": c, "allow": count["ALLOW"], "r1": count["R1"], "hold": count["HOLD"], "reject": count["REJECT"], "extra": extra, "lost": lost})
            print(f"| {s:.2f} | {c:.2f} | {count['ALLOW']}/{count['HOLD'] + count['R1']}/{count['REJECT']} | {count['ALLOW'] + count['R1']} / {count['HOLD']} / {count['REJECT']} | +{len(extra)} / -{len(lost)} |")
    print(f"\nCandidates released somewhere on the grid beyond now+R1: {len(released)}")
    if args.json:
        args.json.write_text(json.dumps({"now": now, "causes": cause_counts, "grid": grid, "released": released}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
