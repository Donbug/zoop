#!/usr/bin/env python3
"""Operator smoke for the graph handoff import: installed `zoop-ai-handoff` + `zoop-ai-ingest` -> built Spring jar -> real PostgreSQL.

Every hop is a real process; nothing is mocked. Everything is synthetic and local: no network, no model, no provider. The script
  1. builds the authored ingestion + S2 + S3 world of `ai/pipeline/scripts/graph_handoff_smoke.py`, writes the operator files and
     FREEZES two handoffs with the installed `zoop-ai-handoff` (public company ids are `SYNTH:*`, so the seeded catalog is never
     touched),
  2. registers the three source documents in PostgreSQL with the built jar's document import (the app's own article rows, text
     artifacts and files),
  3. seeds the synthetic fixture graph versions (one ACTIVE pointer and its activation history) by starting the jar once with the
     fixture source, so there is a real pointer to leave untouched,
  4. runs the jar's non-web graph handoff import: it calls the installed `zoop-ai-handoff export` and, for EVERY observation,
     `zoop-ai-ingest export --require-store`, verifies the bundle, registers evidence and an INACTIVE graph version, and writes the
     retained receipt,
  5. checks the persisted rows, files and result document against facts it knows independently (the authored texts, hand-written
     evidence ids and offsets, the producer's own export of the handoff) and proves the refusals: wrong pins, a revoked `store`
     right, a withheld handoff, and an identical import being a no-op; it also starts the web application and shows that the staged
     version is not publicly readable.

Run it with the pipeline venv's Python (it imports the AI smoke world), against an EMPTY dedicated database (a throwaway one: it is
not cleaned):

  make pipeline-install api-build       # once: ai/pipeline/.venv and the jar (not run automatically)
  DB_URL=jdbc:postgresql://127.0.0.1:<port>/<db> DB_USERNAME=<user> DB_PASSWORD=<dummy> \
    [GRAPH_IMPORT_PSQL_CONTAINER=<container>] [GRAPH_IMPORT_DB_USER=<user>] [GRAPH_IMPORT_DB_NAME=<db>] \
    make api-graph-handoff-import-smoke

(the Make target runs this script with --jar/--handoff-cli/--ingest-cli; the direct python invocation with those flags and
--psql-container/--db-user/--db-name still works.) The staged snapshot is the app's current format 3 (PR #217) and carries no original mention value:
the retained receipt keeps the complete `zoop-graph-handoff-bundle-6` bundle, whose `issues[].mentions[]` the script compares with hand-written S2 values, whose
`issues[].fieldProvenance` (which mentions state each selected headline value, whether the operator's representative or unanimity selected it, and which of
`eventTime`/`period` an operator verdict withheld; never a verification) it compares with hand-written selection facts and whose `issues[].fieldVerdicts` it compares
with hand-written operator verdicts.
A second, legal producer world is imported next: documents a and a2 of one issue both use the local mention id `m-a`, which the app maps to two distinct
mention ids and the receipt keeps as two original mentions.
A third, producer-authored VERDICT world (`graph_handoff_smoke.verdict_export`, a SYNTHETIC review, handoff `handoff-verdicts-1`) is imported last: the supply
representative's REJECTed event time and the factory's HELD period are null in the staged snapshot (event time with unknown precision) while the receipt retains
every original mention value, each verdict and its exact evidence; a non-representative HOLD/REJECT and an ALLOW withhold nothing. With the evidence-read phase
(the default) a SECOND TEST-HARNESS activation then reads that version through the real public graph, derived-edge and evidence routes to show the withheld values are absent.
A fourth, producer-authored APPROVED world (`graph_handoff_smoke.approved_export`, replay, SYNTHETIC, handoff `handoff-approved-1`) is imported after the verdict world: an
operator's FINAL approval of an S3 HOLD beside automatic verdicts, and operator-declared document origins. The receipt keeps every used relation's `approvalBasis`
(an operator approval never reads as the independent verifier on the INVOLVES or structural literal, `verifiedAt` is the deciding event's time), every article's
`textSha256` equals the stored text's hash, and each issue's `sourceSupport` equals the hand-written lineage groups (`knownLineageCount` counts groups, not articles)
and exact-text duplicate groups; none of it is in the staged snapshot or any public read (a THIRD TEST-HARNESS activation serves it through the real graph and evidence routes).
A fifth, producer-authored STRUCTURAL-PATH world (`build_world(chain=True)`, SYNTHETIC; three handoffs `path-{private,known,unmapped}-1`, built LAST) is imported after the others: a complete
two-relation path through a mapped but unpublished middle company (a private `pathCompanies` entry, catalogue-checked with an equal label under the import's lock: a renamed one is
`company_mismatch` with nothing written), through a published middle, and an unavailable path through an unmapped middle. The staged snapshots carry no path, no path company and no scope
text; the receipts keep the complete bundle, the `structural_path_closed_over_involves_basis_and_catalog` check and the operator-mapped-chain note. With the evidence-read phase a FOURTH
TEST-HARNESS activation (BACK-DATED to just after the last activation, so an asOf can fall before the structural basis was verified) serves the private-middle version: the spans only a
structural basis cites are 200 without eventIds from the selected version's receipt, 404 before the basis was verified or the article published, under a revoked grant, a private article,
tampered receipt bytes or another version, and no public body names the private company. Disclosure exclusions have no store in the built application, so they are proven by the Java tests.
A sixth, producer-authored IMPACT world (`graph_handoff_smoke.impact_export`, replay, SYNTHETIC, handoff `handoff-impacts-1`, built after the path worlds) is imported last: the receipt retains
the closed `impacts[]` (one row per INVOLVES source relation: a verified positive with an impact-only quote, a verifier-rejected, a verified negative of the other S3 job, a verified undetermined,
a no-evidence and a precheck-rejected row; hand-written in `hs.expected_impacts`), while the snapshot, the import result and every public body carry no proposal, effect, label, candidate id or
verifier digest. With the evidence-read phase a FIFTH TEST-HARNESS activation serves the impact-only quote (cited by no issue, relation or structural basis): 200 with empty eventIds from the
selected version's receipt although the one candidate structural basis does not cite it, 404 before the version existed / the article was published, for another version, under a revoked grant, a
private article or tampered receipt bytes. The article's publication boundary is proven with the IMPACT version itself selected on both sides: at the very end the script adds TEST-ONLY historical
activation rows (reason `smoke history:`, reported as `historicalActivations`, never an import or harness activation) at the fixture's own publication instant, so asOf half a second before is 404 although
graphVersion pins the impact version (a wrong pin would be 422) and half a second after is 200 with that version in metadata. An excluded edge/evidence and a malformed receipt basis need a mutable
exclusion store / re-registered receipt, so the Java tests (real pinned reader, real service) prove those and this script does not claim them over HTTP.

On success the last stdout line is {"status": "passed", "steps": N, "providerCalls": 0, "modelCalls": 0, ...}; any failed

An evidence-read phase runs by default (turn it off with --no-with-evidence-read): after the collision import it starts the web jar on loopback
(artifact source, ZOOP_DOCUMENT_READ_INGESTION_SOURCES = the same registry file, S1 grants unset), makes ONE explicit TEST-HARNESS psql activation of the
second staged version (the import itself never activates; production has no activation route) and reads GET /api/v1/evidence/{id} for the graph body
evidence, with CLI parity for the source registry and failure cases; the verdict world then gets its own one TEST-HARNESS activation and public graph reads. The final line
reports importActivationsWritten: 0 and harnessActivations: 2 separately, plus evidenceReads and verdictGraphReads.
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

API_SCRIPTS = Path(__file__).resolve().parent
PIPELINE = API_SCRIPTS.parents[1] / "ai" / "pipeline"
sys.path[:0] = [str(PIPELINE), str(API_SCRIPTS)]

import document_import_smoke as base  # noqa: E402  (database, jar and step helpers)
from scripts import graph_handoff_smoke as hs  # noqa: E402  (the authored AI world and its operator documents)

check, step = base.check, base.step
PUBLIC_IDS = {"KRX:005930": "SYNTH:000001", "KRX:000660": "SYNTH:000002"}   # the catalog's seeded ids are never reused
SCHEMA = "zoop-graph-handoff-import-1"
COMPANIES = (("SYNTH:000001", "합성기업"), ("SYNTH:000002", "합성부품"))
HANDOFFS = ("handoff-smoke-1", "handoff-smoke-2")
# The operator-declared publishing outlets of the authored world, written out by hand. Only document "a" declares one; "a2" and "b" do not, so their
# stored versions keep a NULL publisher and the public read must answer null. The AI world must have been generated with exactly this declaration.
DECLARED_PUBLISHERS = {"a": "합성일보 Synthetic Daily"}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def version_id(handoff_id: str) -> str:
    return "gv-" + sha256(handoff_id.encode("utf-8"))


def mention_id(article: dict, source_mention_id: str) -> str:
    """The app's mention id, written out by hand (never taken from the writer under test): "mention-" + the SHA-256 of the canonical JSON (sorted keys, no
    spaces) of the resolved article id and version and the producer's local mention id. Local ids repeat across documents; this one does not."""
    return "mention-" + sha256(hs.canonical({"articleId": article["articleId"], "articleVersion": article["articleVersion"],
                                              "sourceMentionId": source_mention_id}).encode("utf-8"))


def participant(source_id: str | None, name: str, role: str, public_id: str | None = None) -> dict:
    """One participant as the authored S2 replay states it; `public_id` is the AUTHORED public id (KRX:*), remapped to this smoke's catalog ids, or None when the
    contract says the company is unmapped (no source id, no canonical entry, or no public decision)."""
    return {"sourceCompanyId": source_id, "companyId": PUBLIC_IDS[public_id] if public_id else None, "name": name, "role": role}


MAPPED = participant("SYNTH-1", "합성기업", "issuer", "KRX:005930")
# The contract's mapping cases, hand-written from the authored world: mapped (two public companies), no source id, no public decision, no canonical entry.
DOC_A = [MAPPED, participant("SYNTH-3", "합성부품", "supplier", "KRX:000660"), participant(None, "미상 거래처", "counterparty")]
DOC_B = [MAPPED, participant("SYNTH-2", "합성협력", "partner"), participant("SYNTH-9", "미등록 법인", "observer")]


def expected_mentions(world, *items: tuple) -> list:
    """The original S2 mentions of one issue, written out by hand from the authored extraction replay (`extraction_smoke.Kit.mention` defaults plus what
    `graph_handoff_smoke.build_world` overrides) and the operator's canonical/decisions files: every item is (document name, S2 local mention id, cited quote,
    title, action, event time, period, participants). `verification` is always `none`; participants are the S2 text as extracted, in S2 order, with the public
    company only where the contract maps it. Ordered as the bundle orders them: by the canonical JSON of the identity."""
    found = []
    for name, local_id, quote, title, action, event_time, period, participants in items:
        ref = world.refs[name]
        found.append({"documentId": ref["documentId"], "documentVersion": ref["documentVersion"], "mentionId": local_id,
                      "articleId": ref["documentId"], "articleVersion": ref["documentVersion"], "verification": "none", "title": title, "action": action,
                      "target": "공급 계약", "eventTime": event_time, "timePrecision": "day", "period": period, "assertionStatus": "announced", "background": False,
                      "participants": participants, "evidenceIds": [hs.evidence_id(world, name, quote)]})
    return sorted(found, key=lambda m: hs.canonical({k: m[k] for k in ("documentId", "documentVersion", "mentionId")}))


def expected_field_provenance(world, selection: str, every: tuple, *, withheld: tuple = (), **different: tuple) -> dict:
    """One issue's `fieldProvenance`, written out by hand: `every` is the (document name, S2 local mention id) pairs that state the SELECTED value (the representative's,
    or the shared one) in each of the six headline fields, and a keyword overrides one field's pairs where fewer mentions state it. Ordered like the mentions: by the
    canonical JSON of the identity. `withheld` is the hand-written subset of `eventTime`/`period` an operator HOLD/REJECT on the selection basis removed from the
    issue headline; the lists still compare the ORIGINAL selected value, never the redacted null. It records selection, never that the value is verified
    (`verification` is always `none`)."""
    def references(pairs: tuple) -> list:
        found = [{"documentId": world.refs[name]["documentId"], "documentVersion": world.refs[name]["documentVersion"], "mentionId": local_id}
                 for name, local_id in pairs]
        return sorted(found, key=hs.canonical)
    fields = ("title", "action", "target", "eventTime", "period", "assertionStatus")
    return {"selection": selection, "verification": "none", "withheld": list(withheld),
            "sameValueMentions": {field: references(different.get(field, every)) for field in fields}}


def fingerprint(path: Path) -> dict:
    """Every file under `path`: mode, size, mtime and hash (a read-only ledger must be identical afterwards)."""
    found = {}
    for item in sorted(path.rglob("*")):
        if item.is_file():
            info = item.stat()
            found[str(item.relative_to(path))] = (stat.S_IMODE(info.st_mode), info.st_size, info.st_mtime_ns, sha256(item.read_bytes()))
    return found


class Layout:
    """The directories of the world and of the app side, in the names the jar's settings use."""

    def __init__(self, world, ingest_cli: Path):
        self.world = world
        self.ingest_cli = ingest_cli
        self.work = Path(tempfile.mkdtemp(prefix="zoop-graphimport-app-")).resolve()   # a real path: no /var symlink on macOS
        atexit.register(shutil.rmtree, self.work, True)
        self.requests = self.work / "requests"
        self.artifacts = self.work / "artifacts"
        self.requests.mkdir(mode=0o700)
        self.artifacts.mkdir(mode=0o700)
        self.root = self.work                       # the names base.Jar expects from its "world"
        self.state = world.root / "ingestion"
        self.registry_path = world.kit.registry_path

    def ownership_env(self) -> dict:
        return hs.ownership_env()

    @property
    def ledgers(self) -> dict:
        return {name: self.world.root / name for name in ("ingestion", "extraction", "relation", "handoff")}


