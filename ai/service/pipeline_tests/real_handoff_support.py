"""Harness for the handoff door over the REAL installed `zoop-ai-handoff` and an actual two-job synthetic world (no stand-in command, no Neo4j: the handoff does
not read the private graph). The operator side is the pipeline's interpreter building the world and freezing two handoffs (`build_handoff_world.py`); the service
side is a real uvicorn process whose only door to the pipeline is the installed `ai/pipeline/.venv/bin/zoop-ai-handoff export`.

The ledgers (ingestion, extraction, S3, handoff) are shared and read-only; everything a test mutates (source registry and the three operator files) is a private
copy in the workspace, so a test can revoke a grant or change an operator file and then restore the exact original bytes.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from relation_support import PIPELINE, PIPELINE_BIN, PIPELINE_PYTHON, tree
from support import canonical
from handoff_support import HandoffWorkspace  # noqa: E402  (tests/ is on sys.path through relation_support)

HANDOFF_CLI = PIPELINE_BIN / "zoop-ai-handoff"
BUILD_HANDOFF_WORLD = Path(__file__).resolve().parent / "build_handoff_world.py"
BUILD_VERDICT_HANDOFF_WORLD = Path(__file__).resolve().parent / "build_verdict_handoff_world.py"
VERDICT_HANDOFF = "handoff-verdicts-1"
EXPORTS_SCHEMA = "zoop-ai-handoff-exports-1"
RUNTIME_SCHEMA = "zoop-ai-handoff-1"
VALIDATE = ("import json, sys\nfrom zoop_ai_pipeline.handoff_contracts import validate_bundle\n"
            "validate_bundle(json.load(sys.stdin)['bundle'])\nprint('valid')\n")


def require_handoff_pipeline() -> None:
    """The pipeline targets fail, they never skip: a green run must mean the real pipeline ran."""
    for path in (PIPELINE_PYTHON, HANDOFF_CLI):
        assert path.is_file() and os.access(path, os.X_OK), f"{path} is missing: run `make pipeline-install` before service-pipeline-test"


@dataclass
class HandoffWorld:
    root: Path
    relation: Path
    extraction: Path
    ingestion: Path
    sources: Path
    canonical: Path
    decisions: Path
    bindings: Path
    state: Path                       # the handoff ledger the operator froze two handoffs into
    handoffs: dict[str, dict[str, Any]]
    counts: dict[str, Any]
    evidence_ids: list[str]
    issue_ids: list[str]
    relation_edges: list[list[Any]]
    exclusions: dict[str, int]
    private: list[str]
    article_ids: list[str]
    expect: dict[str, Any] = field(default_factory=dict)   # the verdict world's hand-written expectations (the pipeline smoke's own), never derived from the service

    def ledgers(self) -> dict[str, dict]:
        return {name: tree(getattr(self, name)) for name in ("relation", "extraction", "ingestion", "state")}


def build_handoff_world(root: Path, script: Path = BUILD_HANDOFF_WORLD) -> HandoffWorld:
    require_handoff_pipeline()
    root.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([str(PIPELINE_PYTHON), str(script), str(PIPELINE), str(root)], capture_output=True, text=True, timeout=900,
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"})
    assert done.returncode == 0, done.stderr[-4000:] + done.stdout[-2000:]
    info = json.loads(done.stdout.strip().splitlines()[-1])
    return HandoffWorld(Path(info["root"]), Path(info["relation"]), Path(info["extraction"]), Path(info["ingestion"]), Path(info["sources"]), Path(info["canonical"]),
                        Path(info["decisions"]), Path(info["bindings"]), Path(info["handoffState"]), info["handoffs"], info["counts"], info["evidenceIds"],
                        info["issueIds"], info["relationEdges"], info["exclusions"], info["private"], info["articleIds"], info.get("expect", {}))


def pin_entry(world: HandoffWorld, principal: str, handoff_id: str, **overrides: Any) -> dict[str, Any]:
    pins = world.handoffs[handoff_id]
    return {"principal": principal, "handoffId": handoff_id, "manifestDigest": pins["manifestDigest"], "bundleDigest": pins["bundleDigest"], **overrides}


class RealWorkspace(HandoffWorkspace):
    """One service's fresh state over the shared read-only ledgers, private copies of the mutable operator inputs and the real installed command."""

    def __init__(self, root: Path, world: HandoffWorld, exports: list[dict[str, Any]]):
        super().__init__(root, command=HANDOFF_CLI, exports=exports)
        self.world = world
        self.handoff_state, self.relation_state, self.extraction_state, self.ingestion_state = world.state, world.relation, world.extraction, world.ingestion
        for name in ("sources", "canonical", "decisions", "bindings"):
            shutil.copyfile(getattr(world, name), getattr(self, name))
        self.originals = {name: getattr(self, name).read_bytes() for name in ("sources", "canonical", "decisions", "bindings")}

    def restore(self, name: str) -> None:
        getattr(self, name).write_bytes(self.originals[name])

    def direct(self, handoff_id: str, command: Path = HANDOFF_CLI) -> tuple[int, dict[str, Any], bytes]:
        """The oracle: the installed command run directly, the way the service runs it, over the same ledgers and the same private operator inputs."""
        argv = [str(command), "export", "--state-dir", str(self.handoff_state), "--relation-state-dir", str(self.relation_state), "--extraction-state-dir",
                str(self.extraction_state), "--ingestion-state-dir", str(self.ingestion_state), "--sources", str(self.sources), "--canonical", str(self.canonical),
                "--decisions", str(self.decisions), "--bindings", str(self.bindings)]
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "ZOOP_STATE_DIR": str(self.app_state), "ZOOP_AI_WORKER_STATE_DIR": str(self.worker)}
        done = subprocess.run(argv, input=json.dumps({"schemaVersion": RUNTIME_SCHEMA, "handoffId": handoff_id}).encode(), capture_output=True, env=env, timeout=300)
        assert not done.stderr, done.stderr[-500:]
        return done.returncode, json.loads(done.stdout), done.stdout

    def private_strings(self) -> list[str]:
        return [*super().private_strings(), *self.world.private, str(self.world.root), str(HANDOFF_CLI)]


