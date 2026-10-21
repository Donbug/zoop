#!/usr/bin/env python3
"""LIVE (paid) end-to-end exercise: synthetic Korean documents -> native ingestion -> S2 live -> S3 live -> [scripted manual approval] -> Neo4j graph.

This is an operator smoke for the main agent, NOT a scheduler, collector or publisher. It spends real provider money and is therefore inert unless
explicitly enabled (`--live`, the environment gate, a fresh output root, a finite budget at or below the stated cap).

What is real and what is synthetic (the summary says so again):
  * REAL provider calls: gpt-6-luna (reasoning effort high) for extract/compare/topic/relation/impact and jev-1.14.0 for verify-relation/verify-impact,
    made by the installed `zoop-ai-extract` / `zoop-ai-relation` console scripts under the shared USD/call budget.
  * SYNTHETIC input: the source documents, the company catalogue, the one snapshot (prior) event, the source grant and the canonical decisions are
    authored in this script. No real news, publisher, person or company is used. Canonical decisions are a scripted synthetic test operator's, derived
    only from the candidates the models actually emitted.
  * Manual approval (only with --exercise-manual-approval) is a SCRIPTED SYNTHETIC TEST operator decision on a genuine Jev HOLD, not an editorial decision.

Nothing here loads a .env, edits one, wipes a database, publishes anything to the application, retries a call or resubmits an uncertain one. Verdicts
are whatever the models returned: a HOLD is exercised only if one genuinely occurred, never manufactured. A real failure is reported as a failure and
the run stops (no fixture fallback, no replay).
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import os
import re
import secrets
import sqlite3
import statistics
import subprocess
import sys
import time
from collections import Counter, deque
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCHEMA = "zoop-live-graph-smoke-1"
INGESTION_SCHEMA = "zoop-ingestion-s2-1"
EXTRACTION_SCHEMA = "zoop-extraction-s2-2"
RELATION_SCHEMA = "zoop-relation-s3"
GRAPH_SCHEMA = "zoop-graph-projection-1"
CANONICAL_SCHEMA = "zoop-graph-canonical-1"

MODEL, EFFORT, JEV = "gpt-6-luna", "high", "jev-1.14.0"
STANDARD_HOSTS = {"openai": "api.openai.com", "typesafe": "api.typesafe.ai"}
HARD_CEILING_USD = "10"  # the user-approved TOTAL for this live test; --usd-cap may be lower, never higher
PROVENANCE = {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}
GENERATION_STAGES = ("extract", "compare", "topic", "relation", "impact")
VERIFY_STAGES = ("verify-relation", "verify-impact")
SOURCE_ID, SCOPE_ID = "synthetic-live-source", "body"
REVIEWER = "scripted-synthetic-test-operator"
NOTE = "SCRIPTED SYNTHETIC TEST approval by the live graph smoke harness: not a human editorial decision and not a publication approval."
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")
TOOLS = {"ingest": "zoop-ai-ingest", "extract": "zoop-ai-extract", "relation": "zoop-ai-relation", "graph": "zoop-ai-graph"}

# ------------------------------------------------------------------------------------------------ authored synthetic world

COMPANIES = [("LIVE-ELEC", "가상전자"), ("LIVE-MATL", "가상소재"), ("LIVE-MOBI", "가상모빌리티"), ("LIVE-INVT", "가상투자"), ("LIVE-ENRG", "가상에너지")]
CATALOGUE = {"revision": "live-smoke-catalogue-1",
             "companies": [{"companyId": i, "name": n, "aliases": [], "ticker": None} for i, n in COMPANIES]}
MAIN_TITLE = "[가상 문서] 가상전자·가상소재 양극재 공급 계약 체결"
MAIN_TEXT = (
    "가상전자는 2026년 10월 20일 가상소재와 배터리 양극재 공급 계약을 체결했다고 발표했다.",
    "계약 기간은 2027년 1월 1일부터 2028년 12월 31일까지이며, 가상소재가 가상전자의 배터리 셀 생산 라인에 양극재를 납품한다.",
    "가상모빌리티는 가상전자의 배터리를 장착한 전기차를 2027년 상반기에 출시할 계획이라고 밝혔다.",
    "가상전자와 가상에너지는 같은 전기차 배터리 시장에서 경쟁하고 있다.",
    "가상소재는 가상에너지와도 양극재 공급을 협의하고 있으나 아직 확정된 사항은 없다고 설명했다.",
    "시장에서는 이번 계약으로 가상전자의 원재료 조달 부담이 줄어들 것으로 전망했으나, 일부에서는 양극재 가격 변동에 따른 비용 증가 가능성도 지적했다.")
PRIOR_TITLE = "[가상 문서] 가상전자 배터리 셀 신규 공장 증설 발표"
PRIOR_TEXT = (
    "가상전자는 2026년 9월 15일 충남 지역에 배터리 셀 신규 공장을 증설하겠다고 발표했다.",
    "투자 규모는 3천억 원이고 2027년 하반기 가동을 목표로 한다.",
    "가상투자는 이 증설 사업에 지분 투자를 결정했다고 밝혔다.")
DOCUMENTS = (("main", MAIN_TITLE, MAIN_TEXT, "2026-10-20T00:00:00+00:00"), ("prior", PRIOR_TITLE, PRIOR_TEXT, "2026-09-15T00:00:00+00:00"))
SNAPSHOT_EVENT = "snap-event-1"

EPILOG = f"""\
Required environment (Main injects it; this script never reads a .env):
  ZOOP_AI_PIPELINE_LIVE_ENABLED=1  ZOOP_AI_PIPELINE_LIVE_MODEL={MODEL}  ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT={EFFORT}  TYPESAFE_VALIDATION_MODEL={JEV}
  ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR=<absolute dir>  ZOOP_AI_PIPELINE_LIVE_MAX_USD=<= --usd-cap  ZOOP_AI_PIPELINE_LIVE_MAX_CALLS=<n>
  ZOOP_AI_API_KEY  TYPESAFE_API_KEY   (optional: ZOOP_AI_BASE_URL TYPESAFE_BASE_URL ZOOP_AI_PIPELINE_LIVE_MAX_OUTPUT_TOKENS ..._TIMEOUT_SECONDS)
  ZOOP_GRAPH_AUTH=none|basic [ZOOP_GRAPH_USER ZOOP_GRAPH_PASSWORD] [SSL_CERT_FILE for bolt+s]   (an EMPTY, dedicated Neo4j 5 database)
  ZOOP_STATE_DIR ZOOP_AI_WORKER_STATE_DIR  (absolute; only when run from an installed package, not a source checkout)
Only the live names above reach the S2/S3 children; the ingestion, review and graph children never receive a model key.

Run (from ai/pipeline, with the installed environment):
  .venv/bin/python scripts/live_graph_smoke.py --check --output-root /real/abs/new-dir --graph-uri bolt://127.0.0.1:7687 --usd-cap 10
  .venv/bin/python scripts/live_graph_smoke.py --live  --output-root /real/abs/new-dir --graph-uri bolt://127.0.0.1:7687 --usd-cap 10 [--exercise-manual-approval]

--check validates configuration, endpoints, console scripts and the Neo4j target (read-only graph `preflight`) and prints the plan: no file is created,
no budget file is touched, no model is called. A real run needs a NEW output root whose parent is a real directory (no symlink in the path; on macOS
use /private/tmp/..., not /tmp/...).

Output: ONE JSON summary on stdout (also <output-root>/summary.json); progress codes on stderr. Exit 0 = every check passed (a coverage gap such as
"no genuine Jev HOLD occurred" is reported, not failed); 1 = a real failure or check failure (counters so far are still printed); 2 = refused before
any spend. Stdout never contains a key, a source text, a model reply, a review note or a Neo4j credential (the summary is scanned and suppressed
otherwise). Raw receipts, results and source files stay private (0700/0600) under <output-root>/private and <output-root>/inputs.

Cleanup (the script removes nothing and never wipes a database):
  * output root: contains the synthetic raw documents, private receipts and ledgers; `rm -rf <output-root>` after the evidence is reviewed.
  * budget dir: Main-owned; the call/USD totals are cumulative there and ceilings can only decrease.
  * Neo4j: the container/database is Main-owned and is disposed by Main. The summary lists the exact version IDs/store ID created, with a targeted
    Cypher to remove only those (by exact identity) if the database is to be reused.
