"""Recorded-trace timing: validation, per-record derivation and aggregation.

Only intervals that the record itself supplies are used. Wall time is the record's own start/end interval;
LLM and tool time are interval unions, so parallel spans are never added up into a fake wall time.
Unknown tokens/cost stay null; zero is only reported when the trace proves there was nothing to count."""
from __future__ import annotations

from typing import Any

from .contracts import SPAN_KINDS, Rejected, choice, integer, mapping, number, reject, sequence, text
from .stats import distribution, overlaps, union_length


def parse_trace(raw: Any, where: str) -> dict[str, Any]:
    try:
        return _parse_trace(raw, where)
    except Rejected as exc:
        if exc.code == "trace_invalid":
            raise
        raise Rejected("trace_invalid", exc.message) from None


def _parse_trace(raw: Any, where: str) -> dict[str, Any]:
    trace = mapping(raw, where, ("startMs", "endMs"), ("spans",))
    start = number(trace["startMs"], f"{where}.startMs")
    end = number(trace["endMs"], f"{where}.endMs")
    if end < start:
        reject("trace_invalid", f"{where}: endMs precedes startMs")
    out: dict[str, Any] = {"wallMs": end - start, "spansRecorded": "spans" in trace, "llmMs": None, "toolMs": None,
                           "otherMs": None, "llmCalls": None, "toolCalls": None, "tokens": None, "costUsd": None,
                           "parallelSpans": None}
    if "spans" not in trace:
        return out
    spans: dict[str, dict[str, Any]] = {}
    for index, raw_span in enumerate(sequence(trace["spans"], f"{where}.spans")):
        sw = f"{where}.spans[{index}]"
        span = mapping(raw_span, sw, ("spanId", "kind", "name", "startMs", "endMs"), ("parentSpanId", "tokens", "costUsd"))
        span_id = text(span["spanId"], f"{sw}.spanId")
        if span_id in spans:
            reject("trace_invalid", f"{sw}: duplicate spanId {span_id!r}")
        kind = choice(span["kind"], SPAN_KINDS, f"{sw}.kind")
        text(span["name"], f"{sw}.name")
        s, e = number(span["startMs"], f"{sw}.startMs"), number(span["endMs"], f"{sw}.endMs")
        if e < s:
            reject("trace_invalid", f"{sw}: endMs precedes startMs")
        if s < start or e > end:
            reject("trace_invalid", f"{sw}: span lies outside the record interval")
        tokens = span.get("tokens")
        if tokens is not None:
            if kind != "llm":
                reject("trace_invalid", f"{sw}: tokens are only valid on llm spans")
            tokens = mapping(tokens, f"{sw}.tokens", ("input", "output"))
            tokens = {"input": integer(tokens["input"], f"{sw}.tokens.input"), "output": integer(tokens["output"], f"{sw}.tokens.output")}
        spans[span_id] = {"kind": kind, "start": s, "end": e, "parent": text(span.get("parentSpanId"), f"{sw}.parentSpanId", nullable=True), "tokens": tokens,
                          "cost": number(span.get("costUsd"), f"{sw}.costUsd", nullable=True)}
    for span_id, span in spans.items():
        parent = span["parent"]
        if parent is None:
            continue
        if parent not in spans or parent == span_id:
            reject("trace_invalid", f"span {span_id!r}: unknown or self parent")
        outer = spans[parent]
        if span["start"] < outer["start"] or span["end"] > outer["end"]:
            reject("trace_invalid", f"span {span_id!r} is not contained in its parent {parent!r}")
    for span_id, span in spans.items():  # a containment cycle needs identical intervals; make it explicit
        seen, cursor = {span_id}, span["parent"]
        while cursor is not None:
            if cursor in seen:
                reject("trace_invalid", f"span {span_id!r}: parent cycle")
            seen.add(cursor)
            cursor = spans[cursor]["parent"]
    everything = [(s["start"], s["end"]) for s in spans.values()]
    llm = [s for s in spans.values() if s["kind"] == "llm"]
    tool = [s for s in spans.values() if s["kind"] == "tool"]
    out.update(
        llmMs=union_length([(s["start"], s["end"]) for s in llm]),
        toolMs=union_length([(s["start"], s["end"]) for s in tool]),
        otherMs=max(0.0, out["wallMs"] - union_length(everything)),
        llmCalls=len(llm), toolCalls=len(tool), parallelSpans=overlaps(everything))
    if all(s["tokens"] is not None for s in llm):
        out["tokens"] = {"input": sum(s["tokens"]["input"] for s in llm), "output": sum(s["tokens"]["output"] for s in llm)}
    if all(s["cost"] is not None for s in spans.values()):
        out["costUsd"] = sum(s["cost"] for s in spans.values())
    return out


def _known(parsed: list[dict[str, Any] | None], key: str) -> list[Any]:
    return [t[key] for t in parsed if t is not None and t[key] is not None]


def _total(values: list[float], population: int) -> dict[str, Any]:
    return {"known": len(values), "unknown": population - len(values), "total": round(sum(values), 6) if values else None}


def summarize(traces: list[dict[str, Any] | None], semantics: str) -> dict[str, Any]:
    """`traces` has one entry per *ok* record: a parsed trace or None when the record carried no trace."""
    population = len(traces)
    with_trace = [t for t in traces if t is not None]
    return {
        "semantics": semantics,
        "population": {"okRecords": population, "withTrace": len(with_trace), "withoutTrace": population - len(with_trace)},
        "latencyMs": {
            "wall": distribution(t["wallMs"] for t in with_trace),
            "llm": distribution(_known(traces, "llmMs")),
            "tool": distribution(_known(traces, "toolMs")),
            "other": distribution(_known(traces, "otherMs")),
        },
        "calls": {
            "llm": _total(_known(traces, "llmCalls"), population),
            "tool": _total(_known(traces, "toolCalls"), population),
        },
        "tokens": {
            "input": _total([t["tokens"]["input"] for t in with_trace if t["tokens"] is not None], population),
            "output": _total([t["tokens"]["output"] for t in with_trace if t["tokens"] is not None], population),
        },
        "costUsd": _total(_known(traces, "costUsd"), population),
        "parallelRecords": sum(1 for t in with_trace if t["parallelSpans"]),
        "notes": ["latency is never summed across records or spans; wall = each record's own interval",
                  "llm/tool/other are null (not 0) for records without recorded spans",
                  "tokens/cost totals cover only records where every relevant span reported them; see known/unknown"],
    }
