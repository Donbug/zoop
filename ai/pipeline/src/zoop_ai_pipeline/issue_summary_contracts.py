"""Pure contract of the multi-article ISSUE SUMMARY (`issues[].summary` of the public handoff bundle). No I/O, no storage, no model.

One module is shared by the summary job ledger (`issue_summary`), the live prompt/verifier modules, the handoff planner/validator and the Java importer
port, so the wire has exactly one definition:

* `summary_basis` pins WHAT the model may read: the issue title and the union of the issue's mention evidence spans (`mentions[].evidenceIds`), each
  with its exact article version and quote hash, and whether the quote only reports an earlier event (`background`). Nothing else of the issue enters.
* `deterministic_code` is the zero-call rule table: an issue with ANY HOLD/REJECT field verdict (`eventTime`/`period`) has no summary at all
  (`temporal-review-pending`), an issue with more than `MAX_QUOTES` quotes is `input-too-large`; neither ever reaches a job or a provider.
* `check_summary` validates ONE issue's `summary` value against the whole decision table and the recomputed basis. A deterministic code is accepted only while
  its condition holds, an `available` value only while no deterministic code applies, and a job-coded value only for the exact basis it was produced for.

Everything is a code-point/byte-exact, closed-shape rule (no regular-expression vocabularies, no locale or Unicode-normalisation dependence), so the Java
port reproduces it value for value. A violation raises `ValueError("summary.<where>")`.
"""
from __future__ import annotations

import re
from typing import Any

from .relation_contracts import canonical, digest

__all__ = ["canonical", "digest"]

POLICY = "zoop-issue-summary-policy-1"          # the quote cap below is part of this identity: changing MAX_QUOTES changes this string
SCHEMA = "zoop-issue-summary-1"
MAX_QUOTES, MAX_CLAIMS, MAX_CLAIM_QUOTES, MAX_CLAIM_TEXT = 60, 5, 5, 280      # MAX_CLAIM_TEXT counts Unicode code points
LANGUAGE = "ko"

NOT_REQUESTED, TEMPORAL_PENDING, INPUT_TOO_LARGE = "not-requested", "temporal-review-pending", "input-too-large"
DETERMINISTIC = (NOT_REQUESTED, TEMPORAL_PENDING, INPUT_TOO_LARGE)      # carry `source: null`; no job exists behind them
JOB_CODES = ("producer-invalid", "verifier-hold", "verifier-reject")    # carry the job `source`
OUTCOMES = ("available", *JOB_CODES)
CONTEXTS = ("report", "background")
HELD_DECISIONS = ("HOLD", "REJECT")

# (executionMode, recordingKind) -> (producer kind, verifier kind). A replay is an authored answer, never an independent model's.
KINDS = {("replay", "authored-test"): ("authored-replay", "authored-replay"), ("live", "provider"): ("provider", "independent-verifier")}

ID = r"[A-Za-z0-9._:-]{1,200}"
HASH = r"[a-f0-9]{64}"
EVIDENCE_ID = r"ev-[a-f0-9]{64}"

SOURCE_KEYS = ("jobId", "inputDigest", "resultDigest", "basisDigest")
AVAILABLE_KEYS = ("status", "text", "claims", "evidenceIds", "generatedAt", "resultVersion", "language", "source", "producer", "verifier")
PRODUCER_KEYS = ("kind", "model", "reasoningEffort", "promptVersion", "schemaDigest", "runtimeIdentity")
VERIFIER_KEYS = ("kind", "model", "adapterIdentity", "requestDigest")
CLAIM_KEYS = ("claimId", "text", "evidenceIds")

# `generatedAt` grammar (one definition for the producer, the Java verifier and the service; shared vectors: api/src/test/resources/graph-handoff/summary-time-vectors.json).
# EXACTLY: YYYY-MM-DDTHH:MM:SS, optionally `.` + 1..9 ASCII digits (any trailing zeros), then uppercase `Z` or a numeric offset `+HH:MM` / `-HH:MM`; ASCII digits only,
# uppercase `T`/`Z`, no spaces, no basic (compact) form, no week/ordinal date, no comma fraction, no leap second. Calendar rules: year 0001..9999, Gregorian leap
# years, month 1..12, a day that exists, hour 00..23, minute 00..59, second 00..59. Offset: hour 00..18, minute 00..59, and hour 18 only with minute 00 (so -18:00 and
# +18:00 are the extremes); `+00:00`, `-00:00` and `Z` are all accepted. Only this field is constrained: no other timestamp of the bundle is affected.
GENERATED_AT = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,9})?(?:Z|[+-]([0-9]{2}):([0-9]{2}))")
_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def validate_generated_at(value: Any) -> None:
    """Pure check of the `generatedAt` grammar above (`fullmatch`, no normalisation). Anything else, a non-string included, is `ValueError("summary.generatedAt")`."""
    found = GENERATED_AT.fullmatch(value) if isinstance(value, str) else None
    if found is None:
        raise ValueError("summary.generatedAt")
    year, month, day, hour, minute, second = (int(found.group(i)) for i in range(1, 7))
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    ok = (1 <= year <= 9999 and 1 <= month <= 12 and 1 <= day <= _MONTH_DAYS[month - 1] + (1 if month == 2 and leap else 0)
          and hour <= 23 and minute <= 59 and second <= 59)
    if found.group(7) is not None:
        offset_hour, offset_minute = int(found.group(7)), int(found.group(8))
        ok = ok and offset_hour <= 18 and offset_minute <= 59 and (offset_hour < 18 or offset_minute == 0)
    if not ok:
        raise ValueError("summary.generatedAt")