"""


# ------------------------------------------------------------------------------------------------ small helpers

class Failure(Exception):
    """A real failure (or refused gate). `code` is stable and never embeds a URL, key, path content or provider/source text."""

    def __init__(self, stage: str, code: str, detail: Any = None, uncertain: bool = False):
        self.stage, self.code, self.detail, self.uncertain = stage, code, detail, uncertain
        super().__init__(code)


def cj(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def usd(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def write_private(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def log(stage: str, **facts: Any) -> None:
    """Progress on stderr: stage names, counters and codes only."""
    print(json.dumps({"stage": stage, **facts}, ensure_ascii=False, sort_keys=True), file=sys.stderr, flush=True)


class Redactor:
    """Everything that must never reach stdout/stderr: keys, the Neo4j password, authored source text, titles and the review note."""

    def __init__(self) -> None:
        self.needles: set[str] = set()

    def add(self, *values: Any) -> None:
        self.needles.update(v for v in values if isinstance(v, str) and len(v) >= 6)

    def hit(self, text: str) -> bool:
        return any(needle in text for needle in self.needles)


# ------------------------------------------------------------------------------------------------ harness

class Harness:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.run_id = args.run_id or f"live-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
        self.root = args.output_root
        self.stage = "gate"
        self.started = time.monotonic()
        self.failure: dict | None = None
        self.checks: list[dict] = []
        self.stages: dict[str, Any] = {}
        self.timings: dict[str, float] = {}
        self.stderr_bytes = 0
        self.calls: dict[str, list[dict]] = {}
        self.budget_before: dict | None = None
        self.budget_after: dict | None = None
        self.coverage: dict[str, Any] = {}
        self.created_versions: list[str] = []
        self.runtime = None
        self.budget = None
        self.graph_uri = ""
        self.graph_auth = None
        self.redactor = Redactor()
        self.s2: dict | None = None
        self.s3: dict | None = None
        self.sources_bytes = b""
        self.provider_facts: dict[str, Any] = {}

    # ---- plumbing ---------------------------------------------------------------------------------------------------------------

    def check(self, name: str, condition: bool, scope: str, detail: Any = None) -> None:
        """`scope` says what the check proves: live-provider (real model receipts), offline-local (real local CLIs, no model), neo4j."""
        self.checks.append({"name": name, "scope": scope, "ok": bool(condition)})
        if not condition:
            raise Failure(self.stage, "check_failed:" + name, detail)

    def safe_detail(self, detail: Any) -> Any:
        if detail is None:
            return None
        text = cj(detail).decode("utf-8")
        return {"suppressed": "private text or oversize detail"} if self.redactor.hit(text) or len(text) > 2000 else detail

    def base_env(self) -> dict[str, str]:
        from zoop_ai_pipeline.ingestion_contracts import source_checkout
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
        for key, name in (("ZOOP_STATE_DIR", "reserved-app"), ("ZOOP_AI_WORKER_STATE_DIR", "reserved-s1-worker")):
            value = os.environ.get(key)
            if not value and not source_checkout():
                value = str(self.root / name)  # an installed package needs explicit ownership roots; they only have to exist as non-overlapping paths
            if value:
                env[key] = value
        return env

    def live_env(self) -> dict[str, str]:
        from zoop_ai_pipeline import live_runtime as lr
        names = (lr.GATE, lr.MODEL_VAR, lr.EFFORT_VAR, lr.MAX_OUTPUT_VAR, lr.TIMEOUT_VAR, lr.BUDGET_DIR_VAR, lr.MAX_USD_VAR, lr.MAX_CALLS_VAR,
                 lr.OPENAI_URL_VAR, lr.OPENAI_KEY_VAR, lr.JEV_URL_VAR, lr.JEV_KEY_VAR, lr.JEV_MODEL_VAR)
        return {**self.base_env(), **{name: os.environ[name] for name in names if name in os.environ}}

    def graph_env(self) -> dict[str, str]:
        env = {**self.base_env(), **{k: v for k, v in os.environ.items() if k.startswith("ZOOP_GRAPH_")}}
        if os.environ.get("SSL_CERT_FILE"):
            env["SSL_CERT_FILE"] = os.environ["SSL_CERT_FILE"]
        return env

    def cwd(self) -> Path | None:
        """Children run inside the output root once it exists (a --check run has none and uses the caller's directory)."""
        return self.root if self.root.is_dir() else None

    def cli(self, label: str, tool: str, args: list[str], payload: Any, env: dict[str, str], *, expected: int = 0, timeout: int | None = None,
            keep: bool = False) -> Any:
        """One installed console script as a subprocess. Returns the parsed stdout JSON; a child that exits other than `expected` is a Failure with
        the child's own error code (never its raw text). `keep` stores the (private) stdout under <root>/private/results."""
        argv = [str(self.bin / TOOLS[tool]), *args]
        began = time.monotonic()
        try:
            child = subprocess.run(argv, input=cj(payload) if payload is not None else b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                   cwd=self.cwd(), timeout=timeout or 600)
        except subprocess.TimeoutExpired:
            raise Failure(self.stage, f"{label}_child_timeout_outcome_unknown", uncertain=True) from None
        self.timings[label] = round(time.monotonic() - began, 3)
        self.stderr_bytes += len(child.stderr)
        parsed = None
        if child.stdout.strip():
            try:
                parsed = json.loads(child.stdout)
            except ValueError:
                raise Failure(self.stage, f"{label}_output_not_json", {"exit": child.returncode}) from None
            if keep:
                write_private(self.root / "private" / "results" / f"{label}.json", child.stdout)
        if child.returncode != expected:
            error = parsed.get("error") if isinstance(parsed, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            raise Failure(self.stage, f"{label}_exit_{child.returncode}" + (f":{code}" if isinstance(code, str) else ""),
                          self.safe_detail(error.get("detail") if isinstance(error, dict) else None))
        return parsed

    def cli_error(self, label: str, tool: str, args: list[str], payload: Any, env: dict[str, str], code: str) -> dict:
        """A deliberately refused command: must exit 2 with exactly this error code (offline proof, never reported as live)."""
        argv = [str(self.bin / TOOLS[tool]), *args]
        child = subprocess.run(argv, input=cj(payload), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=self.cwd(), timeout=300)
        self.stderr_bytes += len(child.stderr)
        try:
            parsed = json.loads(child.stdout)
        except ValueError:
            raise Failure(self.stage, f"{label}_output_not_json") from None
        error = parsed.get("error") if isinstance(parsed, dict) else None
        got = error.get("code") if isinstance(error, dict) else None
        self.check(f"{label}: refused with {code}", child.returncode == 2 and got == code, "offline-local", {"exit": child.returncode, "code": got})
        return parsed

    # ---- gate (no spend) --------------------------------------------------------------------------------------------------------

    def gate(self) -> None:
        a = self.args
        if not RUN_ID.match(self.run_id):
            raise Failure("gate", "run_id_invalid")
        from zoop_ai_pipeline import graph_neo4j as neo
        from zoop_ai_pipeline import live_runtime as lr
        from zoop_ai_pipeline.live_budget import Budget, nano_from_usd
        from zoop_ai_pipeline.relation_contracts import ExtractionFailure

        self.bin = Path(sys.executable).parent
        for tool in TOOLS.values():
            path = self.bin / tool
            if not path.is_file() or not os.access(path, os.X_OK):
                raise Failure("gate", f"console_script_missing:{tool}")
        root = a.output_root
        if not root.is_absolute() or ".." in root.parts:
            raise Failure("gate", "output_root_not_absolute")
        if root.exists() or root.is_symlink():
            raise Failure("gate", "output_root_not_fresh")
        if not root.parent.is_dir() or root.parent.resolve() != root.parent:
            raise Failure("gate", "output_root_parent_not_a_real_directory")
        try:
            self.runtime = lr.LiveRuntime.from_env(need_send=True)
        except lr.LiveFailure as exc:
            raise Failure("gate", f"live_configuration:{exc.code}") from None
        binding = self.runtime.binding()
        generation, verifier = binding["generation"], binding["verifier"]
        self.check("runtime pins gpt-6-luna / high / jev-1.14.0",
                   (generation["model"], generation["reasoningEffort"], verifier["model"]) == (MODEL, EFFORT, JEV), "offline-local")
        hosts = {"openai": urlsplit(generation["endpoint"]).hostname, "typesafe": urlsplit(verifier["endpoint"]).hostname}
        standard = hosts == STANDARD_HOSTS
        if not standard and not a.allow_nonstandard_endpoints:
            raise Failure("gate", "endpoint_not_the_real_provider", {"hosts": hosts})
        try:
            cap, hard = nano_from_usd(a.usd_cap), nano_from_usd(HARD_CEILING_USD)
            maximum = nano_from_usd(os.environ.get(lr.MAX_USD_VAR, ""))
            max_calls = int(os.environ[lr.MAX_CALLS_VAR])
        except (ValueError, KeyError):
            raise Failure("gate", "budget_configuration_invalid") from None
        if cap > hard:
            raise Failure("gate", "usd_cap_above_user_approved_total", {"approvedTotalUsd": HARD_CEILING_USD})
        if maximum > cap:
            raise Failure("gate", "configured_budget_above_usd_cap", {"capUsd": a.usd_cap})
        self.budget = Budget(Path(os.environ[lr.BUDGET_DIR_VAR]), maximum, max_calls)
        self.provider_facts = {"gptEndpointHost": hosts["openai"], "jevEndpointHost": hosts["typesafe"], "realProviderEndpoints": standard,
                               "bindingIdentity": binding["identity"], "model": MODEL, "reasoningEffort": EFFORT, "verifierModel": JEV,
                               "maxOutputTokens": generation["maxOutputTokens"], "pricingTier": binding["pricing"]["tier"],
                               "budget": {"maxUsd": usd(Decimal(maximum) / Decimal(10**9)), "maxCalls": max_calls, "capUsd": a.usd_cap}}
        try:
            self.graph_uri = neo.validate_uri(a.graph_uri)
            self.graph_auth = neo.read_auth(self.graph_uri)
        except ExtractionFailure as exc:
            raise Failure("gate", f"graph_configuration:{exc.code}") from None
        for name in (lr.OPENAI_KEY_VAR, lr.JEV_KEY_VAR):
            self.redactor.add(os.environ.get(name))
        self.redactor.add(os.environ.get("ZOOP_GRAPH_PASSWORD"), NOTE, *(t for _, title, texts, _ in DOCUMENTS for t in (title, *texts)))
        self.stages["gate"] = {"status": "passed", **self.provider_facts, "keysPresent": {"openai": True, "typesafe": True},
                               "graphTarget": {"scheme": urlsplit(self.graph_uri).scheme, "port": urlsplit(self.graph_uri).port}}

    def neo_preflight(self) -> None:
        self.stage = "graph-preflight"
        init = {"schemaVersion": GRAPH_SCHEMA, "storeId": f"{self.run_id}-store", "database": self.args.graph_database}
        out = self.cli("graph-preflight", "graph", ["preflight", "--state-dir", str(self.root / "graph"), "--graph-uri", self.graph_uri], init, self.graph_env())
        facts = out["preflight"]
        self.check("neo4j target is a verified empty Neo4j 5 database", facts["result"] == "eligible-empty-target" and facts["counts"] == {"nodes": 0, "relationships": 0},
                   "neo4j")
        self.stages["graphPreflight"] = {"result": facts["result"], "tls": facts["tls"], "server": facts["server"], "database": facts["database"], "ddlPermission": facts["ddlPermission"]}

    # ---- synthetic world --------------------------------------------------------------------------------------------------------

    def write_world(self) -> None:
        self.stage = "setup"
        from zoop_ai_pipeline import live_runtime as lr
        for sub in ("inputs", "private", "private/receipts", "private/results"):
            (self.root / sub).mkdir(mode=0o700, exist_ok=True)
        purposes = sorted({self.runtime.purpose(s) for s in lr.STAGES})
        recipients = sorted({self.runtime.recipient(s) for s in lr.STAGES})
        registry = {"schemaVersion": INGESTION_SCHEMA, "revision": "operator-live-1", "sources": [{
            "sourceId": SOURCE_ID, "adapter": "authored-files", "inputRoot": str(self.root / "inputs"), "allowedHosts": ["example.invalid"],
            "scopes": [{"scopeId": SCOPE_ID, "selection": "synthetic Korean documents authored by the live graph smoke", "initialCursor": None, "articleXPath": None,
                        "timestampLimitations": ["authored synthetic fixtures; no real provider late-registration guarantee"]}],
            "grant": {"grantId": "operator-live-grant", "revision": "rights-1", "sourceId": SOURCE_ID, "enabled": True, "rights": "known",
                      "allowedOperations": ["read", "store", "quote-display", "model-send"], "recipients": recipients, "purposes": purposes,
                      "evidence": ["operator-owned synthetic documents authored by live_graph_smoke.py; no real publisher content"], "expiresAt": None}}]}
        self.sources_bytes = cj(registry)
        self.registry = self.root / "sources.json"
        write_private(self.registry, self.sources_bytes)

    def manifest(self) -> tuple[Path, list[dict]]:
        items, documents = [], {}
        for index, (name, title, texts, published) in enumerate(DOCUMENTS):
            body = ("<html><body><article>" + "".join(f"<p>{htmllib.escape(t, quote=False)}</p>" for t in texts) + "</article></body></html>").encode("utf-8")
            file = f"{self.run_id}-{name}.bin"
            write_private(self.root / "inputs" / file, body)
            documents[f"d{index}"] = {"file": file, "sha256": sha(body)}
            items.append({"candidateId": f"c{index}", "supplierDocumentId": f"live-{name}", "url": f"https://example.invalid/{self.run_id}/{name}", "bodyRef": f"d{index}",
                          "mediaType": "text/html", "title": title, "publishedAt": published, "modifiedAt": None, "sourceRevision": None})
        page_file = f"{self.run_id}-page-0.json"
        page = cj({"items": items, "more": False, "nextCursor": None})
        write_private(self.root / "inputs" / page_file, page)
        manifest = {"schemaVersion": INGESTION_SCHEMA, "sourceId": SOURCE_ID, "scopeId": SCOPE_ID, "documents": documents,
                    "pages": [{"pageId": "page-0", "cursor": None, "response": {"file": page_file, "sha256": sha(page)}, "status": "ok", "nextCursor": None,
                               "terminal": True, "coverageThrough": None}]}
        path = self.root / "live-manifest.json"
        write_private(path, cj(manifest))
        return path, items

    def ingest(self) -> list[dict]:
        self.stage = "ingest"
        manifest, _ = self.manifest()
        round_id = f"{self.run_id}-round"
        request = {"schemaVersion": INGESTION_SCHEMA, "roundId": round_id, "sourceId": SOURCE_ID, "scopeId": SCOPE_ID, "window": None, "checkpointRevision": 0,
                   "fixtureManifestHash": sha(manifest.read_bytes()), "cleanerVersion": "exact-copy-1"}
        out = self.cli("ingest", "ingest", ["run", "--state-dir", str(self.root / "ingestion"), "--sources", str(self.registry), "--fixture-manifest", str(manifest)],
                       request, self.base_env())
        self.check("native ingestion completed with every synthetic document text-ready", out["state"] == "complete" and out["counts"]["textReady"] == len(DOCUMENTS), "offline-local")
        refs = [{"roundId": round_id, "sourceId": SOURCE_ID, "page": r["page"], "ordinal": r["ordinal"], "documentId": r["documentId"], "rawVersion": r["rawVersion"],
                 "documentVersion": r["documentVersion"]} for r in sorted(out["documentRefs"], key=lambda r: (r["page"], r["ordinal"]))]
        self.check("two distinct prepared documents", len(refs) == len(DOCUMENTS) and len({r["documentId"] for r in refs}) == len(DOCUMENTS), "offline-local")
        self.stages["ingest"] = {"documents": len(refs), "textReady": out["counts"]["textReady"], "seconds": self.timings["ingest"], "source": "synthetic authored files"}
        return refs

    def snapshot(self, prior_ref: dict) -> dict:
        """The prior (snapshot) event: an authored member mention grounded on the exact prepared text of the second synthetic document. It is operator
        seed state, NOT an answer to any model request."""
        from zoop_ai_pipeline import extraction_replay as analysis
        export = self.cli("ingest-export", "ingest", ["export", "--state-dir", str(self.root / "ingestion"), "--sources", str(self.registry)],
                          {"schemaVersion": INGESTION_SCHEMA, **prior_ref}, self.base_env())
        article = analysis.article(export, True)
        quote = PRIOR_TEXT[0]
        start = article.body.find(quote)
        self.check("authored snapshot quote is exact prepared text", start >= 0 and article.body.count(quote) == 1, "offline-local")
        mention = {"mention_id": "m-prior", "article_id": article.article_id, "article_version": article.version, "title": "가상전자 신규 공장 증설 발표",
                   "event_type": "facility_expansion", "action": "배터리 셀 신규 공장 증설 발표", "target": "배터리 셀 공장", "event_time": "2026-09-15", "period": None,
                   "assertion_status": "announced", "participants": [{"company_id": "LIVE-ELEC", "name": "가상전자", "role": "issuer"}],
                   "evidence": [{"article_id": article.article_id, "article_version": article.version, "quote": quote, "start": start, "end": start + len(quote)}],
                   "keywords": [], "background": False, "countries": []}
        return {"revision": "live-smoke-snapshot-1", "events": [{"eventId": SNAPSHOT_EVENT, "revision": "rev-1", "members": [{"observation": prior_ref, "mention": mention}]}]}

    # ---- ledgers / receipts -----------------------------------------------------------------------------------------------------

    def read_calls(self, label: str, state: str, database: str, job_id: str) -> list[dict]:
        directory = self.root / state
        wal = directory / f"{database}-wal"
        if wal.exists() and wal.stat().st_size > 0:
            raise Failure(self.stage, f"{label}_ledger_hot_wal")
        connection = sqlite3.connect((directory / database).as_uri() + "?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("SELECT attempt_id, stage, ref, state, response, verdict, started_at, received_at FROM calls WHERE job_id=? ORDER BY started_at, attempt_id",
                                      (job_id,)).fetchall()
        finally:
            connection.close()
        calls = []
        for index, row in enumerate(rows):
            receipt = json.loads(row["response"]) if row["response"] else None
            latency = None
            try:
                latency = round((datetime.fromisoformat(row["received_at"]) - datetime.fromisoformat(row["started_at"])).total_seconds() * 1000)
            except (TypeError, ValueError):
                pass
            call = {"job": label, "index": index, "stage": row["stage"], "ref": row["ref"], "state": row["state"], "verdict": row["verdict"], "attemptId": row["attempt_id"],
                    "startedAt": row["started_at"], "receivedAt": row["received_at"], "latencyMs": latency, "receipt": receipt}
            calls.append(call)
            write_private(self.root / "private" / "receipts" / f"{label}-{index:03d}-{row['stage']}-{sha(row['attempt_id'].encode())[:8]}.json", cj(call))
        self.calls[label] = calls
        return calls

    def soft_read_calls(self, label: str, state: str, database: str, job_id: str) -> None:
        """Read the ledger after a live child ended, however it ended. A killed child may leave a hot WAL: then the ledger is reported unreadable, not guessed."""
        if not (self.root / state / database).exists():
            return
        try:
            self.read_calls(label, state, database, job_id)
        except (Failure, sqlite3.Error, OSError, ValueError):
            self.stages.setdefault("ledgersNotReadable", []).append(label)

    def require_calls(self, label: str) -> list[dict]:
        if label not in self.calls:
            raise Failure(self.stage, f"{label}_ledger_not_readable")
        return self.calls[label]

    def budget_state(self) -> dict:
        """Totals of the shared budget ledger (binds the ceilings the same way a send would; a refusal is a Failure with the budget's own code)."""
        from zoop_ai_pipeline.live_budget import BudgetError
        try:
            return self.budget.snapshot()
        except BudgetError as exc:
            raise Failure("budget", exc.code) from None

    def verify_calls(self, label: str, calls: list[dict], result: dict) -> None:
        """Truthful live accounting from the stored raw receipts (not from the CLI summary alone)."""
        identity = self.runtime.binding()["identity"]
        problems: list[str] = []
        received = [c for c in calls if c["state"] == "received"]
        for call in received:
            receipt, stage = call["receipt"], call["stage"]
            wanted = MODEL if stage in GENERATION_STAGES else JEV
            usage = (receipt or {}).get("usage") or {}
            reported = ((receipt or {}).get("model") or {}).get("reported")
            http = (receipt or {}).get("http") or {}
            checks = {
                "format": (receipt or {}).get("format") == "zoop-live-receipt-1",
                "binding": (receipt or {}).get("bindingIdentity") == identity,
                "recipientPurpose": (receipt or {}).get("recipient") == self.runtime.recipient(stage) and (receipt or {}).get("purpose") == self.runtime.purpose(stage),
                "http200": http.get("status") == 200 and http.get("truncated") is False,
                "bodyHash": http.get("bodySha256") == sha((http.get("bodyText") or "").encode("utf-8")),
                "modelRequested": ((receipt or {}).get("model") or {}).get("requested") == wanted,
                "modelReported": isinstance(reported, str) and (reported == wanted or reported.startswith(wanted + "-")),
                # The generation provider always reports usage; a Jev reply may legitimately omit it (then the worst-case charge stays and is reported as unknown usage).
                "tokens": stage in VERIFY_STAGES or (type(usage.get("inputTokens")) is int and type(usage.get("outputTokens")) is int and usage["inputTokens"] > 0)}
            problems += [f"{stage}#{call['index']}:{name}" for name, ok in checks.items() if not ok]
        unreceipted = [c for c in calls if c["state"] == "started"]
        usage_block = result.get("usage") or {}
        if usage_block.get("executionMode") != "live" or result.get("provenance") != PROVENANCE:
            problems.append("mode_not_live_or_provenance_wrong")
        if usage_block.get("replayCalls", 0) != 0 or usage_block.get("startedWithoutReceipt", 0) != 0 or unreceipted:
            problems.append("replay_or_unreceipted_calls")
        if usage_block.get("providerCalls") != len(received) or any(c["state"] not in {"received", "unsent"} for c in calls):
            problems.append("call_count_mismatch")
        self.check(f"{label}: every call is a stored real receipt (200, requested/reported model, tokens, binding, purpose/recipient, body hash) and the mode is truthfully live",
                   not problems, "live-provider", problems[:20])

    # ---- S2 / S3 ----------------------------------------------------------------------------------------------------------------

    def s2_run(self, refs: list[dict]) -> dict:
        self.stage = "s2"
        job = f"{self.run_id}-s2"
        request = {"schemaVersion": EXTRACTION_SCHEMA, "jobId": job, "provenance": PROVENANCE, "promptVersion": "zoop-live-graph-smoke-prompt-1", "incoming": refs[0],
                   "catalogue": CATALOGUE, "snapshot": self.snapshot(refs[1]), "topic": {"producerVersion": "zoop-topic-replay-producer-1"}}
        argv = ["run", "--state-dir", str(self.root / "extraction"), "--ingestion-state-dir", str(self.root / "ingestion"), "--sources", str(self.registry), "--initial-only"]
        log("s2-live-run", job=job)
        try:
            out = self.cli("s2", "extract", argv, request, self.live_env(), timeout=self.args.child_timeout_seconds, keep=True)
        finally:
            self.soft_read_calls("s2", "extraction", "extraction.sqlite3", job)
        self.s2 = out
        failure = out.get("failure")
        self.stages["s2"] = {"jobId": job, "state": out.get("state"), "phase": out.get("phase"), "failureCode": (failure or {}).get("code"),
                             "providerCalls": (out.get("usage") or {}).get("providerCalls"), "seconds": self.timings.get("s2")}
        self.check("S2 live job is ready (state/delivery current)", out["state"] == "ready" and out["delivery"]["status"] == "current", "live-provider",
                   {"state": out.get("state"), "phase": out.get("phase"), "failureCode": (failure or {}).get("code"), "failureDetail": self.safe_detail((failure or {}).get("detail"))})
        self.verify_calls("s2", self.require_calls("s2"), out)
        counts = out["counts"]
        stage_counts = Counter(c["stage"] for c in self.calls["s2"])
        self.stages["s2"] = {"jobId": job, "inputDigest": out["inputDigest"], "state": out["state"], "mode": out["usage"]["executionMode"], "provenance": out["provenance"],
                             "events": counts["eventCandidates"], "comparisons": counts["comparisons"], "effectiveRelations": counts["effectiveRelations"],
                             "dispositions": counts["dispositions"], "topicCandidates": counts["topicCandidates"], "callsByStage": dict(stage_counts),
                             "providerCalls": out["usage"]["providerCalls"], "seconds": self.timings["s2"]}
        return out

    def s3_run(self) -> dict:
        self.stage = "s3"
        job = f"{self.run_id}-s3"
        request = {"schemaVersion": RELATION_SCHEMA, "jobId": job, "provenance": PROVENANCE, "upstream": {"jobId": self.s2["jobId"], "inputDigest": self.s2["inputDigest"]}}
        common = ["--state-dir", str(self.root / "relation"), "--extraction-state-dir", str(self.root / "extraction"), "--ingestion-state-dir", str(self.root / "ingestion"),
                  "--sources", str(self.registry)]
        env = self.live_env()
        log("s3-live-submit", job=job)
        self.cli("s3-submit", "relation", ["submit", *common], request, env)
        log("s3-live-resume", job=job)
        try:
            out = self.cli("s3", "relation", ["resume", *common, "--initial-only"], {"schemaVersion": RELATION_SCHEMA, "jobId": job}, env,
                           timeout=self.args.child_timeout_seconds, keep=True)
        finally:
            self.soft_read_calls("s3", "relation", "relation.sqlite3", job)
        self.s3, self.s3_common, self.s3_job = out, common, job
        failure = out.get("failure")
        self.stages["s3"] = {"jobId": job, "state": out.get("state"), "phase": out.get("phase"), "failureCode": (failure or {}).get("code"),
                             "providerCalls": (out.get("usage") or {}).get("providerCalls"), "seconds": self.timings.get("s3")}
        self.check("S3 live job is ready (state/delivery current)", out["state"] == "ready" and out.get("delivery", {}).get("status") == "current", "live-provider",
                   {"state": out.get("state"), "phase": out.get("phase"), "failureCode": (failure or {}).get("code"), "failureDetail": self.safe_detail((failure or {}).get("detail"))})
        self.verify_calls("s3", self.require_calls("s3"), out)
        self.stages["s3"] = self.s3_summary(out)
        return out

    def s3_summary(self, out: dict) -> dict:
        relations = []
        for r in out["relations"]:
            el = r["eligibility"]
            verdicts = [e for e in r["history"] if e["kind"] == "verdict"]
            claims = Counter(c.get("verdict") for e in verdicts for c in (e.get("claims") or []) if isinstance(c, dict))
            relations.append({"relationCandidateId": r["relationCandidateId"], "type": r["type"], "connection": r["connection"], "precheck": r["precheck"]["state"],
                              "eligibility": el["status"], "revision": el["revision"], "reviewPending": el["reviewPending"],
                              "reasonCodes": sorted({x.get("code") for x in el["reasons"] if isinstance(x, dict)}), "approvalBasis": (el["approvalBasis"] or {}).get("kind"),
                              "verifierCalled": any(e.get("verifier") == "called" for e in verdicts), "claimVerdicts": dict(claims),
                              "impact": r["impact"]["status"], "impactCandidates": len(r["impact"]["candidates"])})
        return {"jobId": out["jobId"], "state": out["state"], "mode": out["usage"]["executionMode"], "provenance": out["provenance"], "counts": out["counts"],
                "providerCalls": out["usage"]["providerCalls"], "callsByStage": dict(Counter(c["stage"] for c in self.calls.get("s3", []))),
                "relations": relations, "seconds": self.timings.get("s3")}

    # ---- manual approval (only a genuine Jev HOLD) ------------------------------------------------------------------------------

    def genuine_holds(self, out: dict) -> list[dict]:
        verified = {c["ref"] for c in self.calls.get("s3", []) if c["stage"] == "verify-relation" and c["state"] == "received"}
        found = []
        for r in out["relations"]:
            el = r["eligibility"]
            verdicts = [e for e in r["history"] if e["kind"] == "verdict"]
            rc = r["relationCandidateId"]
            if (el["status"] == "hold" and not el["reviewPending"] and r["precheck"]["state"] == "pending" and verdicts and verdicts[-1].get("verifier") == "called"
                    and verdicts[-1].get("claims") and verdicts[-1].get("eligibility") == "hold" and any(ref == rc or ref.startswith(rc + "|") for ref in verified)):
                found.append(r)
        return sorted(found, key=lambda r: r["relationCandidateId"])

    def approve(self, holds: list[dict]) -> dict | None:
        self.stage = "manual-approval"
        wanted = self.args.approve_relation
        if wanted is not None and wanted not in {h["relationCandidateId"] for h in holds}:
            raise Failure("manual-approval", "approve_relation_is_not_a_genuine_jev_hold")
        target = next(h for h in holds if wanted in (None, h["relationCandidateId"]))
        rc, revision = target["relationCandidateId"], target["eligibility"]["revision"]
        before = {r["relationCandidateId"]: (r["eligibility"]["status"], r["eligibility"]["revision"]) for r in self.s3["relations"]}
        calls_before, usage_before = len(self.calls["s3"]), self.s3["usage"]["providerCalls"]
        budget_before = self.budget_state()
        review = {"schemaVersion": RELATION_SCHEMA, "jobId": self.s3_job, "relationCandidateId": rc, "expectedRevision": revision, "decision": "allow",
                  "reviewer": REVIEWER, "note": NOTE}
        log("manual-approval", relation=rc)
        out = self.cli("s3-review", "relation", ["review", *self.s3_common], review, self.base_env(), keep=True)   # no model key in this process' environment
        after = next(r for r in out["relations"] if r["relationCandidateId"] == rc)
        basis = after["eligibility"]["approvalBasis"] or {}
        calls_after = self.read_calls("s3", "relation", "relation.sqlite3", self.s3_job)
        budget_after = self.budget_state()
        self.check("scripted manual approval made the HOLD effective with operator-final-approval basis (reviewer, revision+1, decidedAt) and no review-pending",
                   after["eligibility"]["status"] == "eligible" and not after["eligibility"]["reviewPending"] and basis.get("kind") == "operator-final-approval"
                   and basis.get("reviewer") == REVIEWER and basis.get("revision") == revision + 1 and bool(basis.get("decidedAt"))
                   and after["history"][-1].get("kind") == "review" and after["history"][-1].get("effect") == "approved", "offline-local",
                   {"status": after["eligibility"]["status"], "basisKind": basis.get("kind")})
        self.check("manual approval caused NO model call (result calls, ledger rows and budget reservations unchanged)",
                   out["usage"]["providerCalls"] == usage_before and len(calls_after) == calls_before and budget_after == budget_before, "offline-local",
                   {"usage": out["usage"]["providerCalls"], "ledgerRows": len(calls_after), "budgetUnchanged": budget_after == budget_before})
        self.check("manual approval created no impact candidate for the approved relation and changed no other relation",
                   after["impact"]["candidates"] == [] and after["impact"]["status"] in {"not-applicable", "pending"}
                   and all(before[r["relationCandidateId"]] == (r["eligibility"]["status"], r["eligibility"]["revision"]) for r in out["relations"] if r["relationCandidateId"] != rc),
                   "offline-local", {"impact": after["impact"]["status"]})
        self.s3 = out
        self.stages["s3"] = self.s3_summary(out)
        self.coverage["manualApproval"] = {"status": "exercised", "relationCandidateId": rc, "reviewer": REVIEWER, "actor": "scripted synthetic test operator (not a human)",
                                           "approvalBasisKind": basis.get("kind"), "revision": basis.get("revision"), "modelCallsAdded": 0,
                                           "otherGenuineHoldsLeftUntouched": len(holds) - 1}
        return after

    # ---- offline negatives on the REAL live ledgers (never reported as live) --------------------------------------------------

    def review_negatives(self) -> None:
        self.stage = "offline-review-negatives"
        eligible = next((r for r in self.s3["relations"] if r["eligibility"]["status"] == "eligible"), None)
        if eligible is None:
            self.coverage["offlineReviewNegatives"] = "skipped: no eligible relation"
            return
        body = {"schemaVersion": RELATION_SCHEMA, "jobId": self.s3_job, "relationCandidateId": eligible["relationCandidateId"], "decision": "allow", "reviewer": REVIEWER,
                "note": NOTE}
        revision = eligible["eligibility"]["revision"]
        self.cli_error("review of a stale revision", "relation", ["review", *self.s3_common], {**body, "expectedRevision": revision + 5}, self.base_env(), "review_revision_conflict")
        self.cli_error("review allow of an already-eligible relation", "relation", ["review", *self.s3_common], {**body, "expectedRevision": revision}, self.base_env(),
                       "review_target_not_hold")
        self.coverage["offlineReviewNegatives"] = "passed (offline CLI proofs on the live ledger; not live verdicts)"

    # ---- graph ------------------------------------------------------------------------------------------------------------------

    def canonical_registry(self, s3: dict) -> dict:
        """One synthetic scripted-operator decision per endpoint that an ELIGIBLE, not-review-pending relation actually uses (subject, object, path steps), derived
        only from the S3 result the models produced. No merges: every endpoint is its own canonical identity."""
        used: set[tuple[str, str]] = set()
        for r in s3["relations"]:
            el = r["eligibility"]
            if el["status"] != "eligible" or el["reviewPending"]:
                continue
            for e in (r["subject"], r["object"], *[s[role] for s in r["path"] for role in ("subject", "object")]):
                used.add((e["kind"], e["ref"]))
        ident = {"company": lambda ref: "co-" + ref.lower(), "event": lambda ref: "event:" + ref, "topic": lambda ref: "topic:" + ref}
        upstream = {"jobId": self.s2["jobId"], "inputDigest": self.s2["inputDigest"]}
        return {"schemaVersion": CANONICAL_SCHEMA, "entries": [
            {"upstream": upstream, "kind": kind, "ref": ref, "canonicalId": ident[kind](ref), "decisionRef": f"{self.run_id}-scripted-synthetic-decision:{kind}"}
            for kind, ref in sorted(used)]}

    def write_canonical(self, document: dict | bytes) -> None:
        raw = document if isinstance(document, bytes) else cj(document)
        write_private(self.root / "next-canonical.json", raw)
        os.replace(self.root / "next-canonical.json", self.root / "canonical.json")

    def graph_argv(self, command: str) -> list[str]:
        argv = [command, "--state-dir", str(self.root / "graph")]
        if command in {"freeze", "project", "read", "focus"}:
            argv += ["--relation-state-dir", str(self.root / "relation"), "--extraction-state-dir", str(self.root / "extraction"),
                     "--ingestion-state-dir", str(self.root / "ingestion"), "--sources", str(self.registry), "--canonical", str(self.root / "canonical.json")]
        if command == "init":
            argv += ["--graph-uri", self.graph_uri]
        return argv

    def graph(self, label: str, command: str, request: dict) -> dict:
        return self.cli(label, "graph", self.graph_argv(command), request, self.graph_env())

    def graph_error(self, label: str, command: str, request: dict, code: str) -> dict:
        """A deliberately refused graph command (exit 2 with exactly this error or withheld code). Offline proof, never reported as live."""
        child = subprocess.run([str(self.bin / TOOLS["graph"]), *self.graph_argv(command)], input=cj(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=self.graph_env(), cwd=self.root, timeout=300)
        self.stderr_bytes += len(child.stderr)
        try:
            parsed = json.loads(child.stdout)
        except ValueError:
            raise Failure(self.stage, f"{label}_output_not_json") from None
        got = ((parsed.get("error") or {}).get("code")) or ((parsed.get("delivery") or {}).get("code"))
        self.check(f"{label}: refused with {code}", child.returncode == 2 and got == code, "offline-local", {"exit": child.returncode, "code": got})
        return parsed

    def sel(self, name: str) -> dict:
        return {"schemaVersion": GRAPH_SCHEMA, "versionId": f"{self.run_id}-{name}"}

    @staticmethod
    def distances(edges: list[dict], start: str) -> dict[str, int]:
        adjacent: dict[str, set[str]] = {}
        for e in edges:
            a, b = e["subject"]["id"], e["object"]["id"]
            adjacent.setdefault(a, set()).add(b)
            adjacent.setdefault(b, set()).add(a)
        seen, queue = {start: 0}, deque([start])
        while queue:
            node = queue.popleft()
            for other in sorted(adjacent.get(node, ())):
                if other not in seen:
                    seen[other] = seen[node] + 1
                    queue.append(other)
        return seen

    def neo_oracle(self):
        from neo4j import READ_ACCESS, GraphDatabase
        driver = GraphDatabase.driver(self.graph_uri, auth=self.graph_auth)

        def query(cypher: str, **params: Any) -> list[dict]:
            with driver.session(database=self.args.graph_database, default_access_mode=READ_ACCESS) as session:
                return [record.data() for record in session.run(cypher, params)]
        return driver, query

    def project_version(self, name: str, s3_job: dict, *, approvals: dict[str, int]) -> dict:
        """freeze -> project -> read -> focus -> recover -> idempotent repeats for ONE version, checked against the S3 result and a read-only Neo4j oracle."""
        self.stage = f"graph-{name}"
        sel = self.sel(name)
        relation = {"jobId": self.s3_job, "inputDigest": s3_job["inputDigest"]}
        frozen = self.graph(f"{name}-freeze", "freeze", {**sel, "relation": relation})
        self.created_versions.append(sel["versionId"])
        self.check(f"{name}: freeze pins the exact audit counts and approval kinds", frozen["state"] == "frozen" and frozen["publication"] == "not-published"
                   and frozen["audit"]["approvals"] == {"automatic": approvals["automatic"], "operatorFinal": approvals["operatorFinal"]}
                   and frozen["audit"]["projectedCandidates"] == approvals["automatic"] + approvals["operatorFinal"] and frozen["usage"] == {"providerCalls": 0, "modelCalls": 0},
                   "offline-local", {"audit": frozen.get("audit")})
        self.check(f"{name}: freeze is idempotent", self.graph(f"{name}-freeze-again", "freeze", {**sel, "relation": relation}) == frozen, "offline-local")
        ready = self.graph(f"{name}-project", "project", sel)
        self.check(f"{name}: project committed one transaction (ready, not published)", ready["state"] == "ready" and ready["publication"] == "not-published"
                   and ready["attempts"] == [{"n": 1, "outcome": "committed", "code": None}], "neo4j", {"state": ready.get("state"), "attempts": ready.get("attempts")})
        self.check(f"{name}: project is idempotent", self.graph(f"{name}-project-again", "project", sel) == ready, "neo4j")
        read = self.graph(f"{name}-read", "read", sel)
        nodes, edges = read["graph"]["nodes"], read["graph"]["edges"]
        self.check(f"{name}: read verifies the stored version against the plan (marker matched, no model use)", read["delivery"]["status"] == "current"
                   and read["verification"]["marker"] == "matched" and read["verification"]["nodes"] == len(nodes) and read["verification"]["edges"] == len(edges)
                   and read["usage"] == {"providerCalls": 0, "modelCalls": 0} and read["digests"] == ready["digests"], "neo4j")
        kinds = Counter(a["kind"] for e in edges for a in e["sourceApprovals"])
        self.check(f"{name}: every projected relation carries its per-source approval kind exactly as pinned (automatic {approvals['automatic']}, operator-final {approvals['operatorFinal']})",
                   kinds.get("automatic-verifier", 0) == approvals["automatic"] and kinds.get("operator-final-approval", 0) == approvals["operatorFinal"], "neo4j", dict(kinds))
        companies = sorted((n["id"] for n in nodes if n["kind"] == "company"), key=lambda c: (-sum(c in (e["subject"]["id"], e["object"]["id"]) for e in edges), c))
        self.check(f"{name}: the projected graph has at least one company", bool(companies), "neo4j")
        center = companies[0]
        for depth in (1, 2, 3):
            focus = self.graph(f"{name}-focus-{depth}", "focus", {**sel, "companyId": center, "depth": depth})
            dist = self.distances(edges, center)
            want_nodes = {n: d for n, d in dist.items() if d <= depth}
            want_edges = sorted(e["relationId"] for e in edges if min(dist.get(e["subject"]["id"], 10**9), dist.get(e["object"]["id"], 10**9)) < depth)
            self.check(f"{name}: focus depth {depth} equals the neighbourhood computed from the verified full read",
                       focus["focus"] == {"companyId": center, "depth": depth, "found": True} and {n["id"]: n["distance"] for n in focus["graph"]["nodes"]} == want_nodes
                       and sorted(e["relationId"] for e in focus["graph"]["edges"]) == want_edges, "neo4j", {"depth": depth})
        absent = self.graph(f"{name}-focus-absent", "focus", {**sel, "companyId": "co-absent-synthetic", "depth": 1})
        self.check(f"{name}: an absent company is found:false with an empty graph", absent["focus"]["found"] is False and absent["graph"] == {"nodes": [], "edges": []}, "neo4j")
        self.graph_error(f"{name}: recover of a ready version", "recover", sel, "recovery_not_required")
        self.check(f"{name}: inspect agrees (ready, next read)", self.graph(f"{name}-inspect", "inspect", sel)["state"] == "ready", "neo4j")
        driver, query = self.neo_oracle()
        try:
            version = sel["versionId"]
            stored_nodes = query("MATCH (n) WHERE n.v = $v RETURN count(n) AS c", v=version)[0]["c"]
            stored_edges = query("MATCH ()-[e]->() WHERE e.v = $v RETURN count(e) AS c", v=version)[0]["c"]
            marker = query("MATCH (m:ZgVersion {versionId: $v}) RETURN m.nodeCount AS n, m.edgeCount AS e, m.graphDigest AS g, m.payloadDigest AS p", v=version)
            self.check(f"{name}: read-only Neo4j oracle: stored nodes/edges/marker equal the verified read and the ledger digests",
                       stored_nodes == len(nodes) and stored_edges == len(edges) and len(marker) == 1 and marker[0] == {"n": len(nodes), "e": len(edges), "g": ready["digests"]["graph"],
                                                                                                                  "p": ready["digests"]["payload"]}, "neo4j",
                       {"nodes": stored_nodes, "edges": stored_edges})
        finally:
            driver.close()
        return {"versionId": version, "nodes": len(nodes), "edges": len(edges), "evidence": len(read["evidence"]), "approvals": frozen["audit"]["approvals"],
                "edgeTypes": dict(Counter(e["type"] for e in edges)), "focusCompany": center, "digests": ready["digests"],
                "s3ReviewDigestStillMatches": read["current"]["s3ReviewDigestMatches"], "canonicalEntries": frozen["canonical"]["entries"], "attempts": ready["attempts"]}

    @staticmethod
    def effective(s3: dict) -> tuple[list[dict], list[dict], list[dict]]:
        """(all projectable, automatic, operator-final) relations of an S3 result: eligible, not review-pending, by their effective approval basis."""
        eligible = [r for r in s3["relations"] if r["eligibility"]["status"] == "eligible" and not r["eligibility"]["reviewPending"]]
        kind = lambda r: (r["eligibility"]["approvalBasis"] or {}).get("kind")  # noqa: E731
        return eligible, [r for r in eligible if kind(r) == "automatic-verifier"], [r for r in eligible if kind(r) == "operator-final-approval"]

    def graph_phase(self, holds: list[dict]) -> None:
        """init -> offline canonical negative -> `auto` version (everything the independent verifier made eligible) -> [scripted approval -> `manual` version].

        The automatic version is frozen and projected BEFORE any approval: a write is gated on the whole review state exactly as frozen, so a newer review
        state (the approval) calls for a NEW version, and the earlier immutable one stays readable."""
        self.stage = "graph-init"
        eligible, automatic, operator = self.effective(self.s3)
        self.check("something is projectable: an eligible relation, or a genuine Jev HOLD to approve", bool(eligible) or bool(holds), "live-provider",
                   {"eligibility": self.s3["counts"]["eligibility"]})
        init = {"schemaVersion": GRAPH_SCHEMA, "storeId": f"{self.run_id}-store", "database": self.args.graph_database}
        driver, query = self.neo_oracle()
        try:
            self.check("neo4j database is empty before init (this script never wipes)", query("MATCH (n) RETURN count(n) AS c")[0]["c"] == 0, "neo4j")
        finally:
            driver.close()
        out = self.graph("init", "init", init)
        self.check("init bound one store (schema objects created, usage zero)", out["store"]["state"] == "bound" and out["usage"] == {"providerCalls": 0, "modelCalls": 0}, "neo4j")
        self.check("init is idempotent", self.graph("init-again", "init", init)["store"] == out["store"], "neo4j")
        self.write_canonical(self.canonical_registry(self.s3))
        self.canonical_negative()
        versions: dict[str, Any] = {}
        if eligible:
            versions["auto"] = self.project_version("auto", self.s3, approvals={"automatic": len(automatic), "operatorFinal": len(operator)})
        if holds:
            approved = self.approve(holds)
            eligible, automatic, operator = self.effective(self.s3)
            self.check("the approved relation is the only operator-final-approval relation", [r["relationCandidateId"] for r in operator] == [approved["relationCandidateId"]],
                       "offline-local")
            self.write_canonical(self.canonical_registry(self.s3))   # new endpoints may now be used; every earlier decision stays byte-identical
            versions["manual"] = self.project_version("manual", self.s3, approvals={"automatic": len(automatic), "operatorFinal": len(operator)})
            if "auto" in versions:
                self.stage = "graph-auto-after-approval"
                again = self.graph("auto-read-after-approval", "read", self.sel("auto"))
                self.check("the earlier automatic version stays immutable and readable after the approval (its S3 review digest no longer matches: a newer state needs a new version)",
                           again["delivery"]["status"] == "current" and again["current"]["s3ReviewDigestMatches"] is False and again["digests"] == versions["auto"]["digests"], "neo4j")
        self.stages["graph"] = {"storeId": init["storeId"], "database": init["database"], "versions": versions}
        self.stage = "graph-final"
        driver, query = self.neo_oracle()
        try:
            total = query("MATCH (n) RETURN count(n) AS c")[0]["c"]
            stores = query("MATCH (s:ZgStore) RETURN s.storeId AS id")
            expected = 1 + sum(v["nodes"] + 1 for v in versions.values())
            self.check("neo4j holds exactly one store plus the planned version nodes and markers (nothing else; nothing published)", total == expected and stores == [{"id": init["storeId"]}],
                       "neo4j", {"total": total, "expected": expected})
        finally:
            driver.close()

    def stale_authority_proof(self) -> None:
        """Offline proof on a projected live version: a changed source grant revision withholds the read; restoring it serves the same version again."""
        self.stage = "offline-stale-authority"
        name = "manual" if "manual" in self.stages["graph"]["versions"] else "auto"
        if name not in self.stages["graph"]["versions"]:
            return
        sel = self.sel(name)
        original = self.sources_bytes
        document = json.loads(original)
        document["sources"][0]["grant"]["revision"] = "rights-2"
        try:
            write_private(self.root / "next-sources.json", cj(document))
            os.replace(self.root / "next-sources.json", self.registry)
            self.graph_error("read after a source grant revision change", "read", sel, "grant_revision_changed")
        finally:
            write_private(self.root / "next-sources.json", original)
            os.replace(self.root / "next-sources.json", self.registry)
        self.check("restoring the exact grant serves the version again", self.graph(f"{name}-read-restored", "read", sel)["delivery"]["status"] == "current", "offline-local")
        self.coverage["offlineStaleAuthority"] = "passed (offline CLI proof; grant revision change withholds, restore serves)"

    def canonical_negative(self) -> None:
        self.stage = "offline-canonical-negative"
        registry = self.canonical_registry(self.s3)
        if len(registry["entries"]) < 1:
            return
        self.write_canonical({**registry, "entries": registry["entries"][1:]})
        try:
            self.graph_error("freeze with an unresolved canonical endpoint", "freeze", {**self.sel("bad-unresolved"), "relation": {"jobId": self.s3_job, "inputDigest": self.s3["inputDigest"]}},
                             "canonical_mapping_unresolved")
            self.graph_error("the refused freeze wrote no version", "inspect", self.sel("bad-unresolved"), "version_not_found")
        finally:
            self.write_canonical(registry)
        self.coverage["offlineCanonicalNegative"] = "passed (offline CLI proof; an unresolved mapping fails the whole freeze with no version row)"

    # ---- orchestration ----------------------------------------------------------------------------------------------------------

    def execute(self) -> None:
        self.gate()
        a = self.args
        if a.check:
            # --check creates nothing: `preflight` never touches a ledger, and the graph state dir named here is the (absent) future one.
            self.neo_preflight()
            self.stages["plan"] = self.plan()
            return
        if not a.live:
            raise Failure("gate", "live_flag_required_for_a_paid_run")
        self.root.mkdir(mode=0o700)
        os.chmod(self.root, 0o700)
        write_private(self.root / "README.private.txt", b"Private live graph smoke output: synthetic raw documents, raw provider receipts and ledgers. Remove with rm -rf after review.\n")
        self.write_world()
        self.neo_preflight()   # before any spend: a broken graph target must not cost model money
        self.budget_before = self.budget_state()
        self.stages["budgetBefore"] = self.budget_before
        refs = self.ingest()
        self.s2_run(refs)
        self.s3_run()
        holds = self.genuine_holds(self.s3)
        eligibility = self.s3["counts"]["eligibility"]
        self.coverage["liveVerdicts"] = {"eligibleAutomatic": eligibility["eligible"], "hold": eligibility["hold"], "reject": eligibility["reject"], "pending": eligibility["pending"],
                                         "note": "verdicts are the models' own; none was manufactured or weakened"}
        self.coverage["genuineJevHolds"] = {"count": len(holds), "relationCandidateIds": [h["relationCandidateId"] for h in holds]}
        if not a.exercise_manual_approval:
            self.coverage["manualApproval"] = {"status": "not-requested", "genuineHoldsAvailable": len(holds)}
        elif not holds:
            self.coverage["manualApproval"] = {"status": "coverage-gap", "reason": "no genuine Jev HOLD with a passing deterministic gate occurred; the automatic eligible "
                                                                                    "path is proven; a separate bounded case can be run by Main"}
        self.review_negatives()
        self.graph_phase(holds if a.exercise_manual_approval else [])
        self.stale_authority_proof()

    def plan(self) -> dict:
        return {"documents": [{"name": n, "paragraphs": len(t)} for n, _, t, _ in DOCUMENTS], "companies": len(COMPANIES), "snapshotEvents": 1,
                "s2Stages": ["extract", "compare (incoming event x snapshot event)", "topic"], "s3Stages": ["relation", "verify-relation (Jev)", "impact", "verify-impact (Jev)"],
                "graph": ["init", "freeze", "project", "read", "focus depth 1-3", "recover", "idempotent repeats", "read-only Neo4j oracle"],
                "estimatedCalls": "data dependent: S2 about 3-4, S3 about 2 per relation candidate plus impact; capped by ZOOP_AI_PIPELINE_LIVE_MAX_CALLS and the USD ceiling",
                "noSpendInCheckMode": True}

    # ---- summary ----------------------------------------------------------------------------------------------------------------

    def finalize(self) -> dict:
        if self.budget is not None and self.budget_before is not None:
            try:
                self.budget_after = self.budget.snapshot()
            except Exception:  # noqa: BLE001 - the summary must still be produced
                self.budget_after = {"error": "budget_snapshot_failed"}
        all_calls = [c for label in ("s2", "s3") for c in self.calls.get(label, [])]
        received = [c for c in all_calls if c["state"] == "received"]
        receipts = [c["receipt"] for c in received if c["receipt"]]
        estimated = [Decimal(r["cost"]["estimatedUsd"]) for r in receipts if (r.get("cost") or {}).get("estimatedUsd") is not None]
        charged = sum((Decimal(r["cost"]["chargedUsd"]) for r in receipts), Decimal(0))
        reserved = sum((Decimal(r["cost"]["reservedUsd"]) for r in receipts), Decimal(0))
        unknown = [c for c in all_calls if c["state"] == "started"]
        per_stage: dict[str, dict] = {}
        for call in all_calls:
            slot = per_stage.setdefault(call["stage"], {"calls": 0, "latenciesMs": []})
            slot["calls"] += 1
            if call["latencyMs"] is not None:
                slot["latenciesMs"].append(call["latencyMs"])
        latency = {stage: {"calls": s["calls"], "minMs": min(s["latenciesMs"], default=None), "medianMs": int(statistics.median(s["latenciesMs"])) if s["latenciesMs"] else None,
                           "maxMs": max(s["latenciesMs"], default=None), "totalMs": sum(s["latenciesMs"])} for stage, s in sorted(per_stage.items())}
        if self.budget_before and self.budget_after and "error" not in self.budget_after:
            created = self.budget_after["calls"] - self.budget_before["calls"]
            self.budget_delta = {"reservationsCreated": created, "chargedUsd": usd(Decimal(self.budget_after["chargedUsd"]) - Decimal(self.budget_before["chargedUsd"])),
                                 "totalChargedUsd": self.budget_after["chargedUsd"], "maxUsd": self.budget_after["maxUsd"], "maxCalls": self.budget_after["maxCalls"],
                                 "states": self.budget_after["states"]}
            accounted = created == len(received) + len(unknown) and (bool(unknown) or Decimal(self.budget_delta["chargedUsd"]) == charged)
            self.checks.append({"name": "budget ledger equals the raw receipts (call count and charged USD)", "scope": "live-provider", "ok": bool(accounted)})
            if not accounted and self.failure is None:
                self.failure = {"stage": "accounting", "code": "budget_receipts_mismatch", "detail": {"reservations": created, "receipts": len(received), "unreceipted": len(unknown)}}
        else:
            self.budget_delta = None
        status = "failed" if self.failure else ("passed-with-coverage-gap" if (self.coverage.get("manualApproval") or {}).get("status") == "coverage-gap" else "passed")
        if self.args.check and not self.failure:
            status = "check-passed"
        summary = {
            "schemaVersion": SCHEMA, "status": status, "runId": self.run_id, "finishedAt": now_iso(), "wallSeconds": round(time.monotonic() - self.started, 1),
            "outputRoot": str(self.root), "failure": self.failure,
            "provenance": {"documents": "SYNTHETIC: authored in this script (no real news, publisher or company)", "models": "REAL provider calls (gpt-6-luna reasoning high; jev-1.14.0)"
                           if not self.args.check else "none (check mode)", "catalogueAndSnapshot": "synthetic operator seed state, not a model answer",
                           "canonicalDecisions": "scripted synthetic test operator, derived only from actually emitted S3 candidates (no merges)",
                           "manualApproval": "scripted synthetic test operator (not a human)" if (self.coverage.get("manualApproval") or {}).get("status") == "exercised" else "not exercised",
                           "providerEndpointsAreReal": self.provider_facts.get("realProviderEndpoints")},
            "config": self.provider_facts, "stages": self.stages,
            "calls": {"received": len(received), "unreceipted": len(unknown), "perStage": {s: v["calls"] for s, v in sorted(per_stage.items())}, "latency": latency,
                      "detail": [{"job": c["job"], "stage": c["stage"], "state": c["state"], "verdictCode": c["verdict"], "latencyMs": c["latencyMs"],
                                  "httpStatus": ((c["receipt"] or {}).get("http") or {}).get("status"),
                                  "modelReported": ((c["receipt"] or {}).get("model") or {}).get("reported"),
                                  "inputTokens": ((c["receipt"] or {}).get("usage") or {}).get("inputTokens"), "outputTokens": ((c["receipt"] or {}).get("usage") or {}).get("outputTokens"),
                                  "reasoningTokens": ((c["receipt"] or {}).get("usage") or {}).get("reasoningTokens"),
                                  "estimatedUsd": ((c["receipt"] or {}).get("cost") or {}).get("estimatedUsd")} for c in all_calls]},
            "cost": {"estimatedUsd": usd(sum(estimated, Decimal(0))) if len(estimated) == len(receipts) else None, "usageUnknownCalls": len(receipts) - len(estimated),
                     "chargedUsdFromReceipts": usd(charged), "worstCaseReservedUsdOfReceivedCalls": usd(reserved),
                     "unreceiptedCallsCharged": "worst case, amount unknown here (see budget ledger)" if unknown else "none",
                     "tier": "conservative long-context rates; an upper estimate, not the provider's invoice", "budget": self.budget_delta},
            "manualApprovalAndCoverage": self.coverage,
            "checks": {"total": len(self.checks), "failed": [c["name"] for c in self.checks if not c["ok"]], "byScope": dict(Counter(c["scope"] for c in self.checks)),
                       "list": [f"[{c['scope']}] {c['name']}" for c in self.checks]},
            "childStderrBytes": self.stderr_bytes, "timingsSeconds": self.timings,
            "privateArtifacts": {"receipts": str(self.root / "private" / "receipts"), "results": str(self.root / "private" / "results"), "mode": "dirs 0700, files 0600"},
            "cleanup": {"outputRoot": f"rm -rf {self.root}  (private synthetic raw documents, raw receipts, ledgers)", "budgetDir": "Main-owned; totals are cumulative; ceilings only decrease",
                        "neo4jContainer": "Main-owned; this script never wipes a database",
                        "neo4jTargeted": {"cypher": ("MATCH (n) WHERE n.v IN $versions DETACH DELETE n; MATCH (m:ZgVersion) WHERE m.versionId IN $versions DELETE m; "
                                                     "MATCH (s:ZgStore {storeId: $storeId}) DELETE s"),
                                          "params": {"versions": self.created_versions, "storeId": f"{self.run_id}-store"},
                                          "note": "by exact identity only; run it only if the database is to be reused"}}}
        return summary


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="live_graph_smoke.py", description=__doc__, epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="explicit opt-in to a PAID run (required unless --check)")
    parser.add_argument("--check", action="store_true", help="validate configuration, console scripts and the Neo4j target (read-only preflight); spend nothing, create nothing")
    parser.add_argument("--output-root", required=True, type=Path, help="NEW absolute real path; holds synthetic raw documents, private receipts and every ledger")
    parser.add_argument("--graph-uri", required=True, help="bolt://<loopback>:<port> or bolt+s://<host>:<port> of an EMPTY dedicated Neo4j 5 database")
    parser.add_argument("--graph-database", default="neo4j", help="user database name (never `system`)")
    parser.add_argument("--usd-cap", required=True, help=f"aggregate budget ceiling in USD this run may be configured with; must be <= {HARD_CEILING_USD} (the approved total)")
    parser.add_argument("--run-id", help="id prefix for jobs/versions/store (default: generated)")
    parser.add_argument("--exercise-manual-approval", action="store_true",
                        help="if (and only if) a GENUINE Jev HOLD with a passing deterministic gate occurs, submit ONE scripted synthetic test operator `allow`, assert no model call "
                             "and the operator-final-approval basis, then project a second version; otherwise report a coverage gap")
    parser.add_argument("--approve-relation", metavar="RC", help="with --exercise-manual-approval: approve this specific genuine HOLD (default: the first by id)")
    parser.add_argument("--allow-nonstandard-endpoints", action="store_true", help="allow base URLs other than api.openai.com / api.typesafe.ai (then NOT reported as the real provider)")
    parser.add_argument("--child-timeout-seconds", type=int, default=3000, help="wall limit of each live S2/S3 child (a killed child leaves an unknown outcome that is never resent)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    if not args.check and not args.live:
        print(json.dumps({"schemaVersion": SCHEMA, "status": "refused", "failure": {"code": "live_flag_required_for_a_paid_run"}}))
        return 2
    harness = Harness(args)
    try:
        harness.execute()
    except Failure as exc:
        harness.failure = {"stage": exc.stage, "code": exc.code, "uncertain": exc.uncertain, "detail": harness.safe_detail(exc.detail)}
    except Exception as exc:  # noqa: BLE001 - never print an exception message: it may carry a path, URL or text
        harness.failure = {"stage": harness.stage, "code": "unexpected_" + type(exc).__name__}
    summary = harness.finalize()
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if harness.redactor.hit(text):
        text = json.dumps({"schemaVersion": SCHEMA, "status": "failed", "runId": harness.run_id, "failure": {"code": "summary_contained_private_text_suppressed"},
                           "outputRoot": str(harness.root)}, indent=2)
        summary["status"] = "failed"
    if harness.root.is_dir() and not args.check:
        try:
            write_private(harness.root / "summary.json", text.encode("utf-8"))
        except OSError:
            pass
    print(text)
    if summary["status"] in {"passed", "passed-with-coverage-gap", "check-passed"}:
        return 0
    return 2 if harness.budget_before is None else 1   # 2: refused before any spend; 1: a real failure after the budget was opened


if __name__ == "__main__":
    raise SystemExit(main())