class Smoke:
    def __init__(self, args, db, layout):
        self.args, self.db, self.layout, self.world = args, db, layout, layout.world
        self.java = args.java
        self.jar = base.Jar(args.java, args.jar, db, layout)
        self.runs = 0

    # ---------------------------------------------------------------------------------------------------- jar runs ----
    def graph_env(self, request: Path, result: Path) -> dict:
        root = self.world.root
        return {**self.jar.base_env(), "ZOOP_GRAPH_HANDOFF_IMPORT_ENABLED": "true",
                "ZOOP_GRAPH_HANDOFF_IMPORT_REQUEST": str(request), "ZOOP_GRAPH_HANDOFF_IMPORT_RESULT": str(result),
                "ZOOP_HANDOFF_CLI": str(self.args.handoff_cli), "ZOOP_HANDOFF_STATE_DIR": str(root / "handoff"),
                "ZOOP_RELATION_STATE_DIR": str(root / "relation"), "ZOOP_EXTRACTION_STATE_DIR": str(root / "extraction"),
                "ZOOP_INGESTION_CLI": str(self.args.ingest_cli), "ZOOP_INGESTION_STATE_DIR": str(root / "ingestion"),
                "ZOOP_INGESTION_SOURCES": str(self.layout.registry_path), "ZOOP_HANDOFF_CANONICAL": str(root / "canonical.json"),
                "ZOOP_HANDOFF_DECISIONS": str(root / "decisions.json"), "ZOOP_HANDOFF_BINDINGS": str(root / "bindings.json"),
                "ZOOP_ARTIFACT_ROOT": str(self.layout.artifacts), **hs.ownership_env()}

    def graph_import(self, label: str, request: dict | bytes) -> tuple[int, dict | None, str]:
        """One operator run of the graph handoff import; returns (exit status, parsed result file, process output)."""
        self.runs += 1
        stem = f"{self.runs:02d}-{label}"
        request_path = self.layout.requests / f"{stem}-request.json"
        result_path = self.layout.requests / f"{stem}-result.json"
        request_path.write_bytes(request if isinstance(request, bytes) else json.dumps(request).encode("utf-8"))
        try:
            done = subprocess.run(self.jar.argv("--spring.main.web-application-type=none"), env=self.graph_env(request_path, result_path),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=420)
        except subprocess.TimeoutExpired as expired:
            base.OUTPUT.append((expired.stdout or b"").decode("utf-8", "replace"))
            raise AssertionError(f"{label}: the import JVM did not exit within 420s (result file exists: {result_path.exists()})")
        output = done.stdout.decode("utf-8", "replace")
        base.OUTPUT.append(output)
        parsed = None
        if result_path.exists():
            check(stat.S_IMODE(result_path.stat().st_mode) & 0o077 == 0, f"{label}: result file is not owner-only")
            text = result_path.read_text("utf-8")
            check(text, f"{label}: the result file was reserved but left empty")
            for private in (str(self.world.root), str(self.layout.work)):
                check(private not in text, f"{label}: the result file leaks a path")
            for secret in hs.PRIVATE:
                check(secret not in text, f"{label}: the result file leaks source or review text")
            parsed = json.loads(text)
        return done.returncode, parsed, output

    @staticmethod
    def request(handoff_id: str, manifest_digest: str, bundle_digest: str) -> dict:
        return {"schemaVersion": SCHEMA, "handoffId": handoff_id, "expectedManifestDigest": manifest_digest,
                "expectedBundleDigest": bundle_digest, "operator": "smoke-operator"}

    # ---------------------------------------------------------------------------------------------------- web runs ----
    def web(self, extra_env: dict, ready: str | None = None):
        """The built application as a web server on a free loopback port; `with` stops it (after `ready` appeared in its log)."""
        return WebRun(self.jar, extra_env, ready)

    # ---------------------------------------------------------------------------------------------------- database -----
    def table_fingerprint(self) -> dict:
        return json.loads(self.db.run("""
            SELECT json_build_object(
              'versions', (SELECT md5(coalesce(string_agg(v::text, '|' ORDER BY v.id), '')) FROM graph_versions v),
              'activations', (SELECT md5(coalesce(string_agg(a::text, '|' ORDER BY a.id), '')) FROM graph_activations a),
              'evidence', (SELECT md5(coalesce(string_agg(e::text, '|' ORDER BY e.id), '')) FROM evidence e),
              'artifacts', (SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x.id), '')) FROM artifacts x),
              'articles', (SELECT md5(coalesce(string_agg(a::text, '|' ORDER BY a.id), '')) FROM articles a),
              'versionsOfArticles', (SELECT md5(coalesce(string_agg(v::text, '|' ORDER BY v.article_id, v.version), '')) FROM article_versions v))"""))

    def set_registry(self, change):
        """Atomically rewrites the one source registry both CLIs read (a reader sees the old or the new file)."""
        path = self.layout.registry_path
        registry = json.loads(path.read_text("utf-8"))
        change(registry["sources"][0]["grant"])
        temporary = path.parent / "next-sources.json"
        temporary.write_bytes(hs.json_bytes(registry))
        temporary.replace(path)

    def ingest_export(self, ref: dict, *, require_store: bool) -> int:
        """Runs the installed `zoop-ai-ingest export` for one observation against the CURRENT registry; returns its exit status."""
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8",
               "PYTHONDONTWRITEBYTECODE": "1", **hs.ownership_env()}
        argv = [str(self.args.ingest_cli), "export", "--state-dir", str(self.world.root / "ingestion"), "--sources",
                str(self.layout.registry_path)] + (["--require-store"] if require_store else [])
        done = subprocess.run(argv, input=hs.json_bytes({"schemaVersion": "zoop-ingestion-s2-1", **ref}), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env, timeout=120)
        return done.returncode

    def fixture_source_start(self) -> tuple[int, str]:
        """Starts the application with the local/dev fixture source against the CURRENT database; returns (exit status, output)."""
        port = "--server.port=0"
        done = subprocess.run(self.jar.argv(port, "--server.address=127.0.0.1"), env={**self.jar.base_env(), "ZOOP_GRAPH_SNAPSHOT_SOURCE": "fixture"},
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        output = done.stdout.decode("utf-8", "replace")
        base.OUTPUT.append(output)
        return done.returncode, output


class WebRun:
    def __init__(self, jar, extra_env: dict, ready: str | None = None):
        self.ready = ready
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.lines: list[str] = []
        self.process = subprocess.Popen(jar.argv(f"--server.port={self.port}", "--server.address=127.0.0.1"),
                                        env={**jar.base_env(), **extra_env}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        threading.Thread(target=self.drain, daemon=True).start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def drain(self):
        for raw in self.process.stdout:
            self.lines.append(raw.decode("utf-8", "replace"))

    def __enter__(self):
        deadline = time.monotonic() + 240
        # "Started ..." is logged BEFORE the application runners run, so a runner's own log line is the readiness of its work.
        marker = self.ready or "Started ZoopApplication"
        while time.monotonic() < deadline and self.process.poll() is None and not any(marker in l for l in self.lines):
            time.sleep(0.5)
        check(any(marker in l for l in self.lines), "the web application did not become ready:\n" + "".join(self.lines)[-1500:])
        return self

    def __exit__(self, *exc):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
        base.OUTPUT.append("".join(self.lines))

    def get(self, path: str) -> tuple[int, str]:
        try:
            with self.opener.open(f"http://127.0.0.1:{self.port}{path}", timeout=30) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")


def evidence_read_phase(smoke, db, layout, world, vid2: str, never_activated: tuple, active_before: str) -> dict:
    """Public GET /api/v1/evidence/{id} over real HTTP for the graph body evidence of the second staged handoff.

    The import never activates, and no production activation exists, so a staged version is unreadable by design. This phase therefore adds
    ONE explicit TEST-HARNESS activation of `vid2` by psql, mirroring JdbcGraphVersionRepository.activateSystem (same advisory lock, pointer move
    and a `system` history row), in the smoke's own throwaway database. It is reported separately (`harnessActivations`) and is not an import
    result. The evidence rows of `vid2` are shared with the first import, whose receipt they still point at: reading proves the SELECTED version's
    receipt (not the row's own, older one) supplies the grant pins. Expectations come from the authored world, never from the reader under test."""
    import urllib.parse
    from datetime import timezone
    reads = 0
    spans = [("a", hs.EVT_A), ("a", hs.GEO_A), ("a", hs.SUP), ("a2", hs.EVT_A2), ("b", hs.QB), ("b", hs.GEO_B)]
    snapshot = json.loads((layout.artifacts / "graph_snapshot" / f"{vid2}.json").read_text("utf-8"))
    expected = {}
    for name, quote in spans:
        eid, span = hs.evidence_id(world, name, quote), hs.span(world, name, quote)
        citing = [i["issueId"] for i in snapshot["issues"] if eid in i["evidenceIds"] or eid in i["geographyEvidenceIds"]]
        expected[eid] = {"name": name, "quote": quote, "span": span, "events": citing}
    main_id = hs.evidence_id(world, "a", hs.EVT_A)
    check(expected[main_id]["events"], "the authored world's main evidence is cited by no issue of the snapshot")
    ref = base.item(world.refs["a"])["observation"]
    artifact_tree = fingerprint(layout.artifacts)
    registry_bytes = layout.registry_path.read_bytes()
    web_env = {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(layout.artifacts),
               "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(layout.artifacts), "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(layout.registry_path)}

    def get(web, evidence_id: str, **params) -> tuple[int, dict]:
        nonlocal reads
        reads += 1
        query = urllib.parse.urlencode(params)
        code, body = web.get(f"/api/v1/evidence/{evidence_id}" + (f"?{query}" if query else ""))
        return code, (json.loads(body) if body.startswith("{") else {})

    def error_code(body: dict) -> str:
        return (body.get("error") or {}).get("code", "")

    with smoke.web(web_env) as web:
        # before any activation: the staged version cannot be pinned, and the active fixture version does not show this evidence ----
        code, body = get(web, main_id, graphVersion=vid2)
        check(code == 409 and error_code(body) == "VERSION_UNAVAILABLE", f"a staged version was readable through the evidence read: {code} {body}")
        code, body = get(web, main_id)
        check(code == 404 and error_code(body) == "EVIDENCE_UNAVAILABLE", f"the unpinned read before any activation: {code} {body}")
        before_reads = smoke.table_fingerprint()

        # the one explicit test-harness activation ------------------------------------------------------------------------------
        at = datetime.now(timezone.utc)
        check(at.year >= 2026 and db.scalar("SELECT count(*) FROM graph_activations") == 2, "unexpected activation history before the harness")
        db.run(f"""SELECT pg_advisory_xact_lock(x'7a6f6f7067726170'::bigint);
            UPDATE graph_versions SET active = false WHERE active;
            UPDATE graph_versions SET active = true WHERE id = '{vid2}';
            INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed, admin_id,
                admin_email_snapshot, reason, activated_at)
            VALUES ('{vid2}', '{active_before}', 'activate', 'system', true, NULL, 'system',
                'smoke harness: synthetic activation', '{at.isoformat()}')""")
        check(db.scalar("SELECT id FROM graph_versions WHERE active") == vid2 and db.scalar("SELECT count(*) FROM graph_activations") == 3,
              "the harness activation did not apply")
        harness_fingerprint = smoke.table_fingerprint()

        # reads after the harness activation ---------------------------------------------------------------------------------------
        publishers_read: dict = {}
        for eid, fact in expected.items():
            if not fact["events"]:
                # Cited by no issue and no relation: only the structural basis rests on it. A BASIS-ONLY span is served when the selected version's
                # receipt proves exactly that relation's basis cites it, and carries no eventIds.
                check((fact["name"], fact["quote"]) == ("a", hs.SUP), f"an unexpected evidence cited by nothing: {fact['name']} {fact['quote']!r}")
            code, body = get(web, eid)
            span = fact["span"]
            check(code == 200 and body["id"] == eid and body["quote"] == fact["quote"] and body["start"] == span["start"]
                  and body["end"] == span["end"] and body["articleId"] == span["documentId"] and body["articleVersion"] == span["documentVersion"]
                  and body["documentVersion"] == span["documentVersion"] and body["quoteVerified"] is True,
                  f"graph evidence {fact['name']}: {code} {str(body)[:300]}")
            check(body["eventIds"] == fact["events"] and body["sentiment"] is None and body["documentSummary"] is None
                  and body["analysisStatus"] is None and body["analysisProvenance"] is None and body["resultVersion"] is None,
                  f"graph evidence body fields {fact['name']}: {body}")
            article = body["article"]
            check(set(article) == {"title", "publisher", "url", "publishedAt"}, f"graph evidence article keys {fact['name']}: {article}")
            check(article["publisher"] == DECLARED_PUBLISHERS.get(fact["name"]),
                  f"graph evidence {fact['name']}: article.publisher {article['publisher']!r} is not the declared {DECLARED_PUBLISHERS.get(fact['name'])!r}")
            publishers_read[fact["name"]] = article["publisher"]
            meta = body["metadata"]
            check(meta["source"] == "public_graph_snapshot" and meta["graphVersion"] == vid2 and meta["partial"] is False and meta["failures"] == [],
                  f"graph evidence metadata: {meta}")
            check(abs((datetime.now(timezone.utc) - datetime.fromisoformat(meta["asOf"].replace("Z", "+00:00"))).total_seconds()) < 300,
                  f"the unpinned read's asOf is not the request time: {meta['asOf']}")
        code, body = get(web, main_id, graphVersion=vid2)
        check(code == 200 and body["metadata"]["graphVersion"] == vid2, f"graphVersion read: {code} {body}")
        later = (at + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        code, body = get(web, main_id, asOf=later)
        check(code == 200 and body["metadata"]["graphVersion"] == vid2 and body["metadata"]["asOf"] == later, f"later asOf read: {code} {body}")
        code, body = get(web, main_id, asOf="2026-10-09T00:00:00Z")
        check(code == 404 and error_code(body) == "EVIDENCE_UNAVAILABLE", f"an asOf before the activation must not show the evidence: {code} {body}")
        code, body = get(web, main_id, asOf="2026-10-09T00:00:00Z", graphVersion=vid2)
        check(code == 422 and error_code(body) == "INVALID_REQUEST", f"inconsistent graphVersion and asOf: {code} {body}")
        code, body = get(web, main_id, round="brf-1")
        check(code == 409 and error_code(body) == "VERSION_UNAVAILABLE", f"round: {code} {body}")
        for other in never_activated:
            code, body = get(web, main_id, graphVersion=other)
            check(code == 409 and error_code(body) == "VERSION_UNAVAILABLE", f"a never-activated version was readable: {other} {code}")
        code, body = get(web, main_id, asOf="yesterday")
        check(code == 422 and error_code(body) == "INVALID_REQUEST", f"an invalid asOf: {code} {body}")
        code, body = get(web, main_id, companyId="SYNTH:000001")
        check(code == 200 and body["metadata"]["partial"] is True and body["sentiment"] is None
              and [f["section"] for f in body["metadata"]["failures"]] == ["sentiment"], f"known company: {code} {body}")
        code, body = get(web, main_id, companyId="NOPE:1")
        check(code == 404 and error_code(body) == "RESOURCE_NOT_FOUND", f"unknown company: {code} {body}")
        code, body = get(web, "ev-" + "0" * 64)
        check(code == 404 and error_code(body) == "RESOURCE_NOT_FOUND", f"unknown evidence id: {code} {body}")
        check(publishers_read.get("a") == DECLARED_PUBLISHERS["a"] and publishers_read.get("a2", "missing") is None
              and publishers_read.get("b", "missing") is None,
              f"the public reads did not cover the declared and the undeclared documents: {publishers_read}")
        for name, quote in spans:
            span = hs.span(world, name, quote)
            stored = db.scalar(f"SELECT json_build_object('publisher', publisher) FROM article_versions WHERE article_id = '{span['documentId']}' AND version = '{span['documentVersion']}'")["publisher"]
            check(stored == DECLARED_PUBLISHERS.get(name), f"the stored article_versions.publisher of {name} is {stored!r}")
        check(smoke.table_fingerprint() == harness_fingerprint, "a public read changed a table")
        check(fingerprint(layout.artifacts) == artifact_tree, "a public read changed the artifact tree")
        check(before_reads["evidence"] == harness_fingerprint["evidence"] and before_reads["artifacts"] == harness_fingerprint["artifacts"],
              "the harness changed evidence or artifacts")
        step("evidence read (web, artifact source, S1 grants unset): staged 409 / unpinned 404 before the harness activation; after it the six-field body, "
             "selected graphVersion and asOf, eventIds, later asOf 200, earlier asOf 404, 422/409/404 paths, partial company context; nothing written")

        # parity with the CLI: the same current registry decides the import's --require-store and this read ------------------------
        original = json.loads(layout.registry_path.read_text("utf-8"))["sources"][0]["grant"]
        now_past = "2020-01-01T00:00:00Z"
        denied = {
            "drop read": lambda g: g.update({"allowedOperations": [o for o in g["allowedOperations"] if o != "read"]}),
            "drop store": lambda g: g.update({"allowedOperations": [o for o in g["allowedOperations"] if o != "store"]}),
            "drop quote-display": lambda g: g.update({"allowedOperations": [o for o in g["allowedOperations"] if o != "quote-display"]}),
            "disabled": lambda g: g.update({"enabled": False}),
            "rights unknown": lambda g: g.update({"rights": "unknown"}),
            "rights denied": lambda g: g.update({"rights": "denied"}),
            "blank evidence": lambda g: g.update({"evidence": ["  "]}),
            "expired": lambda g: g.update({"expiresAt": now_past}),
        }
        for label, change in denied.items():
            smoke.set_registry(change)
            code, body = get(web, main_id)
            cli = smoke.ingest_export(ref, require_store=True)
            check(code == 404 and error_code(body) == "EVIDENCE_UNAVAILABLE" and cli != 0,
                  f"parity {label}: the read answered {code} but the CLI exit was {cli}")
            smoke.set_registry(lambda g: (g.clear(), g.update(original)))
            code, body = get(web, main_id)
            check(code == 200 and smoke.ingest_export(ref, require_store=True) == 0, f"parity {label}: restoring did not restore both")
        # a changed revision or grant id is not something the CLI sees (its export takes no expected pin); the read compares the receipt's pins
        for label, change in (("revision", lambda g: g.update({"revision": g["revision"] + "-next"})),
                              ("grant id", lambda g: g.update({"grantId": g["grantId"] + "-other"}))):
            smoke.set_registry(change)
            code, body = get(web, main_id)
            check(code == 404 and error_code(body) == "EVIDENCE_UNAVAILABLE", f"a changed {label} did not withhold the evidence: {code} {body}")
            smoke.set_registry(lambda g: (g.clear(), g.update(original)))
        # control: model-send is not part of the rule (nothing is sent to a model); both with and without it the read and the CLI pass
        for operations in (["read", "store", "quote-display"], ["read", "store", "model-send", "quote-display"]):
            smoke.set_registry(lambda g: g.update({"allowedOperations": operations}))
            code, body = get(web, main_id)
            check(code == 200 and smoke.ingest_export(ref, require_store=True) == 0, f"control model-send {operations}: {code}")
        smoke.set_registry(lambda g: (g.clear(), g.update(original)))
        step("parity: for every denial (missing read/store/quote-display, disabled, rights unknown/denied, blank evidence, expiry) the GET is 404 exactly when "
             "`zoop-ai-ingest export --require-store` fails; a changed revision/grant id is 404; model-send in or out of the grant does not matter")

        # failures: each is restored afterwards ---------------------------------------------------------------------------------
        layout.registry_path.write_bytes(b"{")
        code, body = get(web, main_id)
        check(code == 503 and error_code(body) == "SOURCE_UNAVAILABLE", f"a malformed source registry: {code} {body}")
        parked = layout.registry_path.with_name("parked-sources.json")
        layout.registry_path.replace(parked)
        code, body = get(web, main_id)
        check(code == 503 and error_code(body) == "SOURCE_UNAVAILABLE", f"a missing source registry: {code} {body}")
        parked.replace(layout.registry_path)
        layout.registry_path.write_bytes(registry_bytes)
        check(get(web, main_id)[0] == 200, "restoring the registry file did not restore the read")
        # An expiresAt the S2-1 Python model rejects (a lowercase `z`) makes the WHOLE registry invalid: 503, never a per-source denial,
        # whether it sits on the requested source or on an unrelated one. Each is restored byte-for-byte.
        bad_expiry = "2030-01-01T00:00:00z"
        requested = json.loads(registry_bytes.decode("utf-8"))
        requested["sources"][0]["grant"]["expiresAt"] = bad_expiry
        layout.registry_path.write_bytes(hs.json_bytes(requested))
        code, body = get(web, main_id)
        check(code == 503 and error_code(body) == "SOURCE_UNAVAILABLE", f"an invalid expiresAt on the requested source: {code} {body}")
        layout.registry_path.write_bytes(registry_bytes)
        check(get(web, main_id)[0] == 200, "restoring the registry after an invalid requested-source expiry did not restore the read")
        unrelated = json.loads(registry_bytes.decode("utf-8"))
        other = json.loads(json.dumps(unrelated["sources"][0]))
        other["sourceId"] = other["grant"]["sourceId"] = "unrelated-smoke-source"
        other["grant"]["grantId"] = "unrelated-smoke-grant"
        other["grant"]["expiresAt"] = bad_expiry
        unrelated["sources"].append(other)
        layout.registry_path.write_bytes(hs.json_bytes(unrelated))
        code, body = get(web, main_id)
        check(code == 503 and error_code(body) == "SOURCE_UNAVAILABLE", f"an invalid expiresAt on an unrelated source: {code} {body}")
        layout.registry_path.write_bytes(registry_bytes)
        check(get(web, main_id)[0] == 200, "restoring the registry after an invalid unrelated-source expiry did not restore the read")
        receipt_path = layout.artifacts / "verification_receipt" / f"{vid2}.json"
        receipt_info = receipt_path.stat()
        receipt_original = receipt_path.read_bytes()
        receipt_path.write_bytes(receipt_original.replace(b'"activation":"none"', b'"activation":"nope"'))
        check(receipt_path.read_bytes() != receipt_original, "the receipt tamper did not change any byte")
        code, body = get(web, main_id)
        check(code == 404 and error_code(body) == "EVIDENCE_UNAVAILABLE", f"tampered receipt bytes: {code} {body}")
        receipt_path.write_bytes(receipt_original)
        os.utime(receipt_path, ns=(receipt_info.st_atime_ns, receipt_info.st_mtime_ns))
        check(get(web, main_id)[0] == 200, "restoring the receipt did not restore the read")
        article_id = expected[main_id]["span"]["documentId"]
        db.run(f"UPDATE articles SET access_status = 'private' WHERE id = '{article_id}'")
        code, body = get(web, main_id)
        db.run(f"UPDATE articles SET access_status = 'available' WHERE id = '{article_id}'")
        check(code == 404 and error_code(body) == "EVIDENCE_UNAVAILABLE", f"a private article stayed readable: {code} {body}")
        check(get(web, main_id)[0] == 200, "restoring article access did not restore the read")
        check(fingerprint(layout.artifacts) == artifact_tree and layout.registry_path.read_bytes() == registry_bytes,
              "a failure scenario was not restored exactly (artifact tree or registry file)")
        step("failures: malformed or deleted source registry 503; an invalid expiresAt ('...00z') on the requested source or on an unrelated source 503; "
             "tampered receipt bytes 404; a private article 404; each restored byte-for-byte")
    check(db.scalar("SELECT count(*) FROM graph_activations WHERE reason LIKE 'smoke harness:%'") == 1,
          "the harness activation count is not exactly one")
    return {"harnessActivations": 1, "evidenceReads": reads}

def verdict_read_phase(smoke, db, layout, layout4, world, vid4: str, previous: str, ev4) -> dict:
    """Public graph reads over real HTTP of the VERDICT world's staged version: the rejected/held `eventTime` and `period` are hidden in the real graph output.

    The import never activates, and no production activation exists, so this phase adds ONE explicit TEST-HARNESS activation of `vid4` by psql (the same
    statement shape as `evidence_read_phase`, moving the pointer from `previous`) in the smoke's own throwaway database. It is reported separately
    (`harnessActivations`) and is not an import result. The web application reads the retained receipt of `vid4` with the verdict world's OWN source registry
    (`layout4`). Everything expected is written out by hand from the authored (SYNTHETIC) review: the supply representative's event time is REJECTed (no time,
    unknown precision), its period ALLOWed (still read as stated); the factory's only mention keeps its time while its period is HELD. No public read exposes
    a period, so that one is proven absent from the snapshot artifact (`main`) and from every public body here."""
    import urllib.parse
    from datetime import timezone
    supply, factory = "issue:supply-2026q3", "issue:factory-2026q4"
    web_env = {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(layout.artifacts),
               "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(layout.artifacts), "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(layout4.registry_path)}
    graph_reads = evidence_reads = 0
    spans = [("a", hs.PERIOD_A, supply), ("a2", hs.PERIOD_A2, supply), ("b", hs.PERIOD_B, factory)]
    bodies: list[str] = []

    def get_json(web, path: str) -> tuple[int, dict]:
        code, text = web.get(path)
        bodies.append(text)
        return code, (json.loads(text) if text.startswith("{") else {})

    with smoke.web(web_env) as web:
        code, graph = get_json(web, f"/api/v1/graph?graphVersion={vid4}")
        check(code == 409 and (graph.get("error") or {}).get("code") == "VERSION_UNAVAILABLE", f"the staged verdict version was readable before the harness activation: {code} {graph}")
        at = datetime.now(timezone.utc)
        check(db.scalar("SELECT count(*) FROM graph_activations") == 3, "unexpected activation history before the verdict harness")
        db.run(f"""SELECT pg_advisory_xact_lock(x'7a6f6f7067726170'::bigint);
            UPDATE graph_versions SET active = false WHERE active;
            UPDATE graph_versions SET active = true WHERE id = '{vid4}';
            INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed, admin_id,
                admin_email_snapshot, reason, activated_at)
            VALUES ('{vid4}', '{previous}', 'activate', 'system', true, NULL, 'system',
                'smoke harness: synthetic verdict activation', '{at.isoformat()}')""")
        check(db.scalar("SELECT id FROM graph_versions WHERE active") == vid4 and db.scalar("SELECT count(*) FROM graph_activations") == 4,
              "the verdict harness activation did not apply")
        harness_fingerprint = smoke.table_fingerprint()

        # the real graph output: the pinned version and the default (active) read both hide the rejected time -------------------
        for path in (f"/api/v1/graph?graphVersion={vid4}", "/api/v1/graph"):
            code, graph = get_json(web, path)
            graph_reads += 1
            check(code == 200 and graph["metadata"]["graphVersion"] == vid4, f"{path}: {code} {str(graph)[:300]}")
            nodes = {n["id"]: n for n in graph["nodes"] if n["kind"] == "issue"}
            check(set(nodes) == {supply, factory}, f"{path}: issue nodes {sorted(nodes)}")
            check((nodes[supply]["eventTime"], nodes[supply]["timePrecision"]) == (None, "unknown")
                  and (nodes[factory]["eventTime"], nodes[factory]["timePrecision"]) == ("2026-11-15", "day"),
                  f"{path}: the rejected supply time is not hidden or the unreviewed factory time is not kept: "
                  f"{[(n['id'], n['eventTime'], n['timePrecision']) for n in nodes.values()]}")
        # an issue shared by two companies is read again through the derived edge's `via`: the same withheld time there
        derived = [e for e in graph["edges"] if e["derived"]]
        seen_via = 0
        for edge in derived:
            code, detail = get_json(web, f"/api/v1/graph/edges/{urllib.parse.quote(edge['id'], safe='')}")
            graph_reads += 1
            check(code == 200, f"derived edge detail {edge['id']}: {code} {detail}")
            for via in detail["via"]:
                if via["id"] == supply:
                    check((via["eventTime"], via["timePrecision"]) == (None, "unknown"), f"a derived edge shows the rejected supply time: {via}")
                    seen_via += 1
                if via["id"] == factory:
                    check((via["eventTime"], via["timePrecision"]) == ("2026-11-15", "day"), f"a derived edge changed the factory time: {via}")
                    seen_via += 1
        # no public body carries a rejected or held ORIGINAL value, a verdict or a review word ------------------------------------
        joined = "\n".join(bodies)
        check("2026-09-30" not in joined and "2026Q4" not in joined
              and not any(word in joined for word in ("fieldVerdicts", "withheld", "operator-field-verdict", "contradicted", "ambiguous", "unstated", hs.REVIEWER)),
              "a rejected or held original value, or a verdict, reached a public graph read")

        # the verdict spans are part of their issues' evidence, so the existing public evidence read serves them like geography evidence ----------
        for name, quote, issue_id in spans:
            eid, span = ev4(name, quote), hs.span(world, name, quote)
            code, body = get_json(web, f"/api/v1/evidence/{eid}")
            evidence_reads += 1
            check(code == 200 and body["id"] == eid and body["quote"] == quote and body["start"] == span["start"] and body["end"] == span["end"]
                  and body["articleId"] == span["documentId"] and body["articleVersion"] == span["documentVersion"] and body["quoteVerified"] is True
                  and body["eventIds"] == [issue_id] and body["metadata"]["graphVersion"] == vid4,
                  f"verdict evidence {name}: {code} {str(body)[:300]}")
        check(smoke.table_fingerprint() == harness_fingerprint, "a public read changed a table")
        step(f"verdict world, real graph output (web, artifact source; ONE test-harness activation of the staged verdict version): GET /api/v1/graph pinned and default show the "
             f"supply issue without an event time (unknown precision) and the factory time kept, {seen_via} derived-edge `via` entries agree, no public body carries a rejected or "
             f"held original value or a verdict word, and the three verdict spans are served as evidence of their issues; nothing written")
    check(db.scalar("SELECT count(*) FROM graph_activations WHERE reason LIKE 'smoke harness:%'") == 2,
          "the harness activation count is not exactly two (evidence phase and verdict phase)")
    return {"harnessActivations": 1, "evidenceReads": evidence_reads, "graphReads": graph_reads}

# Words that belong to the retained receipt only: the staged snapshot and every public read must never carry them.
INTERNAL_WORDS = ("operator-final-approval", "automatic-verifier", "approvalBasis", "manual-operator-final-approval", "s3-operator-final-approval",
                  "sourceSupport", "knownLineageCount", "independentSourceCount", "unknownLineageArticles", "duplicateGroups", "operator-declared-origin",
                  "textSha256", "originId")


def approved_world_phase(args, db, layout, scratch: Path) -> dict:
    """A producer-authored world where an operator FINALLY APPROVED a HOLD relation (beside automatic ones) and declared document origins, imported over real processes.

    SYNTHETIC and replay-only (`executionMode: replay`, `recordingKind: authored-test`): a live provider recording needs a paid run and is covered by the Java unit
    tests only. Everything expected is written out by hand in `hs.expected_approvals`, `hs.expected_support` and `hs.expected_origins`; nothing is read back from the
    importer or the verifier under test. It proves that the receipt keeps the approval basis of every used relation, that an operator approval never reads as an
    automatic verdict (on the INVOLVES literal and on the structural basis), that `verifiedAt` is the deciding event's time, that each article's `textSha256` is the
    stored text's hash, that `sourceSupport` counts lineage GROUPS (not articles) and exact-text duplicate groups only, and that none of it reaches the snapshot."""
    from collections import Counter
    world5, env = hs.approved_export(scratch / "approved", PUBLIC_IDS)
    layout5 = Layout(world5, args.ingest_cli)
    layout5.artifacts = layout.artifacts
    smoke5 = Smoke(args, db, layout5)
    status, result, _ = smoke5.jar.run("documents-approved", [base.item(ref) for ref in world5.refs.values()], artifact_root=layout.artifacts)
    check(status == 0 and result and result["status"] == "succeeded", f"the approved world's document import failed: {result}")
    ledgers_before = {name: fingerprint(path) for name, path in layout5.ledgers.items()}
    hid, vid = hs.APPROVED_HANDOFF, version_id(hs.APPROVED_HANDOFF)
    manifest_digest, bundle_digest = hs.digest(env["manifest"]), sha256(hs.canonical(env["bundle"]).encode("utf-8"))
    bundle = env["bundle"]
    status, result, output = smoke5.graph_import("approved", smoke5.request(hid, manifest_digest, bundle_digest))
    check(status == 0 and result and result["status"] == "succeeded" and result["outcome"] == "staged" and result["graphVersionId"] == vid,
          f"the approved handoff was not staged: {result} {output[-800:]}")

    # approval bases: the result states how the staged edges' S3 relations became eligible, from hand-written expectations ---------------
    approvals = hs.expected_approvals(world5)
    kinds = dict(Counter(want["kind"] for want in approvals.values()))
    check(kinds.get("operator-final-approval", 0) >= 1 and kinds.get("automatic-verifier", 0) >= 1,
          f"the authored world must hold at least one operator-approved and one automatic relation: {kinds}")
    check(result["provenance"]["sourceKind"] == "synthetic" and result["provenance"]["executionMode"] == "replay"
          and result["provenance"]["recordingKind"] == "authored-test" and result["provenance"]["approvalBases"] == kinds
          and result["provenance"]["structuralRelationOrigin"] == "manual-operator-review", f"provenance: {result['provenance']}")
    receipt = json.loads((layout.artifacts / "verification_receipt" / f"{vid}.json").read_text("utf-8"))
    check(receipt["bundle"] == bundle and receipt["bundle"]["schemaVersion"] == "zoop-graph-handoff-bundle-6", "the approved receipt does not retain the producer's bundle")
    check(receipt["appVerification"]["approvalBasis"] == "audit-metadata-not-a-verifier-verdict", "the receipt overclaims what an approval basis is")
    used = {(source["relation"]["jobId"], use["relationCandidateId"]): use for source in bundle["sources"] for use in source["reviewUsed"]}
    check(set(used) == set(approvals), f"the used reviews differ from the hand-written approvals: {sorted(used)} vs {sorted(approvals)}")
    for key, want in approvals.items():
        got = used[key]["approvalBasis"]
        check(got["kind"] == want["kind"] and got["reviewer"] == want["reviewer"] and got["revision"] == want["revision"] == used[key]["revision"]
              and isinstance(got["decidedAt"], str) and got["decidedAt"],
              f"the approval basis of {key} is not the hand-written one: {got} vs {want}")
    literals = set()
    for relation in bundle["relations"]:
        if relation["type"] == "FOLLOWS":
            continue
        refs = [(ref["jobId"], ref["id"]) for ref in relation["sourceRefs"]]
        manual = any(approvals[ref]["kind"] == "operator-final-approval" for ref in refs)
        if relation["type"] == "INVOLVES":
            expected = "manual-operator-final-approval" if manual else "independent-verifier-supported-all-claims"
            check(relation["provenance"]["s3SemanticValidation"] == expected, f"an INVOLVES edge mislabels its approval basis: {relation['provenance']}")
            literals.add(expected)
        else:
            expected = "s3-operator-final-approval" if manual else "s3-independent-verifier-supported-all-claims"
            check(relation["provenance"]["origin"] == "manual-operator-review" and relation["provenance"]["basisEligibility"] == expected,
                  f"a structural edge mislabels its approval basis: {relation['provenance']}")
            for basis in relation["basis"]:
                decided = used[(basis["sourceRelation"]["jobId"], basis["sourceRelation"]["relationCandidateId"])]["approvalBasis"]["decidedAt"]
                check(basis["verifiedAt"] == decided, "a structural verification time is not the deciding event's time")
    check("manual-operator-final-approval" in literals, "no INVOLVES edge rests on an operator approval in the authored world")

    # sourceSupport and origins: hand-written, never recomputed with the code under test -------------------------------------------------
    check({i["id"]: i["sourceSupport"] for i in bundle["issues"]} == hs.expected_support(world5), "the issues' sourceSupport is not the hand-written one")
    origins = hs.expected_origins(world5)
    for name, ref in world5.refs.items():
        article = next(a for a in bundle["articles"] if a["documentId"] == ref["documentId"] and a["documentVersion"] == ref["documentVersion"])
        want = origins[name]
        check(article["origin"] == (None if want is None else {**want, "verification": "operator-declared-origin"}),
              f"the origin of {name} is not the operator's declaration: {article['origin']}")
        stored = db.scalar(f"SELECT sha256 FROM artifacts WHERE id = 'text-{ref['documentVersion']}'")
        check(article["textSha256"] == stored, f"the text digest of {name} is not the stored text's hash")
    supports = list(hs.expected_support(world5).values())
    check(any(s["independentSourceCount"] is None for s in supports) and any(s["independentSourceCount"] is not None for s in supports)
          and any(s["articleCount"] > s["knownLineageCount"] > 0 for s in supports),
          "the authored world must hold an unknown and a counted independence and a lineage group with several articles")

    # the snapshot stays format 3 and carries none of it ---------------------------------------------------------------------------
    snapshot_file = layout.artifacts / "graph_snapshot" / f"{vid}.json"
    snapshot_bytes = snapshot_file.read_bytes()
    snapshot = json.loads(snapshot_bytes.decode("utf-8"))
    check(snapshot["snapshotFormat"] == 3 and set(snapshot) == {"snapshotFormat", "versionId", "sourceBundleId", "companies", "issues", "relations", "articles", "evidence"},
          "the approved snapshot is not format 3")
    snapshot_text = snapshot_bytes.decode("utf-8")
    leaked = [word for word in (*INTERNAL_WORDS, *(want["reviewer"] for want in approvals.values() if want["reviewer"]),
                                *(want["originId"] for want in origins.values() if want))
              if word in snapshot_text]
    check(not leaked, f"an approval, an origin or a support count reached the public snapshot: {leaked}")
    status, again, _ = smoke5.graph_import("approved-again", smoke5.request(hid, manifest_digest, bundle_digest))
    check(status == 0 and again and again["outcome"] == "unchanged" and snapshot_file.read_bytes() == snapshot_bytes
          and again["provenance"]["approvalBases"] == kinds, f"retrying the approved import changed the staged bytes or the statement: {again}")
    check({name: fingerprint(path) for name, path in layout5.ledgers.items()} == ledgers_before, "the approved world's ledgers changed")
    step(f"an approved + origin world (SYNTHETIC, replay): staged with approval bases {kinds}, the INVOLVES and structural literals following the hand-written approvals "
         "(an operator approval never reads as the verifier), verifiedAt = the deciding event's time, article text digests = the stored texts, sourceSupport = the "
         "hand-written lineage groups (not article counts) and exact duplicate groups, none of it in the snapshot; a retry is a no-op with identical bytes")
    return {"world": world5, "layout": layout5, "smoke": smoke5, "vid": vid, "bundle": bundle, "approvals": approvals, "origins": origins}


def approved_read_phase(approved: dict, db, layout, previous: str) -> dict:
    """The approved world over real HTTP: ONE more TEST-HARNESS activation (psql, like the other two), then the public graph and evidence reads.

    The receipt now carries approval bases, origins, text digests and sourceSupport; `getEvidence` must still serve the span (it reads only the article's observation
    pins) and no public body may carry any of those internal values."""
    from datetime import timezone
    smoke, vid, world, layout5 = approved["smoke"], approved["vid"], approved["world"], approved["layout"]
    web_env = {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(layout.artifacts),
               "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(layout.artifacts), "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(layout5.registry_path)}
    bodies: list[str] = []

    def get_json(web, path: str) -> tuple[int, dict]:
        code, text = web.get(path)
        bodies.append(text)
        return code, (json.loads(text) if text.startswith("{") else {})

    with smoke.web(web_env) as web:
        code, graph = get_json(web, f"/api/v1/graph?graphVersion={vid}")
        check(code == 409 and (graph.get("error") or {}).get("code") == "VERSION_UNAVAILABLE", f"the staged approved version was readable before activation: {code} {graph}")
        check(db.scalar("SELECT count(*) FROM graph_activations") == 4, "unexpected activation history before the approved harness")
        at = datetime.now(timezone.utc)
        db.run(f"""SELECT pg_advisory_xact_lock(x'7a6f6f7067726170'::bigint);
            UPDATE graph_versions SET active = false WHERE active;
            UPDATE graph_versions SET active = true WHERE id = '{vid}';
            INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed, admin_id,
                admin_email_snapshot, reason, activated_at)
            VALUES ('{vid}', '{previous}', 'activate', 'system', true, NULL, 'system',
                'smoke harness: synthetic approved activation', '{at.isoformat()}')""")
        check(db.scalar("SELECT id FROM graph_versions WHERE active") == vid and db.scalar("SELECT count(*) FROM graph_activations") == 5,
              "the approved harness activation did not apply")
        harness_fingerprint = smoke.table_fingerprint()
        code, graph = get_json(web, f"/api/v1/graph?graphVersion={vid}")
        check(code == 200 and graph["metadata"]["graphVersion"] == vid, f"the approved graph read: {code} {str(graph)[:300]}")
        issue_ids = {n["id"] for n in graph["nodes"] if n["kind"] == "issue"}
        check(issue_ids == set(hs.expected_support(world)), f"the approved graph's issues are not the hand-written ones: {sorted(issue_ids)}")
        evidence_reads = 0
        for name, quote in (("a", hs.EVT_A), ("b", hs.QB)):
            eid, span = hs.evidence_id(world, name, quote), hs.span(world, name, quote)
            code, body = get_json(web, f"/api/v1/evidence/{eid}")
            evidence_reads += 1
            check(code == 200 and body["id"] == eid and body["quote"] == quote and body["start"] == span["start"] and body["end"] == span["end"]
                  and body["articleId"] == span["documentId"] and body["articleVersion"] == span["documentVersion"] and body["quoteVerified"] is True
                  and body["metadata"]["graphVersion"] == vid, f"approved evidence {name}: {code} {str(body)[:300]}")
        joined = "\n".join(bodies)
        reviewers = [want["reviewer"] for want in approved["approvals"].values() if want["reviewer"]]
        leaked = [word for word in (*INTERNAL_WORDS, *reviewers, *(want["originId"] for want in approved["origins"].values() if want)) if word in joined]
        check(not leaked, f"an approval basis, an origin or a support count reached a public read: {leaked}")
        check(smoke.table_fingerprint() == harness_fingerprint, "a public read changed a table")
        step("approved world over real HTTP (ONE more test-harness activation): the staged version is unreadable before it, then the public graph serves its issues and "
             "GET /api/v1/evidence serves two spans from the receipt that now holds approval bases, origins, text digests and sourceSupport; no public body carries any of them")
    return {"harnessActivations": 1, "evidenceReads": evidence_reads}



PATH_IDS = {**PUBLIC_IDS, "KRX:000999": "SYNTH:000003"}      # the chain world's tail company is a third synthetic catalog company
PATH_TAIL = ("SYNTH:000003", "합성투자")
PATH_MIDDLES = ("private", "known", "unmapped")
# What must never reach a public body or the snapshot in ANY mode: the receipt-only path structure and S3 scope keys. The private middle company's id is separate (PATH_MIDDLE_ID):
# the `known` world legitimately publishes it as a company.
PATH_LEAKS = ("structuralPath", "pathCompanies", "businessScope", "productScope", "supplierCompanyId", "customerCompanyId")
PATH_MIDDLE_ID = "SYNTH:000002"
PATH_COUNTS = {"private": {"companies": 2, "issues": 2, "relations": 4, "articles": 3, "evidence": 7},
               "known": {"companies": 3, "issues": 2, "relations": 5, "articles": 3, "evidence": 7},
               "unmapped": {"companies": 2, "issues": 2, "relations": 4, "articles": 3, "evidence": 7}}


def path_world_phase(args, db, layout, scratch: Path) -> dict:
    """Structural paths over real processes: the producer's `chain` world (SYNTHETIC; rel-a also holds SYNTH-4 -> SYNTH-3 -> SYNTH-1) frozen three times by the installed
    `zoop-ai-handoff`, once per middle company: `private` (SYNTH-3 mapped but unpublished: a private pathCompany, never a public node), `known` (SYNTH-3 is public too: a one- and
    a two-relation edge) and `unmapped` (the operator did not map SYNTH-3: the two-relation path is unavailable, never invented). Every expectation is hand-written in
    `hs.expected_chain`; nothing is read back from the importer or the verifier under test.

    A catalogue company the path names only privately must still exist with an equal label (renamed: `company_mismatch`, nothing written); the staged snapshot carries NO path
    data, path company or scope text; the retained receipt keeps the complete bundle and the new check and `structuralPath` note."""
    # The back-dated path activation (path_read_phase) needs this world's S3 relations to become eligible clearly AFTER the last activation, whose timestamp is the real clock of
    # the earlier harness (the world is built within milliseconds of it otherwise): a fixed margin, not a race.
    time.sleep(2)
    world = hs.build_world(scratch / "chain", chain=True)
    layout6 = Layout(world, args.ingest_cli)
    layout6.artifacts = layout.artifacts
    smoke6 = Smoke(args, db, layout6)
    status, result, _ = smoke6.jar.run("documents-paths", [base.item(ref) for ref in world.refs.values()], artifact_root=layout.artifacts)
    check(status == 0 and result and result["status"] == "succeeded", f"the path world's document import failed: {result}")
    db.run(f"INSERT INTO companies (id, name, name_key, search_text) VALUES ('{PATH_TAIL[0]}', '{PATH_TAIL[1]}', '', '')")
    operator = hs.Operator(world)
    exports = {}
    decision_docs = {}      # per mode: the operator's decisions file each handoff was frozen over
    for middle in PATH_MIDDLES:
        decisions = hs.chain_decisions(world, middle)
        for company in decisions["companies"]:
            company["publicId"] = PATH_IDS.get(company["publicId"], company["publicId"])
        decision_docs[middle] = decisions
        exports[middle] = hs.freeze_export(operator, world, f"path-{middle}-1", decisions)
        want, bundle = hs.expected_chain(middle, PATH_IDS), exports[middle]["bundle"]
        check(bundle["schemaVersion"] == "zoop-graph-handoff-bundle-6", f"{middle}: the producer's bundle is not schema 6")
        check([c["id"] for c in bundle["companies"]] == want["companies"] and bundle["pathCompanies"] == want["pathCompanies"],
              f"{middle}: companies {[c['id'] for c in bundle['companies']]} / path companies {bundle['pathCompanies']} are not the hand-written ones")
        paths = {r["target"]: r["structuralPath"] for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO"}
        check(paths == want["paths"], f"{middle}: structural paths {paths} are not the hand-written ones {want['paths']}")
        check(all(r["structuralPath"] is None for r in bundle["relations"] if r["type"] != "STRUCTURALLY_RELATED_TO"), f"{middle}: a non-structural edge carries a path")
    ledgers_before = {name: fingerprint(path) for name, path in layout6.ledgers.items()}
    versions = {middle: version_id(f"path-{middle}-1") for middle in PATH_MIDDLES}
    pins = {middle: (hs.digest(env["manifest"]), sha256(hs.canonical(env["bundle"]).encode("utf-8"))) for middle, env in exports.items()}
    step(f"the chain world frozen three times by the installed zoop-ai-handoff ({', '.join(PATH_MIDDLES)} middle): companies, private path companies and every edge's path "
         "equal the hand-written expectation")

    # a path company that is not in the catalogue with an equal label: refused whole, nothing written --------------------------------------
    before = smoke6.table_fingerprint()
    db.run("UPDATE companies SET name = '다른 이름' WHERE id = 'SYNTH:000002'")
    hs.write_operator(world, decisions=decision_docs["private"])
    status, result, output = smoke6.graph_import("path-private-renamed", smoke6.request("path-private-1", *pins["private"]))
    db.run("UPDATE companies SET name = '합성부품' WHERE id = 'SYNTH:000002'")
    check(status != 0 and result and result["status"] == "failed" and result["failure"]["code"] == "company_mismatch",
          f"a renamed private path company was not refused as company_mismatch: {result} {output[-500:]}")
    check(smoke6.table_fingerprint() == before and not (layout.artifacts / "graph_snapshot" / f"{versions['private']}.json").exists()
          and not (layout.artifacts / "verification_receipt" / f"{versions['private']}.json").exists(), "a refused path import left rows or files behind")

    imported = {}
    for middle in PATH_MIDDLES:
        env, vid = exports[middle], versions[middle]
        hs.write_operator(world, decisions=decision_docs[middle])
        status, result, output = smoke6.graph_import(f"path-{middle}", smoke6.request(f"path-{middle}-1", *pins[middle]))
        check(status == 0 and result and result["status"] == "succeeded" and result["outcome"] == "staged" and result["graphVersionId"] == vid,
              f"{middle}: the path handoff was not staged: {result} {output[-800:]}")
        check(result["counts"] == PATH_COUNTS[middle] and sum(result["evidenceRows"].values()) == 7 and result["active"] is False
              and result["activation"] == "not-activated" and "pathCompanies" not in json.dumps(result),
              f"{middle}: result {result}")
        want = hs.expected_chain(middle, PATH_IDS)
        snapshot_bytes = (layout.artifacts / "graph_snapshot" / f"{vid}.json").read_bytes()
        snapshot = json.loads(snapshot_bytes.decode("utf-8"))
        check(snapshot["snapshotFormat"] == 3 and sorted(c["companyId"] for c in snapshot["companies"]) == want["companies"],
              f"{middle}: the snapshot's public companies are not the hand-written ones: {[c['companyId'] for c in snapshot['companies']]}")
        # The middle company's id is a PUBLIC node only in the `known` world; in `private` and `unmapped` it must not appear in the snapshot at all. The receipt-only path
        # keys and scope text are absent in every mode.
        snapshot_text = snapshot_bytes.decode("utf-8")
        leaked = [word for word in (*PATH_LEAKS, "소재 사업", "intermediate_company_unmapped", *((PATH_MIDDLE_ID,) if middle != "known" else ())) if word in snapshot_text]
        check(not leaked, f"{middle}: path data reached the public snapshot: {leaked}")
        receipt = json.loads((layout.artifacts / "verification_receipt" / f"{vid}.json").read_text("utf-8"))
        check(receipt["bundle"] == env["bundle"] and receipt["manifest"] == env["manifest"], f"{middle}: the receipt does not retain the original")
        app = receipt["appVerification"]
        check("structural_path_closed_over_involves_basis_and_catalog" in app["checks"]
              and app["structuralPath"] == "operator-mapped-basis-chain-not-causality-or-price-direction" and app["semanticTruth"] == "not-verified"
              and app["activation"] == "none", f"{middle}: the receipt's statement of the path: {app}")
        hs.write_operator(world, decisions=decision_docs[middle])
        status, again, _ = smoke6.graph_import(f"path-{middle}-again", smoke6.request(f"path-{middle}-1", *pins[middle]))
        check(status == 0 and again and again["outcome"] == "unchanged" and (layout.artifacts / "graph_snapshot" / f"{vid}.json").read_bytes() == snapshot_bytes,
              f"{middle}: retrying changed the staged bytes: {again}")
        imported[middle] = {"snapshot": snapshot, "receipt": receipt}
    check(db.scalar("SELECT count(*) FROM graph_versions WHERE active") == 1 and smoke6.table_fingerprint()["activations"] == before["activations"],
          "a path import moved the pointer or wrote an activation")
    check({name: fingerprint(path) for name, path in layout6.ledgers.items()} == ledgers_before, "the path world's ledgers changed")
    step("path imports: a renamed private path company is company_mismatch with nothing written; private / known / unmapped stage with the hand-written public companies, "
         "NO path company, path or scope text in any snapshot, the complete bundle plus the structural_path check and the operator-mapped note in the receipt; retries are no-ops")
    return {"world": world, "layout": layout6, "smoke": smoke6, "vids": versions, "exports": exports, "imported": imported}


def path_read_phase(paths: dict, db, layout, previous: str) -> dict:
    """The `private`-middle version over real HTTP: ONE more TEST-HARNESS activation (psql, like the others) BACK-DATED to just after the last activation, so that an asOf
    between that activation and the moment the S3 relations became eligible selects this version while its structural bases are not yet verified.

    A BASIS-ONLY span (SUP, and the second link's sentence) is cited by no issue and no relation, only by a structural basis: it is served (200, no eventIds) only when the
    selected version's receipt proves exactly that relation's basis cites it, and every current rights / row / article / receipt gate still applies. Disclosure exclusions have
    no store in the built application (nothing to drive over HTTP); the relation / issue / evidence exclusions are proven by the Java tests with the real pinned reader."""
    import urllib.parse
    from datetime import timezone
    smoke, world, layout6, vid = paths["smoke"], paths["world"], paths["layout"], paths["vids"]["private"]
    bundle = paths["exports"]["private"]["bundle"]
    want = hs.expected_chain("private", PATH_IDS)
    web_env = {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(layout.artifacts),
               "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(layout.artifacts), "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(layout6.registry_path)}
    bases = [b for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO" for b in r["basis"]]
    verified = min(datetime.fromisoformat(b["verifiedAt"]) for b in bases)
    last = db.scalar("SELECT to_char(max(activated_at) AT TIME ZONE 'UTC' + interval '1 second', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '+00:00' FROM graph_activations")
    t0 = datetime.fromisoformat(last)
    # The first basis became eligible at `verified`. The harness activation sits one second after the last activation (t0) and the asOf "before verification" half a second
    # before `verified`, to the microsecond, so t0 <= asOf < verified is only a question of the margin the sleep at the start of this phase guarantees (>= 2 s).
    before_verification = (verified - timedelta(milliseconds=500)).astimezone(timezone.utc)
    check(t0 <= before_verification < verified, f"the path world was not built at least 1.5 s after the last activation ({t0} vs the first basis verification {verified}): cannot place the harness activation")
    iso = lambda moment: moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")   # noqa: E731

    snapshot = paths["imported"]["private"]["snapshot"]
    basis_only = [("a", hs.SUP), ("a", hs.CHAIN)]
    spans = {hs.evidence_id(world, name, quote): (name, quote, hs.span(world, name, quote)) for name, quote in basis_only}
    direct_id = hs.evidence_id(world, "a", hs.EVT_A)
    direct_events = [i["issueId"] for i in snapshot["issues"] if direct_id in i["evidenceIds"] or direct_id in i["geographyEvidenceIds"]]
    check(direct_events and all(not any(eid in i["evidenceIds"] or eid in i["geographyEvidenceIds"] for i in snapshot["issues"]) for eid in spans)
          and all(eid not in r["evidenceIds"] for r in snapshot["relations"] for eid in spans), "the authored basis spans are cited directly by an issue or a relation")
    reads, graph_reads = 0, 0
    bodies: list[str] = []

    def get(web, evidence_id: str, **params) -> tuple[int, dict]:
        nonlocal reads
        reads += 1
        query = urllib.parse.urlencode(params)
        code, text = web.get(f"/api/v1/evidence/{evidence_id}" + (f"?{query}" if query else ""))
        bodies.append(text)
        return code, (json.loads(text) if text.startswith("{") else {})

    def code_of(body: dict) -> str:
        return (body.get("error") or {}).get("code", "")

    def served(web, evidence_id: str, label: str, **params) -> dict:
        code, body = get(web, evidence_id, **params)
        check(code == 200 and body["id"] == evidence_id and body["quoteVerified"] is True, f"{label}: {code} {str(body)[:300]}")
        return body

    def withheld(web, evidence_id: str, label: str, **params) -> None:
        code, body = get(web, evidence_id, **params)
        check(code == 404 and code_of(body) == "EVIDENCE_UNAVAILABLE", f"{label}: expected 404 EVIDENCE_UNAVAILABLE, got {code} {str(body)[:300]}")

    with smoke.web(web_env) as web:
        code, body = get(web, direct_id, graphVersion=vid)
        check(code == 409 and code_of(body) == "VERSION_UNAVAILABLE", f"the staged path version was readable before activation: {code} {body}")
        activations_before = db.scalar("SELECT count(*) FROM graph_activations")
        check(activations_before == 5, "unexpected activation history before the path harness")
        db.run(f"""SELECT pg_advisory_xact_lock(x'7a6f6f7067726170'::bigint);
            UPDATE graph_versions SET active = false WHERE active;
            UPDATE graph_versions SET active = true WHERE id = '{vid}';
            INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed, admin_id,
                admin_email_snapshot, reason, activated_at)
            VALUES ('{vid}', '{previous}', 'activate', 'system', true, NULL, 'system',
                'smoke harness: synthetic path activation', '{t0.isoformat()}')""")
        check(db.scalar("SELECT id FROM graph_versions WHERE active") == vid and db.scalar("SELECT count(*) FROM graph_activations") == activations_before + 1,
              "the path harness activation did not apply")
        harness_fingerprint = smoke.table_fingerprint()
        artifact_tree, registry_bytes = fingerprint(layout.artifacts), layout6.registry_path.read_bytes()

        # basis200: a span only a structural basis rests on is served without events; the directly cited one keeps its event ----------
        for eid, (name, quote, span) in spans.items():
            body = served(web, eid, f"basis-only evidence {quote!r}")
            check(body["quote"] == quote and body["start"] == span["start"] and body["end"] == span["end"] and body["articleId"] == span["documentId"]
                  and body["articleVersion"] == span["documentVersion"] and body["eventIds"] == [] and body["metadata"]["graphVersion"] == vid
                  and body["metadata"]["partial"] is False and body["sentiment"] is None and body["documentSummary"] is None,
                  f"basis-only evidence body {quote!r}: {str(body)[:300]}")
        direct = served(web, direct_id, "direct evidence")
        check(direct["eventIds"] == direct_events and direct["metadata"]["graphVersion"] == vid, f"direct evidence changed: {direct['eventIds']} vs {direct_events}")
        step("basis-only evidence over HTTP: the two spans only a structural basis cites are 200 with eventIds [] from the receipt of the selected version; the directly cited span keeps its event")

        # asOf: before the basis was verified, before the article was published, after both -------------------------------------------
        for eid, (name, quote, span) in spans.items():
            withheld(web, eid, f"asOf {iso(before_verification)} (before the basis was verified) must not show basis-only evidence {quote!r}", asOf=iso(before_verification))
        body = served(web, direct_id, "direct evidence at the same asOf", asOf=iso(before_verification))
        check(body["metadata"]["graphVersion"] == vid and body["eventIds"] == direct_events,
              f"the asOf before verification did not select the path version or changed the direct evidence: {body['metadata']} {body['eventIds']}")
        now = datetime.now(timezone.utc)
        for eid, (name, quote, span) in spans.items():
            body = served(web, eid, f"asOf now serves basis-only evidence {quote!r}", asOf=iso(now))
            check(body["metadata"]["graphVersion"] == vid and body["eventIds"] == [], f"asOf now: {body['metadata']} {body['eventIds']}")
        for eid in (*spans, direct_id):
            withheld(web, eid, "asOf 2026-10-07 (before the article's publication and the version) must not show the evidence", asOf="2026-10-07T00:00:00Z")
        step("asOf: before the structural basis was verified only the basis-only spans are 404 (the direct one stays 200 on this version); at the current time they are 200; "
             "before the publication (an earlier version) every span is 404")

        # a wrong selected version -----------------------------------------------------------------------------------------------------
        for eid in (*spans, direct_id):
            withheld(web, eid, "the approved version (active before) does not contain the path world's evidence", graphVersion=previous)
        for other in (paths["vids"]["known"], paths["vids"]["unmapped"]):
            code, body = get(web, next(iter(spans)), graphVersion=other)
            check(code == 409 and code_of(body) == "VERSION_UNAVAILABLE", f"a never-activated version was readable: {other} {code}")
        check(smoke.table_fingerprint() == harness_fingerprint, "a public read changed a table")
        step("wrong selected version: the previous active version withholds the evidence it never contained (404); never-activated versions are 409")

        # current rights, article access and the receipt still decide ------------------------------------------------------------------
        original = json.loads(registry_bytes.decode("utf-8"))["sources"][0]["grant"]
        every = (*spans, direct_id)
        for label, change in (("drop store", lambda g: g.update({"allowedOperations": [o for o in g["allowedOperations"] if o != "store"]})),
                              ("drop quote-display", lambda g: g.update({"allowedOperations": [o for o in g["allowedOperations"] if o != "quote-display"]})),
                              ("disabled", lambda g: g.update({"enabled": False})),
                              ("revision", lambda g: g.update({"revision": g["revision"] + "-next"})),
                              ("grant id", lambda g: g.update({"grantId": g["grantId"] + "-other"}))):
            smoke.set_registry(change)
            for eid in every:
                withheld(web, eid, f"a revoked grant ({label}) must withhold {eid}")
            smoke.set_registry(lambda g: (g.clear(), g.update(original)))
            for eid in every:
                served(web, eid, f"restoring the grant ({label}) must restore {eid}")
        article_id = next(iter(spans.values()))[2]["documentId"]
        db.run(f"UPDATE articles SET access_status = 'private' WHERE id = '{article_id}'")
        for eid in every:
            withheld(web, eid, f"a private article must withhold {eid}")
        db.run(f"UPDATE articles SET access_status = 'available' WHERE id = '{article_id}'")
        receipt_path = layout.artifacts / "verification_receipt" / f"{vid}.json"
        receipt_info, receipt_original = receipt_path.stat(), receipt_path.read_bytes()
        receipt_path.write_bytes(receipt_original.replace(b'"activation":"none"', b'"activation":"nope"'))
        check(receipt_path.read_bytes() != receipt_original, "the receipt tamper did not change any byte")
        for eid in every:
            withheld(web, eid, f"tampered receipt bytes must withhold {eid}")
        receipt_path.write_bytes(receipt_original)
        os.utime(receipt_path, ns=(receipt_info.st_atime_ns, receipt_info.st_mtime_ns))
        for eid in every:
            served(web, eid, f"restoring the receipt must restore {eid}")
        check(fingerprint(layout.artifacts) == artifact_tree and layout6.registry_path.read_bytes() == registry_bytes,
              "a failure scenario was not restored exactly (artifact tree or registry file)")
        step("current gates: a revoked grant (store, quote-display, disabled, revision, grant id), a private article and tampered receipt bytes are 404 for basis-only AND direct evidence; "
             "each restored byte-for-byte and served again")

        # no public node or path data in any public body ----------------------------------------------------------------------------
        code, text = web.get(f"/api/v1/graph?graphVersion={vid}")
        bodies.append(text)
        graph_reads += 1
        graph = json.loads(text) if code == 200 else {}
        check(code == 200 and graph["metadata"]["graphVersion"] == vid, f"the path graph read: {code} {text[:300]}")
        nodes = {n["id"] for n in graph["nodes"]}
        check("SYNTH:000002" not in nodes and set(want["companies"]) <= nodes, f"the private middle company is a public node, or a public company is missing: {sorted(nodes)}")
        leaked = [word for word in (*PATH_LEAKS, PATH_MIDDLE_ID) if any(word in text_ for text_ in bodies)]
        check(not leaked, f"a private company id, a path or a scope reached a public body: {leaked}")
        check("소재 사업" not in text, "an S3 business scope reached the public graph")
        check(smoke.table_fingerprint() == harness_fingerprint, "a public read changed a table")
        step("no public node for the private middle company; no path, scope or private company id in any public graph or evidence body")
    check(db.scalar("SELECT count(*) FROM graph_activations WHERE reason LIKE 'smoke harness:%'") == 4, "the harness activation count is not exactly four")
    return {"harnessActivations": 1, "evidenceReads": reads, "graphReads": graph_reads}

IMPACT_KEYS = ("impacts", "proposal", "effects", "verifierRequestDigest", "impactCandidateId", "targetVerdict", "sourceRelation")
IMPACT_LITERALS = ("verifier-reject", "no-evidence", "technical-reject", "impact_precheck_rejected", "s3-independent-verifier-quote-effect")


def impact_leaks(text: str, protected: tuple = ()) -> list:
    """What of an impact row a public document must never carry, found structurally: a reserved FIELD name (an object key at any depth), a string VALUE that is
    one of the reserved status/policy literals, or one of the exact `protected` strings (the unverified proposal's reason and limitation text, candidate ids,
    request digests) inside any string value (in the raw text when the document is not JSON). An identifier that merely contains a reserved word, like the handoff id
    `handoff-impacts-1` in `sourceBundleId`, is a legitimate value and never a leak."""
    try:
        document = json.loads(text)
    except ValueError:
        return [f"text {item!r}" for item in protected if item in text]
    found: list = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in IMPACT_KEYS:
                    found.append(f"key {key}")
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            if node in IMPACT_LITERALS:
                found.append(f"value {node}")
            found.extend(f"text {item!r}" for item in protected if item in node)

    walk(document)
    return found


def impact_world_phase(args, db, layout, scratch: Path) -> dict:
    """The producer's `rich` impact world (SYNTHETIC, replay: the verifier is an AUTHORED replay, not an independent inference) frozen by the installed `zoop-ai-handoff` and imported
    over real processes. Every expected row is written out by hand in `hs.expected_impacts` (only S3 identities, the candidate id and the verifier request digest, are read from
    the S3 result there); nothing is read back from the importer or the verifier under test. The receipt retains the complete bundle with its six impact rows; the staged snapshot
    (format 3), the import result and the rows of PostgreSQL carry none of their content, and the one quote only an impact row cites is a registered, verified body span."""
    world, env = hs.impact_export(scratch / "impacts", PUBLIC_IDS)
    layout7 = Layout(world, args.ingest_cli)
    layout7.artifacts = layout.artifacts
    smoke7 = Smoke(args, db, layout7)
    status, result, _ = smoke7.jar.run("documents-impacts", [base.item(ref) for ref in world.refs.values()], artifact_root=layout.artifacts)
    check(status == 0 and result and result["status"] == "succeeded", f"the impact world's document import failed: {result}")
    ledgers_before = {name: fingerprint(path) for name, path in layout7.ledgers.items()}
    hid, vid = hs.IMPACT_HANDOFF, version_id(hs.IMPACT_HANDOFF)
    manifest_digest, bundle_digest = hs.digest(env["manifest"]), sha256(hs.canonical(env["bundle"]).encode("utf-8"))
    bundle = env["bundle"]
    rows = hs.expected_impacts(world, PUBLIC_IDS)
    check(bundle["schemaVersion"] == "zoop-graph-handoff-bundle-6" and bundle["impacts"] == rows and len(rows) == 6 == bundle["counts"]["impacts"]
          and bundle["policy"]["impacts"] == "s3-independent-verifier-quote-effect", "the producer's impacts are not the hand-written rows")
    check(sorted([(r["status"], r["code"]) for r in rows], key=repr) == sorted(hs.RICH_STATUSES, key=repr), f"the authored world does not hold every status: {rows}")
    inv = hs.evidence_id(world, "a", hs.INV)
    before = smoke7.table_fingerprint()
    status, result, output = smoke7.graph_import("impacts", smoke7.request(hid, manifest_digest, bundle_digest))
    check(status == 0 and result and result["status"] == "succeeded" and result["outcome"] == "staged" and result["graphVersionId"] == vid,
          f"the impact handoff was not staged: {result} {output[-800:]}")
    check(result["counts"] == {"companies": 2, "issues": 2, "relations": 4, "articles": 3, "evidence": 7} and result["active"] is False
          and result["activation"] == "not-activated" and result["publicRead"] == "unavailable", f"the impact import result: {result}")
    leaked = impact_leaks(json.dumps(result), (hs.IMPACT_REASON, "authored impact limitation"))
    check(not leaked, f"impact content reached the import result: {leaked}")
    check(db.scalar("SELECT count(*) FROM graph_versions WHERE active") == 1 and smoke7.table_fingerprint()["activations"] == before["activations"],
          "the impact import moved the pointer or wrote an activation")

    # the quote only an impact row cites: a registered, verified, exact body span tied to the retained receipt ---------------------------
    stored = db.rows(f"SELECT quote, quote_verified, input_kind, verification_artifact_id, offset_unit FROM evidence WHERE id = '{inv}'")
    check(len(stored) == 1 and stored[0]["quote"] == hs.INV and stored[0]["quote_verified"] is True and stored[0]["input_kind"] == "body"
          and stored[0]["offset_unit"] == "unicode_code_point" and stored[0]["verification_artifact_id"] == f"artifact-receipt-{vid}",
          f"the impact-only quote is not a verified body span of this receipt: {stored}")

    # the receipt retains every row; the snapshot carries none of their content -----------------------------------------------------------
    receipt = json.loads((layout.artifacts / "verification_receipt" / f"{vid}.json").read_text("utf-8"))
    check(receipt["bundle"] == bundle and receipt["bundle"]["impacts"] == rows and receipt["manifest"] == env["manifest"], "the receipt does not retain the producer's impact rows")
    check("impact_rows_closed_over_involves_sources_approvals_and_labels" in receipt["appVerification"]["checks"]
          and receipt["appVerification"]["semanticTruth"] == "not-verified" and receipt["appVerification"]["activation"] == "none", "the receipt's statement of the impacts")
    snapshot_file = layout.artifacts / "graph_snapshot" / f"{vid}.json"
    snapshot_bytes = snapshot_file.read_bytes()
    snapshot = json.loads(snapshot_bytes.decode("utf-8"))
    snapshot_text = snapshot_bytes.decode("utf-8")
    private = (hs.IMPACT_REASON, "authored impact limitation", *(r["impactCandidateId"] for r in rows if r["impactCandidateId"]),
               *(r["verifierRequestDigest"] for r in rows if r["verifierRequestDigest"]))
    check(snapshot["snapshotFormat"] == 3 and set(snapshot) == {"snapshotFormat", "versionId", "sourceBundleId", "companies", "issues", "relations", "articles", "evidence"},
          "the impact snapshot is not format 3")
    leaked = impact_leaks(snapshot_text, private)
    check(snapshot["sourceBundleId"] == hid, "the snapshot's source bundle id is not the impact handoff id (an id containing a reserved word is legitimate)")
    check(not leaked, f"impact content reached the public snapshot: {leaked}")
    spans = {e["evidenceId"] for e in snapshot["evidence"]}
    check(inv in spans and all(inv not in i["evidenceIds"] and inv not in i["geographyEvidenceIds"] for i in snapshot["issues"])
          and all(inv not in r["evidenceIds"] for r in snapshot["relations"]), "the impact-only quote is cited by an issue or a relation, or is not a snapshot span")
    status, again, _ = smoke7.graph_import("impacts-again", smoke7.request(hid, manifest_digest, bundle_digest))
    check(status == 0 and again and again["outcome"] == "unchanged" and snapshot_file.read_bytes() == snapshot_bytes, f"retrying the impact import changed the staged bytes: {again}")
    check({name: fingerprint(path) for name, path in layout7.ledgers.items()} == ledgers_before, "the impact world's ledgers changed")
    step("an impact world (SYNTHETIC replay, authored verifier): six hand-written rows (verified positive with an impact-only quote, verifier-reject, verified negative, verified undetermined, "
         "no-evidence, precheck-rejected) retained in the receipt; the snapshot, import result and database carry no proposal, effect, label, candidate id or verifier digest; the "
         "impact-only quote is a registered verified body span; a retry is a no-op with identical bytes")
    return {"world": world, "layout": layout7, "smoke": smoke7, "vid": vid, "bundle": bundle, "rows": rows, "inv": inv, "private": private}


def impact_read_phase(impact: dict, db, layout, previous: str) -> dict:
    """The impact version over real HTTP: ONE more TEST-HARNESS activation (psql, now), then GET /api/v1/evidence/{id}.

    The impact-only quote (`INV`, cited by no issue, relation or structural basis) shares its article version with one candidate structural basis whose receipt entry does not cite it
    (valid non-membership) and with the supply INVOLVES edge whose verified row lists it among the verifier-mapped effects: it is 200 with empty eventIds, no label or proposal in
    the body. There is no impact time in the S3 result, so no time is invented: the visible edge and the article's publication decide an asOf, exactly as for every other span."""
    import urllib.parse
    from datetime import timezone
    smoke, world, layout7, vid = impact["smoke"], impact["world"], impact["layout"], impact["vid"]
    web_env = {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(layout.artifacts),
              "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(layout.artifacts), "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(layout7.registry_path)}
    inv = impact["inv"]
    inv_span = hs.span(world, "a", hs.INV)
    direct_id = hs.evidence_id(world, "a", hs.EVT_A)
    snapshot = json.loads((layout.artifacts / "graph_snapshot" / f"{vid}.json").read_text("utf-8"))
    direct_events = [i["issueId"] for i in snapshot["issues"] if direct_id in i["evidenceIds"] or direct_id in i["geographyEvidenceIds"]]
    check(direct_events, "the authored direct span is cited by no issue")
    reads, graph_reads = 0, 0
    bodies: list[str] = []

    def get(web, evidence_id: str, **params) -> tuple[int, dict]:
        nonlocal reads
        reads += 1
        query = urllib.parse.urlencode(params)
        code, text = web.get(f"/api/v1/evidence/{evidence_id}" + (f"?{query}" if query else ""))
        bodies.append(text)
        return code, (json.loads(text) if text.startswith("{") else {})

    def code_of(body: dict) -> str:
        return (body.get("error") or {}).get("code", "")

    def served(web, evidence_id: str, label: str, **params) -> dict:
        code, body = get(web, evidence_id, **params)
        check(code == 200 and body["id"] == evidence_id and body["quoteVerified"] is True, f"{label}: {code} {str(body)[:300]}")
        return body

    def withheld(web, evidence_id: str, label: str, **params) -> None:
        code, body = get(web, evidence_id, **params)
        check(code == 404 and code_of(body) == "EVIDENCE_UNAVAILABLE", f"{label}: expected 404 EVIDENCE_UNAVAILABLE, got {code} {str(body)[:300]}")

    with smoke.web(web_env) as web:
        code, body = get(web, inv, graphVersion=vid)
        check(code == 409 and code_of(body) == "VERSION_UNAVAILABLE", f"the staged impact version was readable before activation: {code} {body}")
        activations_before = db.scalar("SELECT count(*) FROM graph_activations")
        check(activations_before == 6, "unexpected activation history before the impact harness")
        at = datetime.now(timezone.utc)
        db.run(f"""SELECT pg_advisory_xact_lock(x'7a6f6f7067726170'::bigint);
            UPDATE graph_versions SET active = false WHERE active;
            UPDATE graph_versions SET active = true WHERE id = '{vid}';
            INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed, admin_id,
                admin_email_snapshot, reason, activated_at)
            VALUES ('{vid}', '{previous}', 'activate', 'system', true, NULL, 'system',
                'smoke harness: synthetic impact activation', '{at.isoformat()}')""")
        check(db.scalar("SELECT id FROM graph_versions WHERE active") == vid and db.scalar("SELECT count(*) FROM graph_activations") == activations_before + 1,
              "the impact harness activation did not apply")
        harness_fingerprint = smoke.table_fingerprint()
        artifact_tree, registry_bytes = fingerprint(layout.artifacts), layout7.registry_path.read_bytes()

        # impact-only quote: 200, empty eventIds, nothing of the impact row in the body ----------------------------------------------------
        body = served(web, inv, "the impact-only quote")
        check(body["quote"] == hs.INV and body["start"] == inv_span["start"] and body["end"] == inv_span["end"] and body["articleId"] == inv_span["documentId"]
              and body["articleVersion"] == inv_span["documentVersion"] and body["eventIds"] == [] and body["metadata"]["graphVersion"] == vid
              and body["metadata"]["partial"] is False and body["sentiment"] is None and body["documentSummary"] is None, f"impact-only evidence body: {str(body)[:300]}")
        check(set(body) == {"id", "quote", "start", "end", "articleId", "articleVersion", "article", "quoteVerified", "eventIds", "metadata", "sentiment", "documentVersion",
                            "documentSummary", "analysisStatus", "analysisProvenance", "resultVersion"}, f"the evidence response shape changed: {sorted(body)}")
        direct = served(web, direct_id, "direct evidence")
        check(direct["eventIds"] == direct_events and direct["metadata"]["graphVersion"] == vid, f"direct evidence changed: {direct['eventIds']} vs {direct_events}")
        step("impact-only evidence over HTTP: the quote only a verified impact row cites is 200 with eventIds [] (the candidate structural basis of its article does not cite it); "
             "the response shape is unchanged and the directly cited span keeps its event")

        # asOf and the selected version ----------------------------------------------------------------------------------------------------
        served(web, inv, "asOf now", asOf=at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
        for stamp in ("2026-10-07T00:00:00Z", "2026-10-09T00:00:00Z"):
            withheld(web, inv, f"asOf {stamp} (before the version and the article's publication in the version active then) must not show the quote", asOf=stamp)
        withheld(web, inv, "the path version (active before) does not contain the impact-only quote", graphVersion=previous)
        code, body = get(web, inv, graphVersion=version_id(HANDOFFS[0]))
        check(code == 409 and code_of(body) == "VERSION_UNAVAILABLE", f"a never-activated version was readable: {code}")
        step("asOf now is 200; asOf before the version existed is 404 (an earlier version never contained the quote); the previously active version withholds it (404); a never-activated version is 409")

        # current rights, article access and the receipt still decide ---------------------------------------------------------------------
        original = json.loads(registry_bytes.decode("utf-8"))["sources"][0]["grant"]
        every = (inv, direct_id)
        for label, change in (("drop store", lambda g: g.update({"allowedOperations": [o for o in g["allowedOperations"] if o != "store"]})),
                              ("drop quote-display", lambda g: g.update({"allowedOperations": [o for o in g["allowedOperations"] if o != "quote-display"]})),
                              ("disabled", lambda g: g.update({"enabled": False})),
                              ("revision", lambda g: g.update({"revision": g["revision"] + "-next"})),
                              ("grant id", lambda g: g.update({"grantId": g["grantId"] + "-other"}))):
            smoke.set_registry(change)
            for eid in every:
                withheld(web, eid, f"a revoked grant ({label}) must withhold {eid}")
            smoke.set_registry(lambda g: (g.clear(), g.update(original)))
            for eid in every:
                served(web, eid, f"restoring the grant ({label}) must restore {eid}")
        db.run(f"UPDATE articles SET access_status = 'private' WHERE id = '{inv_span['documentId']}'")
        for eid in every:
            withheld(web, eid, f"a private article must withhold {eid}")
        db.run(f"UPDATE articles SET access_status = 'available' WHERE id = '{inv_span['documentId']}'")
        receipt_path = layout.artifacts / "verification_receipt" / f"{vid}.json"
        receipt_info, receipt_original = receipt_path.stat(), receipt_path.read_bytes()
        receipt_path.write_bytes(receipt_original.replace(b'"activation":"none"', b'"activation":"nope"'))
        check(receipt_path.read_bytes() != receipt_original, "the receipt tamper did not change any byte")
        for eid in every:
            withheld(web, eid, f"tampered receipt bytes must withhold {eid}")
        receipt_path.write_bytes(receipt_original)
        os.utime(receipt_path, ns=(receipt_info.st_atime_ns, receipt_info.st_mtime_ns))
        for eid in every:
            served(web, eid, f"restoring the receipt must restore {eid}")
        check(fingerprint(layout.artifacts) == artifact_tree and layout7.registry_path.read_bytes() == registry_bytes,
              "a failure scenario was not restored exactly (artifact tree or registry file)")
        step("current gates: a revoked grant (store, quote-display, disabled, revision, grant id), a private article and tampered receipt bytes are 404 for the impact-only AND the direct span; "
             "each restored byte-for-byte and served again")

        # nothing of an impact row in any public body ----------------------------------------------------------------------------------------
        code, text = web.get(f"/api/v1/graph?graphVersion={vid}")
        bodies.append(text)
        graph_reads += 1
        check(code == 200 and json.loads(text)["metadata"]["graphVersion"] == vid, f"the impact graph read: {code} {text[:300]}")
        leaked = [item for text_ in bodies for item in impact_leaks(text_, impact["private"])]
        check(not leaked, f"impact content reached a public body: {leaked}")
        check(smoke.table_fingerprint() == harness_fingerprint, "a public read changed a table")
        step("no proposal, effect, label, candidate id or verifier digest in any public graph or evidence body; no read changed a table")

        # the publication boundary of the SAME impact version: TEST-ONLY historical activation rows (psql, at the very end) -----------------------------------
        # The earlier asOf checks select OLDER versions (the fixtures). To prove the article's publication time with the impact version itself selected on both sides, the
        # smoke adds history rows in the throwaway database: the selector's own rule is "the last pointer change at or before asOf, newest id first on a tie", the fixture
        # `fixture-2026-10-08` was seeded at exactly the authored articles' publication instant, so one row an hour before the boundary and one at the same instant (a higher
        # id wins the tie) make the impact version the selected one on both sides. Nothing else moves: the active pointer, the stored snapshot and the freeze/import
        # times are untouched, no production selector or activation route changes, and the rows carry their own reason (`smoke history:`), not the harness one.
        article = next(a for a in impact["bundle"]["articles"] if a["articleId"] == inv_span["documentId"])
        check(article["publicationPrecision"] == "datetime" and article["publishedAt"], f"the authored article is not published at an instant: {article['publishedAt']}")
        boundary = datetime.fromisoformat(str(article["publishedAt"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        stamp = lambda moment: moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")   # noqa: E731
        around = db.rows(f"""SELECT version_id, to_char(activated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00' AS at FROM graph_activations
            WHERE pointer_changed AND activated_at > '{stamp(boundary - timedelta(hours=1))}' AND activated_at <= '{stamp(boundary + timedelta(seconds=1))}'
            ORDER BY activated_at, id""")
        check(all(row["at"] == stamp(boundary) for row in around) and len(around) <= 1,
              f"the pointer changes around the publication boundary are not the one fixture seed at exactly {stamp(boundary)}: {around}")
        history_rows = [boundary - timedelta(hours=1)] + ([boundary] if around else [])
        history_before = db.scalar("SELECT count(*) FROM graph_activations")
        active_now = db.scalar("SELECT id FROM graph_versions WHERE active")
        for moment in history_rows:
            db.run(f"""INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed, admin_id,
                admin_email_snapshot, reason, activated_at)
                VALUES ('{vid}', 'fixture-2026-10-01', 'activate', 'system', true, NULL, 'system',
                    'smoke history: synthetic historical activation around the article publication', '{stamp(moment)}')""")
        check(db.scalar("SELECT count(*) FROM graph_activations") == history_before + len(history_rows)
              and db.scalar("SELECT id FROM graph_versions WHERE active") == active_now == vid, "the historical rows moved the pointer or were not written")
        before_publication, after_publication = boundary - timedelta(milliseconds=500), boundary + timedelta(milliseconds=500)
        # `graphVersion` together with `asOf` is refused (422) unless it IS the version active at asOf: a 404 here therefore proves the impact version was selected and the
        # publication time alone withheld the span; the 200 side reports the selected version in its own metadata.
        for eid in (inv, direct_id):
            withheld(web, eid, f"asOf {stamp(before_publication)}, the impact version selected, before the article's publication must not show {eid}",
                     graphVersion=vid, asOf=stamp(before_publication).replace("+00:00", "Z"))
        body = served(web, inv, "asOf just after the publication, the impact version selected", graphVersion=vid, asOf=stamp(after_publication).replace("+00:00", "Z"))
        check(body["metadata"]["graphVersion"] == vid and body["eventIds"] == [] and body["quote"] == hs.INV, f"impact-only evidence after the publication: {body['metadata']} {body['eventIds']}")
        body = served(web, direct_id, "direct evidence just after the publication", graphVersion=vid, asOf=stamp(after_publication).replace("+00:00", "Z"))
        check(body["metadata"]["graphVersion"] == vid and body["eventIds"] == direct_events, f"direct evidence after the publication: {body['metadata']} {body['eventIds']}")
        code, body = get(web, inv, graphVersion=previous, asOf=stamp(after_publication).replace("+00:00", "Z"))
        check(code == 422 and code_of(body) == "INVALID_REQUEST", f"a graphVersion that is not the version active at asOf was not refused: {code} {str(body)[:200]}")
        historical = len(history_rows)
        step(f"publication boundary of the SAME impact version ({historical} test-only historical activation row(s) at the fixture's own instants, reason 'smoke history:'): asOf half a second "
             "before the article's publication is 404 for the impact-only and the direct span although graphVersion pins the impact version (a mismatch would be 422); half a second after "
             "both are 200 with metadata.graphVersion = the impact version; a pin that is not the version active at asOf is 422")
    check(db.scalar("SELECT count(*) FROM graph_activations WHERE reason LIKE 'smoke harness:%'") == 5, "the harness activation count is not exactly five")
    check(db.scalar("SELECT count(*) FROM graph_activations WHERE reason LIKE 'smoke history:%'") == historical, "the historical activation count is not the inserted one")
    return {"harnessActivations": 1, "historicalActivations": historical, "evidenceReads": reads, "graphReads": graph_reads}




def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--handoff-cli", required=True, type=Path)
    parser.add_argument("--ingest-cli", required=True, type=Path)
    parser.add_argument("--java", default=None, help="java binary (default: $JAVA_HOME/bin/java, then PATH)")
    parser.add_argument("--psql-container", default=None, help="database container to `docker exec psql` in")
    parser.add_argument("--psql", default=shutil.which("psql"), help="host psql (used without --psql-container)")
    parser.add_argument("--db-user", default=None)
    parser.add_argument("--db-name", default=None)
    parser.add_argument("--no-with-evidence-read", dest="with_evidence_read", action="store_false",
                        help="skip the public GET /api/v1/evidence/{id} phase (it needs the TEST-HARNESS activation of one staged version)")
    args = parser.parse_args()
    for name in ("DB_URL", "DB_USERNAME", "DB_PASSWORD"):
        check(os.environ.get(name), f"{name} must be set (a dedicated loopback database)")
    args.java = args.java or (str(Path(os.environ["JAVA_HOME"]) / "bin" / "java") if os.environ.get("JAVA_HOME") else shutil.which("java"))
    check(args.java, "no java: set JAVA_HOME or pass --java")
    args.jar, args.handoff_cli, args.ingest_cli = args.jar.resolve(), args.handoff_cli.resolve(), args.ingest_cli.resolve()
    check(args.jar.is_file(), "--jar does not exist (build it with ./api/gradlew -p api assemble)")
    for cli in (args.handoff_cli, args.ingest_cli):
        check(cli.is_file() and os.access(cli, os.X_OK), f"{cli.name} is not an executable file")
    db = base.Database(os.environ["DB_URL"], args.db_user or os.environ["DB_USERNAME"], os.environ["DB_PASSWORD"], args.db_name,
                       args.psql_container, args.psql)
    if db.tables_exist():
        check(db.scalar("SELECT (SELECT count(*) FROM articles) + (SELECT count(*) FROM article_versions) + (SELECT count(*) FROM artifacts)"
                        " + (SELECT count(*) FROM graph_versions) + (SELECT count(*) FROM evidence) = 0"),
              "the database already holds document or graph rows: use a dedicated empty database")

    # ---- the authored world and two frozen handoffs, through the installed handoff CLI ---------------------------------
    scratch = Path(tempfile.mkdtemp(prefix="zoop-graphimport-world-")).resolve()
    atexit.register(shutil.rmtree, scratch, True)
    world = hs.build_world(scratch / "owned")
    decisions = hs.decisions_doc(world)
    for company in decisions["companies"]:
        company["publicId"] = PUBLIC_IDS[company["publicId"]]
    hs.write_operator(world, decisions=decisions)
    operator = hs.Operator(world)
    manifests = {hid: hs.manifest_doc(world, hid, hs.file_hashes(world.root)) for hid in HANDOFFS}
    for hid, manifest in manifests.items():
        frozen = operator.cli("freeze", manifest)
        check(frozen["state"] == "ready" and frozen["publication"] == "not-published", f"freeze {hid}: {frozen}")
    exported = {hid: operator.cli("export", operator.sel(hid)) for hid in HANDOFFS}
    pins = {}
    for hid in HANDOFFS:
        manifest_digest = hs.digest(manifests[hid])
        bundle_digest = sha256(hs.canonical(exported[hid]["bundle"]).encode("utf-8"))
        check(manifest_digest == exported[hid]["receipt"]["manifestDigest"] and bundle_digest == exported[hid]["receipt"]["bundleDigest"],
              f"{hid}: the producer's digests are not the canonical hashes")
        pins[hid] = (manifest_digest, bundle_digest)
    layout = Layout(world, args.ingest_cli)
    smoke = Smoke(args, db, layout)
    ledgers_before = {name: fingerprint(path) for name, path in layout.ledgers.items()}
    step("two handoffs frozen by the installed zoop-ai-handoff over the authored S2/S3 world (synthetic company ids SYNTH:*)")

    # ---- the app's own documents, registered by the jar's document import ----------------------------------------------
    items = [base.item(ref) for ref in world.refs.values()]
    status, result, _ = smoke.jar.run("documents", items, artifact_root=layout.artifacts)
    check(status == 0 and result and result["status"] == "succeeded", f"document import failed: {result}")
    db.run("INSERT INTO companies (id, name, name_key, search_text) VALUES "
           + ", ".join(f"('{cid}', '{name}', '', '')" for cid, name in COMPANIES))
    step("three source documents registered by the document import; two synthetic catalog companies inserted")

    # ---- a real active pointer to leave untouched ----------------------------------------------------------------------
    with smoke.web({"ZOOP_GRAPH_SNAPSHOT_SOURCE": "fixture"}, ready="Graph fixture fixture-2026-10-08 "):
        pass
    active_before = db.scalar("SELECT id FROM graph_versions WHERE active")
    history_before = db.scalar("SELECT coalesce(md5(string_agg(a::text, '|' ORDER BY a.id)), '') FROM graph_activations a")
    check(active_before == "fixture-2026-10-08", f"unexpected active fixture version {active_before}")
    check(db.scalar("SELECT count(*) FROM graph_activations") == 2, "the fixture activation history is not two rows")
    step("fixture versions seeded: fixture-2026-10-08 is the active pointer with two activation rows")

    # ---- the import --------------------------------------------------------------------------------------------------
    hid = HANDOFFS[0]
    vid = version_id(hid)
    manifest_digest, bundle_digest = pins[hid]
    before = smoke.table_fingerprint()
    status, result, output = smoke.graph_import("first", smoke.request(hid, manifest_digest, bundle_digest))
    check(status == 0 and result and result["status"] == "succeeded", f"the import failed: {result} {output[-800:]}")
    check(result["outcome"] == "staged" and result["graphVersionId"] == vid and result["handoffId"] == hid, f"unexpected result {result}")
    check(result["publication"] == "not-published" and result["activation"] == "not-activated" and result["active"] is False
          and result["publicRead"] == "unavailable" and result["nextActivation"] == "unsupported", f"the result overclaims: {result}")
    check(result["digests"] == {"manifest": manifest_digest, "bundle": bundle_digest,
                                "content": exported[hid]["receipt"]["contentDigest"]}, f"digests: {result['digests']}")
    check(result["provenance"]["sourceKind"] == "synthetic" and result["provenance"]["executionMode"] == "replay"
          and result["provenance"]["relationOrigins"] == {"manual-operator-review": 1, "s2-comparison-with-operator-decision": 1,
                                                          "s3-relation": 2}, f"provenance: {result['provenance']}")
    check(result["quoteVerification"] == "quote-integrity-only", "the quote check overclaims")
    check(result["counts"] == {"companies": 2, "issues": 2, "relations": 4, "articles": 3, "evidence": 6}, f"counts: {result['counts']}")
    check(result["evidenceRows"] == {"registered": 6, "existing": 0}, f"evidence rows: {result['evidenceRows']}")
    step("import: real handoff export + per-observation ingestion export --require-store, 6 evidence rows and an inactive version staged")

    # the version row and the untouched pointer ------------------------------------------------------------------------
    row = db.rows(f"""SELECT id, kind, active, review_revision, created_by, policy_version, source_label, issue_count, relation_count,
        article_count, snapshot_artifact_id, rule_revision, candidate_count, published_at IS NULL AS unpublished
        FROM graph_versions WHERE id = '{vid}'""")
    check(len(row) == 1, f"graph_versions rows for {vid}: {row}")
    row = row[0]
    check(row["kind"] == "snapshot" and row["active"] is False and row["review_revision"] == 0 and row["unpublished"] is True
          and row["created_by"] == "operator:smoke-operator" and row["policy_version"] == "zoop-public-projection-policy-1"
          and row["source_label"] == f"graph-handoff:{hid}" and (row["issue_count"], row["relation_count"], row["article_count"]) == (2, 4, 3)
          and row["snapshot_artifact_id"] == f"artifact-{vid}" and row["rule_revision"] is None and row["candidate_count"] is None,
          f"version row: {row}")
    check(db.scalar("SELECT id FROM graph_versions WHERE active") == active_before, "the active pointer moved")
    check(db.scalar("SELECT count(*) FROM graph_versions WHERE active") == 1, "not exactly one active version")
    check(db.scalar("SELECT coalesce(md5(string_agg(a::text, '|' ORDER BY a.id)), '') FROM graph_activations a") == history_before,
          "the activation history changed")
    check(db.scalar(f"SELECT count(*) FROM graph_activations WHERE version_id = '{vid}'") == 0, "the import wrote an activation")
    step("the active pointer, its history and every other version are untouched; the staged row is inactive, unpublished, revision 0")

    # evidence: hand-written ids, code point offsets, exact quotes, the retained receipt as verification artifact --------
    spans = [("a", hs.EVT_A), ("a", hs.GEO_A), ("a", hs.SUP), ("a2", hs.EVT_A2), ("b", hs.QB), ("b", hs.GEO_B)]
    rows = {r["id"]: r for r in db.rows("""SELECT id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset,
        offset_unit, input_kind, raw_locator_ids, quote_verified, verification_artifact_id, summary_analysis_id FROM evidence""")}
    check(set(rows) == {hs.evidence_id(world, name, quote) for name, quote in spans}, "evidence ids differ from the hand-written formula")
    for name, quote in spans:
        span = hs.span(world, name, quote)
        stored = rows[hs.evidence_id(world, name, quote)]
        check(stored["quote"] == quote and stored["start_offset"] == span["start"] and stored["end_offset"] == span["end"]
              and stored["article_id"] == span["documentId"] and stored["article_version"] == span["documentVersion"]
              and stored["offset_unit"] == "unicode_code_point" and stored["input_kind"] == "body"
              and stored["text_artifact_id"] == "text-" + span["documentVersion"] and stored["summary_analysis_id"] is None
              and stored["raw_locator_ids"] and all(isinstance(x, str) for x in stored["raw_locator_ids"]),
              f"evidence row of {name}: {stored}")
        check(stored["quote_verified"] is True and stored["verification_artifact_id"] == f"artifact-receipt-{vid}",
              f"the evidence is not tied to the retained receipt: {stored}")
    step("evidence rows: app formula ids, exact quotes at code point offsets, verification artifact = the retained receipt")

    # the two artifacts and their files ---------------------------------------------------------------------------------
    artifacts = {a["id"]: a for a in db.rows("SELECT id, kind, storage_uri, sha256, bytes, media_type FROM artifacts "
                                             f"WHERE id IN ('artifact-{vid}', 'artifact-receipt-{vid}')")}
    check(set(artifacts) == {f"artifact-{vid}", f"artifact-receipt-{vid}"}, f"artifacts: {sorted(artifacts)}")
    snapshot_file = layout.artifacts / "graph_snapshot" / f"{vid}.json"
    receipt_file = layout.artifacts / "verification_receipt" / f"{vid}.json"
    for artifact_id, path, kind in ((f"artifact-{vid}", snapshot_file, "graph_snapshot"), (f"artifact-receipt-{vid}", receipt_file, "verification_receipt")):
        raw = path.read_bytes()
        record = artifacts[artifact_id]
        check(stat.S_IMODE(path.stat().st_mode) == 0o600, f"{path.name} is not owner-only")
        check(record["kind"] == kind and record["sha256"] == sha256(raw) and record["bytes"] == len(raw)
              and record["storage_uri"] == f"artifact-root:{path.parent.name}/{path.name}" and record["media_type"] == "application/json",
              f"artifact row {record}")
    snapshot = json.loads(snapshot_file.read_text("utf-8"))
    check(set(snapshot) == {"snapshotFormat", "versionId", "sourceBundleId", "companies", "issues", "relations", "articles", "evidence"}
          and snapshot["snapshotFormat"] == 3 and snapshot["versionId"] == vid and snapshot["sourceBundleId"] == hid,
          "the snapshot is not format 3 of this handoff")
    check({c["companyId"] for c in snapshot["companies"]} == {cid for cid, _ in COMPANIES} and len(snapshot["issues"]) == 2
          and len(snapshot["relations"]) == 4 and len(snapshot["articles"]) == 3 and len(snapshot["evidence"]) == 6, "snapshot content")
    check(sorted(str(a["publishedAt"]) for a in snapshot["articles"]) == sorted(["2026-10-08T00:00:00Z", "2026-10-08T00:00:00Z", "None"]),
          f"article publication times: {[a['publishedAt'] for a in snapshot['articles']]}")
    structural = next(r for r in snapshot["relations"] if r["relationType"] == "STRUCTURALLY_RELATED_TO")
    check(structural["basis"][0]["validFrom"] is None and structural["basis"][0]["validUntil"] is None,
          "an unknown validity was not kept unknown")
    # Format 3 facts, written by hand from the authored world (never derived from the writer under test): the issues' period, assertion status,
    # mention references (mention id + the article version of its document) and representative, and the structural basis' own id, business
    # relation type, countries and source article versions. Mentions are the source events whose document the issue's evidence cites.
    pinned = {name: {"articleId": ref["documentId"], "articleVersion": ref["documentVersion"]} for name, ref in world.refs.items()}
    issues = {i["issueId"]: i for i in snapshot["issues"]}
    check(set(issues) == {"issue:supply-2026q3", "issue:factory-2026q4"}, f"snapshot issues: {sorted(issues)}")
    supply, factory = issues["issue:supply-2026q3"], issues["issue:factory-2026q4"]
    check((supply["period"], supply["assertionStatus"], factory["period"], factory["assertionStatus"])
          == ("2026Q3", "announced", "2026Q4", "announced"), "an issue period or assertion status is not the producer's")
    check(supply["mentions"] == sorted(({"mentionId": mention_id(pinned[name], local), **pinned[name]} for name, local in (("a", "m-a"), ("a2", "m-a2"))),
                                       key=lambda mention: mention["mentionId"])
          and supply["representativeMentionId"] == mention_id(pinned["a"], "m-a"), f"supply mentions: {supply['mentions']} {supply['representativeMentionId']}")
    check(factory["mentions"] == [{"mentionId": mention_id(pinned["b"], "m-b"), **pinned["b"]}] and factory["representativeMentionId"] is None,
          f"factory mentions: {factory['mentions']} {factory['representativeMentionId']}")
    relation_key = hs.find(world.jobs["rel-a"], "SUPPLIES", "SYNTH-3", "SYNTH-1")["relationKey"]
    (item,) = structural["basis"]
    producer_basis = next(r for r in exported[hid]["bundle"]["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO")["basis"][0]
    check(item["basisId"] == relation_key and item["relationType"] == "SUPPLIES" and item["countries"] == [] and item["articles"] == [pinned["a"]]
          and datetime.fromisoformat(item["verifiedAt"]) == datetime.fromisoformat(producer_basis["verifiedAt"]), f"structural basis: {item}")
    check(all(r["basis"] == [] for r in snapshot["relations"] if r["relationType"] != "STRUCTURALLY_RELATED_TO"),
          "a non-structural relation carries a basis")
    receipt = json.loads(receipt_file.read_text("utf-8"))
    check(receipt["bundle"] == exported[hid]["bundle"] and receipt["manifest"] == manifests[hid], "the receipt does not retain the original")
    check(hs.digest(receipt["manifest"]) == manifest_digest and sha256(hs.canonical(receipt["bundle"]).encode("utf-8")) == bundle_digest,
          "the receipt's manifest and bundle do not hash to the pins")
    check(receipt["appVerification"]["semanticTruth"] == "not-verified" and receipt["appVerification"]["activation"] == "none",
          "the receipt overclaims")
    # The original mentions the receipt retains: per issue exactly the S2 values of each source document (title, action, time, period, status, background,
    # participants as extracted), never the merged issue's, never verified. Hand-written from the authored world, not read from the producer's export.
    receipt_issues = {i["id"]: i for i in receipt["bundle"]["issues"]}
    check(receipt_issues["issue:supply-2026q3"]["mentions"] == expected_mentions(
        world, ("a", "m-a", hs.EVT_A, "합성 공급 계약", "공급 계약 발표", "2026-09-30", "2026Q3", DOC_A),
        ("a2", "m-a2", hs.EVT_A2, "합성 공급 계약 체결 공개", "공급 계약 발표", "2026-09-30", "2026Q3", [MAPPED])),
          f"supply mentions: {receipt_issues['issue:supply-2026q3']['mentions']}")
    check(receipt_issues["issue:factory-2026q4"]["mentions"] == expected_mentions(
        world, ("b", "m-b", hs.QB, "합성 공장 착공", "공장 착공 알림", "2026-11-15", "2026Q4", DOC_B)),
          f"factory mentions: {receipt_issues['issue:factory-2026q4']['mentions']}")
    check(receipt["bundle"]["schemaVersion"] == "zoop-graph-handoff-bundle-6", "the retained bundle is not schema 6")
    # The selection facts the receipt retains, hand-written from the authored world: the supply issue's operator-chosen representative (document a) states every
    # headline value, while a2 states the same value in every field but its title; the factory issue's only mention is unanimous. Which mentions state the issue's
    # value is a selection fact, never a verification (`verification` stays `none`).
    check(receipt_issues["issue:supply-2026q3"]["fieldProvenance"] == expected_field_provenance(
        world, "operator-representative", (("a", "m-a"), ("a2", "m-a2")), title=(("a", "m-a"),)),
          f"supply field provenance: {receipt_issues['issue:supply-2026q3']['fieldProvenance']}")
    check(receipt_issues["issue:factory-2026q4"]["fieldProvenance"] == expected_field_provenance(world, "unanimous", (("b", "m-b"),)),
          f"factory field provenance: {receipt_issues['issue:factory-2026q4']['fieldProvenance']}")
    check(all(sorted(set(i["evidenceIds"])) == sorted({e for m in i["mentions"] for e in m["evidenceIds"]} | set(i["geography"]["evidenceIds"])
                                                      | {e for v in i["fieldVerdicts"] for e in v["evidenceIds"]})
              for i in receipt["bundle"]["issues"]), "an issue's evidence is not the union of its mentions', its geography's and its verdicts'")
    check(all(i["fieldVerdicts"] == [] and i["fieldProvenance"]["withheld"] == [] for i in receipt["bundle"]["issues"]),
          "the unreviewed world carries a verdict or a withheld field (no verdict means every value is shown, and nothing was verified)")
    snapshot_text = snapshot_file.read_text("utf-8")
    check(not any(word in snapshot_text for word in ('"participants"', '"sourceCompanyId"', '"fieldProvenance"', '"sameValueMentions"', '"fieldVerdicts"', '"withheld"',
                                                     "issuer", "counterparty", "observer", "미등록 법인")),
          "a mention value, a field provenance or a verdict reached the format 3 snapshot (they belong to the receipt only)")
    check(db.scalar("SELECT count(*) FROM artifacts WHERE kind IN ('graph_snapshot', 'verification_receipt')") == 2 + 2,
          "unexpected extra graph artifacts (two fixture snapshots and this import's two are expected)")
    step("snapshot (format 3: period, assertion status, mention references, structured basis, no mention values) and receipt files registered with the registry's hash and size; "
         "the receipt retains the original manifest and bundle, including each issue's original mentions")

    # nothing public ----------------------------------------------------------------------------------------------------
    with smoke.web({"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(layout.artifacts)}) as web:
        code, body = web.get(f"/api/v1/graph?graphVersion={vid}")
        check(code == 409 and "VERSION_UNAVAILABLE" in body, f"the staged version is publicly readable: {code} {body[:300]}")
        # Reads that do not name the staged version are exactly what they were: the artifact source serves the registered fixture
        # versions through the existing fixture reader, and the default and asOf selection still follow the activation history.
        code, body = web.get("/api/v1/graph")
        graph = json.loads(body) if code == 200 else {}
        check(code == 200 and graph["metadata"]["graphVersion"] == active_before and graph["nodes"] and vid not in body and hid not in body,
              f"the default read is not the unchanged active fixture version: {code} {body[:300]}")
        code, body = web.get("/api/v1/graph?asOf=2026-10-05T00:00:00Z")
        check(code == 200 and json.loads(body)["metadata"]["graphVersion"] == "fixture-2026-10-01" and vid not in body,
              f"the asOf read is not the unchanged historical fixture version: {code} {body[:300]}")
        # The merged read contract on the existing fixture (no activation): a structural basis with a known start and an unknown end is a
        # CURRENT basis (active, a null end is not an ended one) and its stored dates are served as they are.
        structural_edges = [e for e in graph["edges"] if e["relationType"] == "STRUCTURALLY_RELATED_TO"]
        check(structural_edges, "the active fixture version serves no structural edge")
        code, body = web.get("/api/v1/graph/edges/" + structural_edges[0]["id"])
        detail = json.loads(body) if code == 200 else {}
        check(code == 200 and detail["validity"] == "active" and detail["basis"] and all(
            b["validity"] == "active" and b["validFrom"] == "2026-09-01" and b["validUntil"] is None for b in detail["basis"]),
            f"the current structural basis is not served as active with its stored dates: {code} {body[:300]}")
    check(db.scalar("SELECT id FROM graph_versions WHERE active") == active_before, "starting the web application moved the pointer")
    step("web (artifact source): graphVersion=<staged> is 409 VERSION_UNAVAILABLE; the default and asOf reads still serve the unchanged fixture versions, and a current fixture basis reads as active")

    # the fixture seeder keeps refusing a database that holds imported versions, and refusing changes nothing -------------
    refused_status, refused_output = smoke.fixture_source_start()
    check(refused_status != 0 and "refuses a database that already has imported graph versions" in refused_output,
          f"the fixture source did not refuse a database with an imported version (exit {refused_status})")
    check(db.scalar("SELECT id FROM graph_versions WHERE active") == active_before
          and db.scalar("SELECT coalesce(md5(string_agg(a::text, '|' ORDER BY a.id)), '') FROM graph_activations a") == history_before,
          "the refused fixture start changed the pointer or its history")
    step("starting the fixture source after an import is refused (existing guard) and leaves the pointer and history untouched")

    # an identical import is a no-op ------------------------------------------------------------------------------------
    after_first = smoke.table_fingerprint()
    inode, mtime = snapshot_file.stat().st_ino, snapshot_file.stat().st_mtime_ns
    status, result, output = smoke.graph_import("again", smoke.request(hid, manifest_digest, bundle_digest))
    check(status == 0 and result["outcome"] == "unchanged" and result["evidenceRows"] == {"registered": 0, "existing": 6}, f"rerun: {result}")
    check(smoke.table_fingerprint() == after_first, "an identical import changed the database")
    check((snapshot_file.stat().st_ino, snapshot_file.stat().st_mtime_ns) == (inode, mtime), "an identical import rewrote the snapshot file")
    step("an identical import is a no-op: unchanged outcome, identical rows and files")

    # wrong pins --------------------------------------------------------------------------------------------------------
    for label, request in (("pin-manifest", smoke.request(hid, "0" * 64, bundle_digest)), ("pin-bundle", smoke.request(hid, manifest_digest, "0" * 64))):
        status, result, output = smoke.graph_import(label, request)
        check(status != 0 and result["status"] == "failed" and result["failure"]["code"] == "pin_mismatch", f"{label}: {result}")
    status, result, output = smoke.graph_import("not-a-request", b'{"schemaVersion": "zoop-graph-handoff-import-1"}')
    check(status != 0 and result["failure"]["code"] == "request_invalid", f"request: {result}")
    check(smoke.table_fingerprint() == after_first, "a refused request changed the database")
    step("wrong pins and an invalid request are refused (pin_mismatch / request_invalid) with nothing written")

    # a second handoff: rights are decided by the CURRENT registry -----------------------------------------------------------
    hid2 = HANDOFFS[1]
    vid2 = version_id(hid2)
    manifest2, bundle2 = pins[hid2]
    before_rights = smoke.table_fingerprint()
    smoke.set_registry(lambda grant: grant.update({"allowedOperations": [op for op in grant["allowedOperations"] if op != "store"]}))
    first_ref = base.item(next(iter(world.refs.values())))["observation"]
    # The CLI distinction the importer relies on: without the store right a plain export still works, --require-store refuses.
    check(smoke.ingest_export(first_ref, require_store=False) == 0 and smoke.ingest_export(first_ref, require_store=True) == 2,
          "zoop-ai-ingest export does not distinguish the store right")
    status, result, output = smoke.graph_import("no-store-right", smoke.request(hid2, manifest2, bundle2))
    failure = result["failure"]
    # The handoff CLI does not check `store` (it needs read + quote-display), so the per-observation export is what refuses.
    check(status != 0 and failure["code"] == "ingestion_export_failed" and re_code(failure.get("ingestionCode")) and failure["observation"] == 0,
          f"a missing store right was not refused by the per-observation export: {result}")
    check(smoke.table_fingerprint() == before_rights and not (layout.artifacts / "graph_snapshot" / f"{vid2}.json").exists(),
          "a refused right left rows or files behind")
    smoke.set_registry(lambda grant: grant.update({"allowedOperations": ["read", "store", "quote-display"], "enabled": False}))
    status, result, output = smoke.graph_import("grant-disabled", smoke.request(hid2, manifest2, bundle2))
    check(status != 0 and result["failure"]["code"] == "handoff_withheld" and re_code(result["failure"].get("handoffCode")), f"withheld: {result}")
    check(smoke.table_fingerprint() == before_rights, "a withheld handoff left rows behind")
    smoke.set_registry(lambda grant: grant.update({"enabled": True}))
    status, result, output = smoke.graph_import("rights-restored", smoke.request(hid2, manifest2, bundle2))
    check(status == 0 and result["outcome"] == "staged" and result["graphVersionId"] == vid2, f"restored: {result}")
    check(db.scalar("SELECT count(*) FROM graph_versions WHERE active") == 1 and db.scalar("SELECT id FROM graph_versions WHERE active") == active_before
          and db.scalar("SELECT count(*) FROM graph_versions WHERE kind = 'snapshot' AND NOT active") == 2
          and db.scalar("SELECT count(*) FROM graph_activations") == 2, "the second import moved the pointer or activated a version")
    check(db.scalar("SELECT count(*) FROM evidence") == 6 and db.scalar(f"SELECT count(*) FROM evidence WHERE verification_artifact_id = 'artifact-receipt-{vid}'") == 6,
          "the second handoff re-registered or re-pointed shared evidence")
    step("rights: a missing store right (per-observation export), a revoked grant (withheld handoff) and their restoration; the second handoff stages and shares the evidence rows")

    # a LEGAL producer collision: documents a and a2 of ONE issue both use the local mention id m-a ----------------------------------------
    world2, collision = hs.collision_export(scratch / "collision", PUBLIC_IDS)
    layout2 = Layout(world2, args.ingest_cli)
    layout2.artifacts = layout.artifacts      # one database and one artifact root: this world's documents and files live beside the first world's
    smoke2 = Smoke(args, db, layout2)
    status, result, _ = smoke2.jar.run("documents-collision", [base.item(ref) for ref in world2.refs.values()], artifact_root=layout.artifacts)
    check(status == 0 and result and result["status"] == "succeeded", f"the collision world's document import failed: {result}")
    ledgers2_before = {name: fingerprint(path) for name, path in layout2.ledgers.items()}
    hid3, vid3 = "handoff-collision-1", version_id("handoff-collision-1")
    manifest3, bundle3 = hs.digest(collision["manifest"]), sha256(hs.canonical(collision["bundle"]).encode("utf-8"))
    status, result, output = smoke2.graph_import("collision", smoke2.request(hid3, manifest3, bundle3))
    check(status == 0 and result and result["status"] == "succeeded" and result["outcome"] == "staged" and result["graphVersionId"] == vid3
          and result["counts"] == {"companies": 2, "issues": 2, "relations": 4, "articles": 3, "evidence": 6},
          f"the collision handoff was not staged: {result} {output[-800:]}")
    snapshot_file3 = layout.artifacts / "graph_snapshot" / f"{vid3}.json"
    snapshot_bytes3 = snapshot_file3.read_bytes()
    snapshot3 = json.loads(snapshot_bytes3.decode("utf-8"))
    pinned2 = {name: {"articleId": ref["documentId"], "articleVersion": ref["documentVersion"]} for name, ref in world2.refs.items()}
    supply3 = next(i for i in snapshot3["issues"] if i["issueId"] == "issue:supply-2026q3")
    ids3 = [mention["mentionId"] for mention in supply3["mentions"]]
    check(supply3["mentions"] == sorted(({"mentionId": mention_id(pinned2[name], "m-a"), **pinned2[name]} for name in ("a", "a2")),
                                        key=lambda mention: mention["mentionId"])
          and len(set(ids3)) == 2 and "m-a" not in ids3 and supply3["representativeMentionId"] == mention_id(pinned2["a"], "m-a"),
          f"collision mentions: {supply3['mentions']} representative {supply3['representativeMentionId']}")
    check(len(snapshot3["issues"]) == 2 and len(snapshot3["relations"]) == 4 and len(snapshot3["articles"]) == 3 and len(snapshot3["evidence"]) == 6,
          "the collision snapshot dropped content")
    receipt3 = json.loads((layout.artifacts / "verification_receipt" / f"{vid3}.json").read_text("utf-8"))
    check(receipt3["bundle"] == collision["bundle"], "the collision receipt does not retain the producer's own mention ids")
    supply_mentions = next(i for i in receipt3["bundle"]["issues"] if i["id"] == "issue:supply-2026q3")["mentions"]
    check(supply_mentions == expected_mentions(world2, ("a", "m-a", hs.EVT_A, "합성 공급 계약", "공급 계약 발표", "2026-09-30", "2026Q3", DOC_A),
                                               ("a2", "m-a", hs.EVT_A2, "합성 공급 계약", "공급 계약 발표", "2026-09-30", "2026Q3", [MAPPED]))
          and len(supply_mentions) == 2 and {m["mentionId"] for m in supply_mentions} == {"m-a"}
          and len({m["documentId"] for m in supply_mentions}) == 2, f"the collision receipt does not keep two original mentions with one local id: {supply_mentions}")
    # Both documents state every value (a2's title equals a's here), yet the operator still chose a: the selection stays `operator-representative` and both
    # identities are in every list, in mention order.
    supply_provenance = next(i for i in receipt3["bundle"]["issues"] if i["id"] == "issue:supply-2026q3")["fieldProvenance"]
    check(supply_provenance == expected_field_provenance(world2, "operator-representative", (("a", "m-a"), ("a2", "m-a"))),
          f"the collision receipt's field provenance is not both identities in every list: {supply_provenance}")
    status, again, _ = smoke2.graph_import("collision-again", smoke2.request(hid3, manifest3, bundle3))
    check(status == 0 and again and again["outcome"] == "unchanged" and snapshot_file3.read_bytes() == snapshot_bytes3,
          f"retrying the collision import changed ids or bytes: {again}")
    check({name: fingerprint(path) for name, path in layout2.ledgers.items()} == ledgers2_before, "the collision world's ledgers changed")
    step("a legal producer collision (documents a and a2 both use local mention id m-a): staged with two distinct app mention ids, the right representative and "
         "the producer's own ids retained in the receipt; a retry is a no-op with identical bytes")

    # a producer-authored VERDICT world: operator per-field verdicts withhold eventTime/period from the public projection -----------------------
    # SYNTHETIC test review (`hs.verdict_cases`), never a real operator review. The expectations below are written out by hand from that authored world;
    # nothing is read back from the importer under test.
    world4, verdict_env = hs.verdict_export(scratch / "verdicts", PUBLIC_IDS)
    layout4 = Layout(world4, args.ingest_cli)
    layout4.artifacts = layout.artifacts
    smoke4 = Smoke(args, db, layout4)
    status, result, _ = smoke4.jar.run("documents-verdicts", [base.item(ref) for ref in world4.refs.values()], artifact_root=layout.artifacts)
    check(status == 0 and result and result["status"] == "succeeded", f"the verdict world's document import failed: {result}")
    ledgers4_before = {name: fingerprint(path) for name, path in layout4.ledgers.items()}
    hid4, vid4 = hs.VERDICT_HANDOFF, version_id(hs.VERDICT_HANDOFF)
    manifest4, bundle4 = hs.digest(verdict_env["manifest"]), sha256(hs.canonical(verdict_env["bundle"]).encode("utf-8"))
    status, result, output = smoke4.graph_import("verdicts", smoke4.request(hid4, manifest4, bundle4))
    check(status == 0 and result and result["status"] == "succeeded" and result["outcome"] == "staged" and result["graphVersionId"] == vid4
          and result["counts"] == {"companies": 2, "issues": 2, "relations": 4, "articles": 3, "evidence": 9}
          and result["evidenceRows"] == {"registered": 3, "existing": 6}, f"the verdict handoff was not staged with three new evidence rows: {result} {output[-800:]}")
    supply_id, factory_id = "issue:supply-2026q3", "issue:factory-2026q4"
    ev4 = lambda name, quote: hs.evidence_id(world4, name, quote)   # noqa: E731
    verdict_spans = [("a", hs.PERIOD_A), ("a2", hs.PERIOD_A2), ("b", hs.PERIOD_B)]
    rows4 = {r["id"]: r for r in db.rows("""SELECT id, article_id, article_version, quote, start_offset, end_offset, offset_unit, input_kind, quote_verified,
        verification_artifact_id FROM evidence""")}
    check(set(rows4) == set(rows) | {ev4(name, quote) for name, quote in verdict_spans}, "the verdict import did not add exactly the three verdict spans' evidence rows")
    for name, quote in verdict_spans:
        span = hs.span(world4, name, quote)
        stored = rows4[ev4(name, quote)]
        check(stored["quote"] == quote and stored["start_offset"] == span["start"] and stored["end_offset"] == span["end"]
              and stored["article_id"] == span["documentId"] and stored["article_version"] == span["documentVersion"]
              and stored["offset_unit"] == "unicode_code_point" and stored["input_kind"] == "body" and stored["quote_verified"] is True
              and stored["verification_artifact_id"] == f"artifact-receipt-{vid4}", f"the verdict evidence row of {name} is not the exact span: {stored}")
    snapshot_file4 = layout.artifacts / "graph_snapshot" / f"{vid4}.json"
    receipt_file4 = layout.artifacts / "verification_receipt" / f"{vid4}.json"
    snapshot_bytes4 = snapshot_file4.read_bytes()
    snapshot4 = json.loads(snapshot_bytes4.decode("utf-8"))
    issues4 = {i["issueId"]: i for i in snapshot4["issues"]}
    check(snapshot4["snapshotFormat"] == 3 and set(issues4) == {supply_id, factory_id} and len(snapshot4["relations"]) == 4
          and any(r["relationType"] == "STRUCTURALLY_RELATED_TO" for r in snapshot4["relations"]), "the verdict snapshot is not format 3 with the re-attested structural edge")
    # The reviewed headline: the supply representative's event time is REJECTed (null, unknown precision) while its period is ALLOWed; the factory's only mention has its
    # period HELD (null) and keeps its event time. The non-representative second document's HOLD/REJECT withhold nothing.
    check((issues4[supply_id]["eventTime"], issues4[supply_id]["timePrecision"], issues4[supply_id]["period"]) == (None, "unknown", "2026Q3")
          and (issues4[factory_id]["eventTime"], issues4[factory_id]["timePrecision"], issues4[factory_id]["period"]) == ("2026-11-15", "day", None),
          f"the snapshot headline values are not the withheld ones: {[(i['eventTime'], i['timePrecision'], i['period']) for i in snapshot4['issues']]}")
    check(issues4[supply_id]["evidenceIds"] == sorted({ev4("a", hs.EVT_A), ev4("a2", hs.EVT_A2), ev4("a", hs.GEO_A), ev4("a", hs.PERIOD_A), ev4("a2", hs.PERIOD_A2)})
          and issues4[factory_id]["evidenceIds"] == sorted({ev4("b", hs.QB), ev4("b", hs.GEO_B), ev4("b", hs.PERIOD_B)}),
          "an issue's evidence is not the union of its mentions', its geography's and its verdicts' spans")
    snapshot_text4 = snapshot_bytes4.decode("utf-8")
    check("2026-09-30" not in snapshot_text4 and "2026Q4" not in snapshot_text4 and "2026Q3" in snapshot_text4
          and not any(word in snapshot_text4 for word in ('"fieldVerdicts"', '"withheld"', '"fieldProvenance"', "operator-field-verdict", "contradicted", "ambiguous", "unstated",
                                                         hs.REVIEWER)),
          "a rejected or held value, or a verdict, reached the public snapshot")
    receipt4 = json.loads(receipt_file4.read_text("utf-8"))
    check(receipt4["bundle"] == verdict_env["bundle"] and receipt4["manifest"] == verdict_env["manifest"], "the verdict receipt does not retain the original")
    check(receipt4["bundle"]["schemaVersion"] == "zoop-graph-handoff-bundle-6" and receipt4["bundle"]["handoffId"] == hid4, "the verdict receipt is not bundle -6")
    receipt_issues4 = {i["id"]: i for i in receipt4["bundle"]["issues"]}
    # The ORIGINAL mentions are untouched by every verdict: the withheld supply time and the held factory period are still stated by their mentions.
    check(receipt_issues4[supply_id]["mentions"] == expected_mentions(
        world4, ("a", "m-a", hs.EVT_A, "합성 공급 계약", "공급 계약 발표", "2026-09-30", "2026Q3", DOC_A),
        ("a2", "m-a2", hs.EVT_A2, "합성 공급 계약 체결 공개", "공급 계약 발표", "2026-09-30", "2026Q3", [MAPPED]))
          and receipt_issues4[factory_id]["mentions"] == expected_mentions(
              world4, ("b", "m-b", hs.QB, "합성 공장 착공", "공장 착공 알림", "2026-11-15", "2026Q4", DOC_B)),
          "a verdict changed an original mention in the receipt")
    check(receipt_issues4[supply_id]["fieldProvenance"] == expected_field_provenance(
        world4, "operator-representative", (("a", "m-a"), ("a2", "m-a2")), withheld=("eventTime",), title=(("a", "m-a"),))
          and receipt_issues4[factory_id]["fieldProvenance"] == expected_field_provenance(world4, "unanimous", (("b", "m-b"),), withheld=("period",)),
          "the verdict receipt's field provenance is not the original selected values plus the withheld list")

    def verdict_rows(issue: dict) -> list:
        return sorted((v["mentionId"], v["field"], v["value"], v["decision"], v["reasonCode"], v["evidenceIds"], v["verification"], v["reviewer"]) for v in issue["fieldVerdicts"])
    review = lambda *row: (*row, "operator-field-verdict", hs.REVIEWER)   # noqa: E731
    check(verdict_rows(receipt_issues4[supply_id]) == sorted([
        review("m-a", "eventTime", "2026-09-30", "REJECT", "contradicted", [ev4("a", hs.EVT_A)]),
        review("m-a", "period", "2026Q3", "ALLOW", "stated", [ev4("a", hs.PERIOD_A)]),
        review("m-a2", "eventTime", "2026-09-30", "HOLD", "unstated", []),
        review("m-a2", "period", "2026Q3", "REJECT", "contradicted", [ev4("a2", hs.PERIOD_A2)])])
          and verdict_rows(receipt_issues4[factory_id]) == [review("m-b", "period", "2026Q4", "HOLD", "ambiguous", [ev4("b", hs.PERIOD_B)])],
          f"the receipt does not keep the operator's verdicts exactly: {receipt_issues4[supply_id]['fieldVerdicts']} {receipt_issues4[factory_id]['fieldVerdicts']}")
    check({issue_id: issue["fieldVerdicts"] for issue_id, issue in receipt_issues4.items()} == hs.expected_verdicts(world4, hs.verdict_cases(world4)),
          "the receipt's verdicts differ from the producer's hand-written expectation")
    status, again, _ = smoke4.graph_import("verdicts-again", smoke4.request(hid4, manifest4, bundle4))
    check(status == 0 and again and again["outcome"] == "unchanged" and snapshot_file4.read_bytes() == snapshot_bytes4,
          f"retrying the verdict import changed the staged bytes: {again}")
    check({name: fingerprint(path) for name, path in layout4.ledgers.items()} == ledgers4_before, "the verdict world's ledgers changed")
    step("a producer-authored verdict world (SYNTHETIC review): staged with the supply representative's REJECTed time and the factory's HELD period null in the snapshot "
         "(time precision unknown), the ALLOWed supply period and a non-representative HOLD/REJECT unchanged, the verdict spans registered and part of each issue's evidence, "
         "and the receipt retaining every original mention value, each verdict and the withheld lists; a retry is a no-op with identical bytes")

    harness = {"harnessActivations": 0, "evidenceReads": 0}
    verdict_read = {"harnessActivations": 0, "evidenceReads": 0, "graphReads": 0}
    approved_read = {"harnessActivations": 0, "evidenceReads": 0}
    path_read = {"harnessActivations": 0, "evidenceReads": 0, "graphReads": 0}
    approved = approved_world_phase(args, db, layout, scratch)
    if args.with_evidence_read:
        harness = evidence_read_phase(smoke, db, layout, world, vid2, (vid, vid3, vid4, approved["vid"]), active_before)
        verdict_read = verdict_read_phase(smoke4, db, layout, layout4, world4, vid4, vid2, ev4)
        approved_read = approved_read_phase(approved, db, layout, vid4)
    # The path world is built LAST: its S3 relations became eligible after every earlier activation, which the back-dated path activation relies on.
    paths = path_world_phase(args, db, layout, scratch)
    if args.with_evidence_read:
        path_read = path_read_phase(paths, db, layout, approved["vid"])
    # The impact world is built after everything else: its harness activation is a plain current-time one after the back-dated path activation.
    impact_read = {"harnessActivations": 0, "evidenceReads": 0, "graphReads": 0}
    impact = impact_world_phase(args, db, layout, scratch)
    if args.with_evidence_read:
        impact_read = impact_read_phase(impact, db, layout, paths["vids"]["private"])

    # ledgers, logs --------------------------------------------------------------------------------------------------------
    check({name: fingerprint(path) for name, path in layout.ledgers.items()} == ledgers_before,
          "a source or handoff ledger changed (they are opened read-only)")
    joined = "\n".join(base.OUTPUT)
    password = os.environ["DB_PASSWORD"]
    check(str(world.root) not in joined and str(layout.work) not in joined and (len(password) < 8 or password not in joined),
          "a path or secret reached a process output")
    for text in hs.PRIVATE:
        check(text not in joined, "source or review text reached a process output")
    step("every ledger is byte/mode/mtime identical; no path, secret or source text in any output")

    print(json.dumps({"status": "passed", "steps": len(base.STEPS), "providerCalls": 0, "modelCalls": 0, "handoffs": 6 + len(PATH_MIDDLES),
                      "evidenceRows": db.scalar("SELECT count(*) FROM evidence"), "stagedVersions": 6 + len(PATH_MIDDLES), "importActivationsWritten": 0,
                      "harnessActivations": harness["harnessActivations"] + verdict_read["harnessActivations"] + approved_read["harnessActivations"]
                      + path_read["harnessActivations"] + impact_read["harnessActivations"],
                      "evidenceReads": harness["evidenceReads"] + verdict_read["evidenceReads"] + approved_read["evidenceReads"] + path_read["evidenceReads"]
                      + impact_read["evidenceReads"],
                      "verdictGraphReads": verdict_read["graphReads"], "approvedRelations": len(approved["approvals"]),
                      "pathGraphReads": path_read["graphReads"], "pathVariants": list(PATH_MIDDLES),
                      "impactRows": len(impact["rows"]), "impactGraphReads": impact_read["graphReads"], "historicalActivations": impact_read.get("historicalActivations", 0),
                      "importRuns": smoke.runs + smoke2.runs + smoke4.runs + approved["smoke"].runs + paths["smoke"].runs + impact["smoke"].runs,
                      "ledgerReadOnly": True}))
    return 0


def re_code(value) -> bool:
    return isinstance(value, str) and value.replace("_", "").isalnum() and value == value.lower()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as failure:
        print("graph handoff import smoke FAILED: " + str(failure).replace(os.environ.get("DB_PASSWORD") or "\0", "***"), file=sys.stderr)
        for output in base.OUTPUT[-1:]:
            print("--- last process output (tail) ---\n" + output[-2500:].replace(os.environ.get("DB_PASSWORD") or "\0", "***"), file=sys.stderr)
        sys.exit(1)