# ---------------------------------------------------------------------------------------------------------- basis -------------------

def temporal_review_pending(issue: dict) -> bool:
    """Any operator field verdict of the issue (on ANY mention, representative or not) that is HOLD or REJECT. Only `eventTime` and `period` are judged."""
    return any(v["decision"] in HELD_DECISIONS for v in issue["fieldVerdicts"])


def summary_basis(issue: dict, evidence: dict[str, dict], articles: dict[tuple[str, str], dict]) -> dict:
    """The exact model input of one issue: its title and the union of `mentions[].evidenceIds` (sorted by evidence id), each pinned to its article version
    and quote hash. A quote is `background` only when EVERY mention citing it is a background (past-context) mention. Geography-only and verdict-only
    evidence is never part of it. `evidence` maps evidence id -> bundle evidence record, `articles` maps (articleId, articleVersion) -> bundle article."""
    background: dict[str, bool] = {}
    for mention in issue["mentions"]:
        for ident in mention["evidenceIds"]:
            background[ident] = background.get(ident, True) and mention["background"] is True
    quotes, used = [], {}
    for ident in sorted(background):
        record = evidence[ident]
        key = (record["articleId"], record["articleVersion"])
        article = articles[key]
        used[key] = {"articleId": key[0], "articleVersion": key[1], "documentId": article["documentId"], "documentVersion": article["documentVersion"],
                     "textSha256": article["textSha256"]}
        quotes.append({"evidenceId": ident, "articleId": key[0], "articleVersion": key[1], "start": record["start"], "end": record["end"],
                       "quoteSha256": record["quoteSha256"], "context": "background" if background[ident] else "report"})
    return {"policy": POLICY, "issueId": issue["id"], "title": issue["title"], "quotes": quotes, "articles": [used[key] for key in sorted(used)]}


def basis_digest(basis: dict) -> str:
    return digest(basis)


def deterministic_code(issue: dict, basis: dict) -> str | None:
    """The zero-call rule table, in order: a held/rejected time field first, then an oversized input. None means a job may exist for this issue."""
    if temporal_review_pending(issue):
        return TEMPORAL_PENDING
    if len(basis["quotes"]) > MAX_QUOTES:
        return INPUT_TOO_LARGE
    return None


# --------------------------------------------------------------------------------------------------------- assembly -----------------

def result_version(basis_digest_: str, claims: list[dict]) -> str:
    """Content identity of an available summary: the basis it was written for and its claims. Never a time, a job id or a runtime."""
    return "isr-" + digest({"basisDigest": basis_digest_, "claims": claims})


def result_digest(job_id: str, input_digest: str, basis_digest_: str, body: dict) -> str:
    """The digest a decisions pin and the bundle `source` carry: the job identity and basis around the result `body` (the summary without `source`)."""
    return digest({"jobId": job_id, "inputDigest": input_digest, "basisDigest": basis_digest_, "result": body})


def available_body(basis_digest_: str, claims: list[dict], generated_at: str, producer: dict, verifier: dict) -> dict:
    """The `available` summary without `source`. `claims` are `[{claimId, text, evidenceIds}]` exactly as the producer parser returned them."""
    return {"status": "available", "text": "\n".join(c["text"] for c in claims), "claims": claims,
            "evidenceIds": sorted({i for c in claims for i in c["evidenceIds"]}), "generatedAt": generated_at,
            "resultVersion": result_version(basis_digest_, claims), "language": LANGUAGE, "producer": producer, "verifier": verifier}


def withheld_body(code: str) -> dict:
    if code not in JOB_CODES:
        raise ValueError("summary.code")
    return {"status": "unavailable", "code": code}


def deterministic_summary(code: str) -> dict:
    if code not in DETERMINISTIC:
        raise ValueError("summary.code")
    return {"status": "unavailable", "code": code, "source": None}


def assemble(job_id: str, input_digest: str, basis_digest_: str, body: dict) -> dict:
    """The exact bundle `issues[].summary` value of a finished job: the result `body` plus its pinned `source`."""
    return {**body, "source": {"jobId": job_id, "inputDigest": input_digest, "resultDigest": result_digest(job_id, input_digest, basis_digest_, body),
                               "basisDigest": basis_digest_}}


# ------------------------------------------------------------------------------------------------------------ check ---------------

def _bad(at: str):
    raise ValueError(f"summary.{at}")


def _need(condition: bool, at: str) -> None:
    if not condition:
        _bad(at)


