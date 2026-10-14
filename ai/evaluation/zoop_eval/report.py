"""Compact human-readable rendering of score and compare documents."""
from __future__ import annotations

from typing import Any


def fmt(metric: dict[str, Any] | None) -> str:
    if metric is None:
        return "-"
    value = metric.get("value")
    if value is None:
        return f"n/a ({metric['status']})" if "status" in metric else (
            f"n/a ({metric['num']}/{metric['den']})" if "den" in metric else "n/a")
    if "den" in metric:
        return f"{value:.3f} ({metric['num']}/{metric['den']})"
    return f"{value:g}" + (f" (n={metric['n']})" if "n" in metric else "")


def _cov(block: dict[str, Any]) -> str:
    return f"ok {block['ok']} / refused {block['refused']} / error {block['error']} / missing {block['missing']} of {block['total']}"


def render_score(score: dict[str, Any]) -> str:
    sysd, corpus = score["system"], score["corpus"]
    model = sysd["model"] and f"{sysd['model']['provider']}/{sysd['model']['name']}@{sysd['model']['version']}"
    lines = [
        f"== run {score['runId']}{' - ' + score['label'] if score['label'] else ''} ==",
        score["provenanceLabel"],
        f"corpus {corpus['corpusId']}@{corpus['corpusRevision']} gold@{corpus['goldRevision']} split={corpus['split']} tasks={','.join(corpus['tasks'])}",
        f"system {sysd['systemId']} family={sysd['family']} model={model or 'none'} config={sysd['config']}",
    ]
    if "graph" in score:
        g = score["graph"]
        lines += ["", f"GRAPH coverage: {_cov(g['coverage'])}",
                  f"  entity linking   acc {fmt(g['entityLinking']['accuracy'])}  false-link-on-unknown {fmt(g['entityLinking']['falseLinkOnUnknown'])}  mis-link {fmt(g['entityLinking']['misLinkedToOtherEntity'])}",
                  f"  event attributes type {fmt(g['events']['typeAccuracy'])}  date {fmt(g['events']['dateAccuracy'])}  date-invented {fmt(g['events']['dateInvented'])}"]
        for kind, m in g["merges"].items():
            lines.append(f"  merge[{kind:6}]   acc {fmt(m['accuracy'])}  FALSE-MERGE {fmt(m['falseMerge'])}  unsafe-on-undecidable {fmt(m['unsafeMergeOnUndecidable'])}  missed {fmt(m['missedMerge'])}")
        e = g["edges"]
        lines += [f"  edges exact      P {fmt(e['exactPrecision'])}  R {fmt(e['exactRecall'])}  F1 {e['exactF1'] if e['exactF1'] is not None else 'n/a'}",
                  f"  edges triple     P {fmt(e['triplePrecision'])}  R {fmt(e['tripleRecall'])}  reversed {fmt(e['reversedDirection'])}  not-in-gold {fmt(e['notInGold'])}",
                  f"  edges temporal   invented {fmt(e['temporalInvented'])}  bound-acc {fmt(e['temporalBoundAccuracy'])}  wrong {e['temporalWrong']}  dropped {e['temporalDropped']}"]
    if "qa" in score:
        a = score["qa"]["all"]
        lines += ["", f"QA coverage: {_cov(a['coverage'])}",
                  f"  outcome correct {fmt(a['outcome']['correct'])}  end-to-end structured correct {fmt(a['outcome']['endToEndCorrect'])}",
                  f"  abstention  P {fmt(a['abstention']['precision'])}  R {fmt(a['abstention']['recall'])}  over-abstain {fmt(a['abstention']['overAbstention'])}  unsupported-answer {fmt(a['abstention']['unsupportedAnswer'])}  conflict R {fmt(a['abstention']['conflictRecall'])}",
                  f"  support     P {fmt(a['retrieval'].get('supportPrecision') or {'value': None, 'status': a['retrieval'].get('status', '')})}  R {fmt(a['retrieval'].get('supportRecall') or {'value': None, 'status': a['retrieval'].get('status', '')})}",
                  f"  path        validity {fmt(a['path'].get('validity') or {'value': None, 'status': a['path'].get('status', '')})}  exact {fmt(a['path'].get('exactMatch') or {'value': None, 'status': a['path'].get('status', '')})}  hop-coverage {fmt(a['path'].get('hopCoverage') or {'value': None, 'status': a['path'].get('status', '')})}",
                  f"  citations   P {fmt(a['citations'].get('precision') or {'value': None, 'status': a['citations'].get('status', '')})}  R {fmt(a['citations'].get('recall') or {'value': None, 'status': a['citations'].get('status', '')})}",
                  f"  free text   {a['freeText']['answerTextRecords']} answer text(s): {a['freeText']['status']}",
                  "  by hop (end-to-end structured correct | hop coverage):"]
        for hop, block in score["qa"]["byHop"].items():
            lines.append(f"    {hop}-hop  {fmt(block['outcome']['endToEndCorrect'])}  |  {fmt(block['path'].get('hopCoverage') or {'value': None, 'status': block['path'].get('status', '')})}")
        lines.append("  by kind (end-to-end structured correct): " + "  ".join(
            f"{kind}={fmt(block['outcome']['endToEndCorrect'])}" for kind, block in score["qa"]["byKind"].items()))
    for task, block in score["timing"].items():
        t = block["all"] if task == "qa" else block
        lines += ["", f"TIMING {task} [{t['semantics']}] ok records {t['population']['okRecords']}, with trace {t['population']['withTrace']}"]
        for stat in ("wall", "llm", "tool"):
            d = t["latencyMs"][stat]
            lines.append(f"  {stat:5} ms  n={d['n']}  p50={d['p50']}  p95={d['p95']}  max={d['max']}" + (f"  caveats: {'; '.join(d['caveats'])}" if d["caveats"] else ""))
        lines.append(f"  llm calls {t['calls']['llm']}  tool calls {t['calls']['tool']}  tokens in {t['tokens']['input']} out {t['tokens']['output']}  costUsd {t['costUsd']}")
    lines += ["", "WARNINGS"] + [f"  - {w}" for w in score["warnings"]]
    lines += ["NOT EVALUATED"] + [f"  - {w}" for w in score["notEvaluated"]]
    return "\n".join(lines)


def render_compare(result: dict[str, Any]) -> str:
    runs = result["runs"]
    lines = [f"== compare {len(runs)} runs ({result['provenanceKind']}, {result['executionMode']}) ==",
             f"corpus {result['corpus']['corpusId']}@{result['corpus']['corpusRevision']} split={result['corpus']['split']}",
             "differing factors: " + (", ".join(f"{k}={v}" for k, v in result["differingFactors"].items()) or "none")
             + ("  [one factor changed]" if result["oneFactorChange"] else ""),
             "", "metric".ljust(46) + "".join(r["runId"][:24].ljust(26) for r in runs)]
    for name, cells in result["metrics"].items():
        lines.append(name.ljust(46) + "".join(fmt(c).ljust(26) for c in cells))
    lines += ["", "NOTES"] + [f"  - {n}" for n in result["notes"]]
    return "\n".join(lines)