def producer_accepts(response_bytes: bytes) -> bool:
    """The producer's own validator (`validate_bundle`, run in the pipeline interpreter) judges the bundle the HTTP response delivered."""
    done = subprocess.run([str(PIPELINE_PYTHON), "-c", VALIDATE], input=response_bytes, capture_output=True, timeout=120,
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1", "ZOOP_STATE_DIR": "/nonexistent", "ZOOP_AI_WORKER_STATE_DIR": "/nonexistent"})
    return done.returncode == 0 and done.stdout.strip() == b"valid"


VALIDATE_MANIFEST = ("import json, sys\nfrom zoop_ai_pipeline.handoff_contracts import Manifest, canonical, digest\n"
                     "doc = json.load(sys.stdin)\nmanifest = Manifest.model_validate(doc['manifest'])\n"
                     "assert canonical(manifest.wire()) == canonical(doc['manifest']) and digest(doc['manifest']) == doc['bundle']['manifestDigest']\n"
                     "print('valid')\n")


def producer_accepts_manifest(response_bytes: bytes) -> bool:
    """The producer's own closed `Manifest` model judges the manifest of the HTTP response: exact canonical form and digest equal to the bundle's `manifestDigest`."""
    done = subprocess.run([str(PIPELINE_PYTHON), "-c", VALIDATE_MANIFEST], input=response_bytes, capture_output=True, timeout=120,
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1", "ZOOP_STATE_DIR": "/nonexistent", "ZOOP_AI_WORKER_STATE_DIR": "/nonexistent"})
    return done.returncode == 0 and done.stdout.strip() == b"valid"


def digest_of(bundle: Any) -> str:
    return hashlib.sha256(canonical(bundle).encode("utf-8")).hexdigest()


def verdict_problems(bundle: dict[str, Any], world: HandoffWorld) -> list[str]:
    """What is wrong with the verdicts a DELIVERED bundle carries, against the hand-written expectation of the pipeline's reviewed world (`world.expect`, never derived from
    the service or from the bundle). Empty list = right. It is NOT vacuous: the expectation must itself hold verdicts, and every issue's delivered verdicts, headline
    `(eventTime, timePrecision, period)`, withheld list and ORIGINAL mentions must equal it, with each withheld headline field actually null while some original mention
    still states a value for it."""
    expect, problems = world.expect, []
    issues = {i["id"]: i for i in bundle["issues"]}
    if sum(len(v) for v in expect["verdicts"].values()) < 5 or not expect["withheld"] or set(issues) != set(expect["headlines"]):
        return ["the hand-written expectation holds no reviewed verdicts or does not cover the bundle's issues"]
    for issue_id, issue in issues.items():
        withheld = expect["withheld"].get(issue_id, [])
        if issue["fieldVerdicts"] != expect["verdicts"][issue_id]:
            problems.append(f"{issue_id}: delivered verdicts differ from the reviewed ones")
        if [issue["eventTime"], issue["timePrecision"], issue["period"]] != expect["headlines"][issue_id]:
            problems.append(f"{issue_id}: public headline values differ from the expected ones")
        if issue["fieldProvenance"]["withheld"] != withheld:
            problems.append(f"{issue_id}: withheld list is {issue['fieldProvenance']['withheld']}, expected {withheld}")
        if issue["mentions"] != expect["mentions"][issue_id]:
            problems.append(f"{issue_id}: an original mention value was changed")
        for name in withheld:
            if issue[name] is not None or not any(m[name] is not None for m in issue["mentions"]) or not any(v["field"] == name for v in issue["fieldVerdicts"]):
                problems.append(f"{issue_id}: withheld {name} is not null, or no original mention / verdict backs it")
        if "eventTime" in withheld and issue["timePrecision"] != "unknown":
            problems.append(f"{issue_id}: a withheld event time kept its precision")
        if any(v["verification"] != "operator-field-verdict" or "evidence" in v or "note" in v for v in issue["fieldVerdicts"]):
            problems.append(f"{issue_id}: a verdict is not the closed operator shape")
    dumped = json.dumps(bundle, ensure_ascii=False)
    problems += [f"private text leaked: {text[:12]}" for text in world.private if text in dumped]
    return problems