def _keys(value: Any, keys: tuple, at: str) -> dict:
    _need(isinstance(value, dict) and set(value) == set(keys), at)
    return value


def _match(value: Any, pattern: str, at: str) -> None:
    _need(isinstance(value, str) and re.fullmatch(pattern, value) is not None, at)


def _hangul(text: str) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in text)


def _source(value: Any, basis_digest_: str) -> dict:
    source = _keys(value, SOURCE_KEYS, "source")
    _match(source["jobId"], ID, "source.jobId")
    for name in ("inputDigest", "resultDigest", "basisDigest"):
        _match(source[name], HASH, f"source.{name}")
    _need(source["basisDigest"] == basis_digest_, "source.basisDigest")        # the job was produced for exactly THIS basis
    return source


def _identity(value: Any, keys: tuple, kind: str, live: bool, at: str) -> dict:
    block = _keys(value, keys, at)
    _need(block["kind"] == kind, f"{at}.kind")
    _need((isinstance(block["model"], str) and 1 <= len(block["model"]) <= 200) if live else block["model"] is None, f"{at}.model")
    return block


def check_summary(issue: dict, summary: Any, basis: dict, execution_pair: tuple[str, str]) -> None:
    """Validate `issue.summary` against the whole decision table. `basis` is `summary_basis(...)` of this very issue, `execution_pair` the bundle's
    (executionMode, recordingKind). The producer pairs with the bundle mode: a replay summary can never sit in a live bundle and vice versa."""
    _need(isinstance(summary, dict) and summary.get("status") in ("available", "unavailable"), "status")
    expected = deterministic_code(issue, basis)
    digest_ = basis_digest(basis)
    if summary["status"] == "unavailable":
        _keys(summary, ("status", "code", "source"), "shape")
        code = summary["code"]
        if code in DETERMINISTIC:
            # A deterministic code is accepted only while its own condition holds (and the earlier rule did not already decide); `not-requested` only
            # while no deterministic rule applies. A held issue therefore never carries any other summary value, `available` included.
            _need(summary["source"] is None and code == (expected or NOT_REQUESTED), "code")
            return
        _need(expected is None and code in JOB_CODES, "code")
        source = _source(summary["source"], digest_)
        _need(source["resultDigest"] == result_digest(source["jobId"], source["inputDigest"], digest_, withheld_body(code)), "source.resultDigest")
        return
    _need(expected is None, "status")
    _keys(summary, AVAILABLE_KEYS, "shape")
    kinds = KINDS.get(tuple(execution_pair))
    _need(kinds is not None, "mode")
    live = execution_pair[0] == "live"
    allowed = {q["evidenceId"] for q in basis["quotes"]}
    claims = summary["claims"]
    _need(isinstance(claims, list) and 1 <= len(claims) <= MAX_CLAIMS, "claims")
    union: set[str] = set()
    for index, claim in enumerate(claims):
        _keys(claim, CLAIM_KEYS, "claims.shape")
        _need(claim["claimId"] == f"c{index + 1}", "claims.claimId")
        text = claim["text"]
        _need(isinstance(text, str) and 1 <= len(text) <= MAX_CLAIM_TEXT and "\n" not in text and "\r" not in text and _hangul(text), "claims.text")
        ids = claim["evidenceIds"]
        _need(isinstance(ids, list) and 1 <= len(ids) <= MAX_CLAIM_QUOTES and all(isinstance(i, str) for i in ids) and ids == sorted(set(ids))
              and set(ids) <= allowed, "claims.evidenceIds")
        union.update(ids)
    _need(summary["text"] == "\n".join(c["text"] for c in claims), "text")
    _need(summary["evidenceIds"] == sorted(union), "evidenceIds")
    _need(summary["language"] == LANGUAGE, "language")
    validate_generated_at(summary["generatedAt"])
    _need(summary["resultVersion"] == result_version(digest_, claims), "resultVersion")
    producer = _identity(summary["producer"], PRODUCER_KEYS, kinds[0], live, "producer")
    _need((isinstance(producer["reasoningEffort"], str) and 1 <= len(producer["reasoningEffort"]) <= 50) if live else producer["reasoningEffort"] is None,
          "producer.reasoningEffort")
    _need(isinstance(producer["promptVersion"], str) and 1 <= len(producer["promptVersion"]) <= 200, "producer.promptVersion")
    _match(producer["schemaDigest"], HASH, "producer.schemaDigest")
    _match(producer["runtimeIdentity"], HASH, "producer.runtimeIdentity")
    verifier = _identity(summary["verifier"], VERIFIER_KEYS, kinds[1], live, "verifier")
    _match(verifier["adapterIdentity"], HASH, "verifier.adapterIdentity")
    _match(verifier["requestDigest"], HASH, "verifier.requestDigest")
    source = _source(summary["source"], digest_)
    body = {k: v for k, v in summary.items() if k != "source"}
    _need(source["resultDigest"] == result_digest(source["jobId"], source["inputDigest"], digest_, body), "source.resultDigest")
