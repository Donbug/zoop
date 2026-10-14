"""Side-by-side comparison of compatible runs. No ranking, no winner, no pass/fail."""
from __future__ import annotations

from typing import Any

from .contracts import SCHEMA_COMPARE, reject


def _factors(system: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {"family": system["family"], "promptRevision": system["promptRevision"],
                            "toolRevision": system["toolRevision"], "schemaRevision": system["schemaRevision"],
                            "graphRevision": system["graphRevision"]}
    model = system["model"]
    flat["model"] = None if model is None else f"{model['provider']}/{model['name']}@{model['version']}"
    for key, value in (system["capabilities"] or {}).items():
        flat[f"capabilities.{key}"] = value
    for key, value in system["config"].items():
        flat[f"config.{key}"] = value
    return flat


def compare_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    if len(scores) < 2:
        reject("compare_incompatible", "compare needs at least two runs")
    ids = [s["runId"] for s in scores]
    if len(set(ids)) != len(ids):
        reject("duplicate_run_id", f"duplicate runId in comparison: {sorted({i for i in ids if ids.count(i) > 1})}")
    first = scores[0]
    for other in scores[1:]:
        if other["provenance"]["kind"] != first["provenance"]["kind"]:
            reject("mixed_provenance", "authored controls and real measurements are never compared or ranked together")
        if other["provenance"]["executionMode"] != first["provenance"]["executionMode"]:
            reject("mixed_mode", f"execution modes differ: {first['provenance']['executionMode']} vs {other['provenance']['executionMode']}")
        for key in ("corpusId", "corpusRevision", "goldRevision", "inputsSha256", "goldSha256", "split", "tasks"):
            if other["corpus"][key] != first["corpus"][key]:
                reject("compare_incompatible", f"corpus {key} differs: {first['corpus'][key]!r} vs {other['corpus'][key]!r}")
        if other["schema"] != first["schema"] or other["scorerVersion"] != first["scorerVersion"]:
            reject("compare_incompatible", "runs were scored by different scorer/schema versions")

    flats = [_factors(s["system"]) for s in scores]
    keys = sorted({k for f in flats for k in f})
    differing = {k: [f.get(k) for f in flats] for k in keys if len({repr(f.get(k)) for f in flats}) > 1}
    contexts = [s["timingContext"] for s in scores]
    timing_ok = all(c is not None and c == contexts[0] for c in contexts)
    names = list(first["headline"])
    metrics: dict[str, list[dict[str, Any]]] = {}
    delta: dict[str, list[float | None]] = {}
    for name in names:
        if name.startswith("timing.") and not timing_ok:
            continue
        metrics[name] = [{"runId": s["runId"], **s["headline"][name]} for s in scores]
        base = metrics[name][0]["value"]
        delta[name] = [None if base is None or m["value"] is None or i == 0 else round(m["value"] - base, 6)
                       for i, m in enumerate(metrics[name])]
    notes = ["no ranking is produced: compare reports side-by-side values, counts and deltas against the first run only",
             "synthetic/unadjudicated gold and small case counts: differences are descriptive, not significance-tested"]
    if not timing_ok:
        notes.append("timing metrics omitted: runs lack an identical timingContext (concurrency, warmup, environment)")
    if first["provenance"]["kind"] == "authored_control":
        notes.append("AUTHORED CONTROLS: these runs are scorer inputs, not systems; the table checks the scorer, not any system")
    return {
        "schema": SCHEMA_COMPARE, "comparable": True, "provenanceKind": first["provenance"]["kind"],
        "executionMode": first["provenance"]["executionMode"], "corpus": {k: first["corpus"][k] for k in ("corpusId", "corpusRevision", "goldRevision", "split", "tasks")},
        "runs": [{"runId": s["runId"], "systemId": s["system"]["systemId"], "family": s["system"]["family"]} for s in scores],
        "differingFactors": differing, "oneFactorChange": len(differing) == 1, "timingComparable": timing_ok,
        "metrics": metrics, "deltaVsFirst": delta, "notes": notes,
    }
