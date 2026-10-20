"""AI -> backend public graph HANDOFF: freeze/recover/inspect/export over a REAL ingestion + two S2 + two S3 job world read through the owners' own seams.

Expectations are written by hand from the authored world (see scripts/graph_handoff_smoke.py), never echoed from the code under test. No Neo4j (the handoff
does not read the private graph), no network, no model. Mutating scenarios use a private copy of the source ledgers (`Rig`), the module-scoped world is
never changed.
"""
from __future__ import annotations

import contextlib
import copy
import fcntl
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from pydantic import ValidationError

from scripts import graph_handoff_smoke as hs
from scripts.ingestion_smoke import json_bytes
from scripts.relation_smoke import find, tree
from zoop_ai_pipeline import handoff_cli as cli
from zoop_ai_pipeline.handoff import Handoff, HandoffPaths, Planner, Store, article_metadata
from zoop_ai_pipeline.handoff_contracts import (POLICY, SCHEMA, Bindings, Decisions, ExtractionFailure, Manifest, Selector, app_evidence_id, content_digest,
    countries_class, time_precision, validate_bundle)

HASH = "a" * 64
HOSTILE = ("x'}) DETACH DELETE n //", "a b", "é", "line\nbreak", "a\0b", "v" * 201, "")


# ---------------------------------------------------------------- fixtures -----------------------------------------------------------

@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    return hs.build_world(tmp_path_factory.mktemp("zoop-handoff") / "owned")


def world_fixture(name: str, **variant):
    @pytest.fixture(scope="module")
    def fixture(tmp_path_factory):
        return hs.build_world(tmp_path_factory.mktemp(f"zoop-handoff-{name}") / "owned", **variant)
    return fixture


# Real ingestion + S2 + S3 worlds for the integrity regressions (each built once per module, never mutated by a test).
collision_same = world_fixture("collide-same", collide=True, a2_differs=False)                          # same local mentionId in two documents, equal metadata
collision_title = world_fixture("collide-title", collide=True, a2_differs=True)                         # ... with a differing title
collision_us = world_fixture("collide-us", collide=True, a2_differs=False, a2_countries=("US",))       # ... with a differing country field
dated_world = world_fixture("dated", dated=True)                                                        # structural basis whose validity is proven only in document b
# The supply issue's event time is 2026-09-30 in both of its documents. Each variant is a REAL ingestion + S2 + S3 world whose validity sentence (document b) states
# the LAST VALID DAY ("through D"), so the S3 value `validUntil` is exactly what the source says and is inclusive (FS042: `validFrom <= time <= validUntil`).
until_before_event_day = world_fixture("until-before-event-day", dated=True, valid_until="2026-09-29")   # [2026-01-01, 2026-09-29]: the event day is after the last valid day
until_on_event_day = world_fixture("until-on-event-day", dated=True, valid_until="2026-09-30")           # [2026-01-01, 2026-09-30]: the event day is the last valid day, inside
until_after_event_day = world_fixture("until-after-event-day", dated=True, valid_until="2026-10-01")     # [2026-01-01, 2026-10-01]: the event day is inside
from_on_event_day = world_fixture("from-on-event-day", dated=True, valid_from="2026-09-30", valid_until=None)      # [2026-09-30, unknown end): start is inclusive
from_after_event_day = world_fixture("from-after-event-day", dated=True, valid_from="2026-10-01", valid_until=None)
event_time_unknown = world_fixture("event-time-unknown", dated=True, event_time=None)                    # a dated basis cannot be compared with a missing event time
event_time_month = world_fixture("event-time-month", dated=True, event_time="2026-09")                  # nor with a month-precision one (no midnight/first-of-month guess)
event_time_unknown_undated = world_fixture("event-time-unknown-undated", dated=True, event_time=None, valid_from=None, valid_until=None)
# Original mentions: one mention identity with different values in its two upstreams, and a member whose own event time is unusable (no offset) or merely coarser.
upstreams_disagree = world_fixture("upstreams-disagree", snapshot_differs=True)
a2_time_offsetless = world_fixture("a2-time-offsetless", a2_event_time="2026-09-30T10:00:00")
a2_time_month = world_fixture("a2-time-month", a2_event_time="2026-09")
a2_time_iso_week = world_fixture("a2-time-iso-week", a2_event_time="2026-W40-3")        # `date.fromisoformat` would call this a day; the app refuses it
event_time_iso_week = world_fixture("event-time-iso-week", event_time="2026-W40-3")       # EVERY member of the supply issue, the issue's own time included, carries it
event_time_no_seconds = world_fixture("event-time-no-seconds", event_time="2026-09-30T09:00Z")   # valid in the app's grammar: seconds are optional, `Z` is an offset


@pytest.fixture(scope="module")
def observation_world(tmp_path_factory):
    return hs.build_observation_world(tmp_path_factory.mktemp("zoop-handoff-observation") / "owned")

@pytest.fixture(scope="module")
def matching_observation_world(tmp_path_factory):
    return hs.build_observation_world(tmp_path_factory.mktemp("zoop-handoff-matching-observation") / "owned", same_url=True)


class Rig:
    """A private copy of the source ledgers and grants plus the three operator files and a fresh handoff state directory."""

    def __init__(self, shared, tmp_path: Path, docs: dict | None = None):
        self.world, self.root = shared, tmp_path / "rig"
        self.root.mkdir()
        for name in ("ingestion", "extraction", "relation"):
            shutil.copytree(shared.root / name, self.root / name)
        self.sources = self.root / "sources.json"
        shutil.copy(shared.kit.registry_path, self.sources)
        self.state = self.root / "handoff"
        self.docs = docs or {"canonical": hs.canonical_doc(shared), "decisions": hs.decisions_doc(shared), "bindings": hs.bindings_doc(shared)}
        self.write()

    def write(self) -> None:
        for name, doc in self.docs.items():
            (self.root / f"{name}.json").write_bytes(json_bytes(doc))

    def hashes(self) -> dict:
        return hs.file_hashes(self.root)

    def manifest(self, handoff_id: str = "h1", **override) -> dict:
        return {**hs.manifest_doc(self.world, handoff_id, self.hashes()), **override}

    def run(self, command: str, request, *, expected: int = 0, state: Path | None = None, raw: bytes | None = None):
        argv = ["zoop-ai-handoff", command, "--state-dir", str(state or self.state)]
        if command in cli.SOURCED:
            argv += ["--relation-state-dir", str(self.root / "relation"), "--extraction-state-dir", str(self.root / "extraction"),
                     "--ingestion-state-dir", str(self.root / "ingestion"), "--sources", str(self.sources), "--canonical", str(self.root / "canonical.json"),
                     "--decisions", str(self.root / "decisions.json"), "--bindings", str(self.root / "bindings.json")]
        out = io.StringIO()
        data = raw if raw is not None else json_bytes(request)
        with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(data))), contextlib.redirect_stdout(out):
            code = cli.main()
        text = out.getvalue()
        assert code == expected, text[:2000]
        assert text.endswith("\n") and text.count("\n") == 1, text[:500]
        return json.loads(text)

    def sel(self, handoff_id: str = "h1") -> dict:
        return {"schemaVersion": SCHEMA, "handoffId": handoff_id}

    def freeze(self, handoff_id: str = "h1", *, expected: int = 0, **override):
        return self.run("freeze", self.manifest(handoff_id, **override), expected=expected)

    def bundle(self, handoff_id: str = "h1") -> dict:
        """Freeze (must succeed) and export (must be current): the full bundle under the current operator files."""
        self.freeze(handoff_id)
        out = self.run("export", self.sel(handoff_id))
        assert out["delivery"]["status"] == "current", out["delivery"]
        return out["bundle"]

    def rows(self) -> int:
        if not (self.state / "handoff.sqlite3").exists():
            return 0
        db = sqlite3.connect(self.state / "handoff.sqlite3")
        try:
            return db.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0]
        finally:
            db.close()

    def sql(self, statement: str, args=()):
        db = sqlite3.connect(self.state / "handoff.sqlite3")
        try:
            return db.execute(statement, args).fetchall()
        finally:
            db.commit()
            db.close()

    def review(self, job: str, rc: str, decision: str = "reject") -> None:
        """Append a review event straight into the COPIED relation ledger (what `relation review` does for a HOLD), to change a source revision."""
        db = sqlite3.connect(self.root / "relation" / "relation.sqlite3")
        try:
            seq = db.execute("SELECT COUNT(*) FROM relation_events WHERE job_id=? AND relation_candidate_id=?", (job, rc)).fetchone()[0] + 1
            db.execute("INSERT INTO relation_events VALUES(?,?,?,?,?,?)", (job, rc, seq, "review", json.dumps(
                {"decision": decision, "reviewer": hs.PRIVATE_REVIEWER, "note": hs.PRIVATE_NOTE, "expectedRevision": seq - 1, "effect": "excluded"}), "2026-10-16T00:00:00+00:00"))
            db.commit()
        finally:
            db.close()

    def grant(self, **change) -> None:
        document = json.loads(self.sources.read_text())
        document["sources"][0]["grant"].update(change)
        self.sources.write_bytes(json_bytes(document))


@pytest.fixture
def rig(shared, tmp_path):
    return Rig(shared, tmp_path)


def error(out: dict, code: str, detail: dict | None = None) -> None:
    assert out == {"schemaVersion": SCHEMA, "error": {"code": code, **({"detail": detail} if detail else {})}}, out


def excluded(bundle: dict) -> dict:
    return {(i["kind"], i["id"]): i["code"] for i in bundle["exclusions"]["items"]}


def issue_ids(bundle: dict) -> list:
    return [i["id"] for i in bundle["issues"]]


# ---------------------------------------------------------------- the full positive handoff -------------------------------------------

def test_full_handoff_over_two_jobs_equals_the_hand_written_expectation_and_leaks_no_source_text(rig):
    frozen = rig.freeze()
    assert frozen["state"] == "ready" and frozen["next"] == "export" and frozen["publication"] == "not-published" and "bundle" not in frozen
    assert frozen["usage"] == {"providerCalls": 0, "modelCalls": 0} and [a["kind"] for a in frozen["attempts"]] == ["freeze"]
    receipt = frozen["receipt"]
    assert receipt["counts"] == hs.expected(rig.world)["counts"] and receipt["manifestDigest"] == hs.digest(rig.manifest())
    assert receipt["sources"] == [{"relation": s["relation"], "upstream": s["upstream"], "reviewDigest": s["reviewDigest"]} for s in rig.manifest()["sources"]]
    assert receipt["checks"]["appImportPending"] and "graphDb" not in json.dumps(receipt) and receipt["exclusionCodes"] == hs.expected(rig.world)["exclusions"]
    out = rig.run("export", rig.sel())
    hs.check_export(rig.world, out)
    text = json.dumps(out, ensure_ascii=False)
    for private in hs.PRIVATE:
        assert private not in text
    assert hs.canonical(out["bundle"]).encode() == (rig.state / "bundles" / f"{receipt['bundleDigest']}.json").read_bytes()
    assert out["bundle"]["digests"]["content"] == receipt["contentDigest"] and out["delivery"]["reviewDigestMatches"] is True
    # The manifest of the ORIGINAL frozen request, exactly: its canonical digest is the receipt's and the bundle's manifestDigest; no path, no secret.
    assert out["manifest"] == rig.manifest() and hs.digest(out["manifest"]) == receipt["manifestDigest"] == out["bundle"]["manifestDigest"]
    assert str(rig.root) not in text and "bindings.json" not in text
    assert "manifest" not in frozen and "manifest" not in rig.run("inspect", rig.sel())


def test_two_s3_jobs_merge_one_canonical_issue_with_all_source_events_and_cross_document_evidence(rig):
    bundle = rig.bundle()
    supply = next(i for i in bundle["issues"] if i["id"] == "issue:supply-2026q3")
    assert supply["sourceEvents"] == hs.source_events(rig.world) and {s["upstream"]["jobId"] for s in supply["sourceEvents"]} == {"s2-a", "s2-b"}
    assert supply["representative"]["mentionId"] == "m-a"
    articles = {e["articleId"] for e in bundle["evidence"] if e["id"] in supply["evidenceIds"]}
    assert articles == {rig.world.refs["a"]["documentId"], rig.world.refs["a2"]["documentId"]}
    involves = next(r for r in bundle["relations"] if r["type"] == "INVOLVES" and r["source"] == "issue:supply-2026q3")
    assert sorted(x["jobId"] for x in involves["sourceRefs"]) == ["rel-a", "rel-b"] and involves["source"] != involves["target"]
    assert {s["relation"]["jobId"] for s in bundle["sources"]} == {"rel-a", "rel-b"}


def test_supported_public_relations_each_have_a_source_backed_positive_and_nothing_else_is_exposed(rig):
    bundle = rig.bundle()
    assert sorted({r["type"] for r in bundle["relations"]}) == ["FOLLOWS", "INVOLVES", "STRUCTURALLY_RELATED_TO"]
    follows = next(r for r in bundle["relations"] if r["type"] == "FOLLOWS")
    assert (follows["source"], follows["target"]) == ("issue:factory-2026q4", "issue:supply-2026q3") and follows["provenance"]["s2Relation"] == "FOLLOWS"
    involves = [r for r in bundle["relations"] if r["type"] == "INVOLVES"]
    assert {(r["source"], r["target"]) for r in involves} == {("issue:supply-2026q3", "KRX:005930"), ("issue:factory-2026q4", "KRX:005930")}
    assert all(r["role"] is None and r["assertionStatus"] == "announced" and r["provenance"]["origin"] == "s3-relation" for r in involves)
    # Company-company S3 types are counted as eligible-but-not-public, never exposed as an edge; topics/events/SHARES_ISSUE never appear.
    first = next(s for s in bundle["sources"] if s["relation"]["jobId"] == "rel-a")
    assert first["audit"]["eligibleNotPublicByType"] == {"INVESTS_IN": 1, "SUPPLIES": 1} and first["audit"]["eligibility"] == {"eligible": 3, "hold": 1, "reject": 0, "pending": 0}
    assert not {r["type"] for r in bundle["relations"]} & {"SHARES_ISSUE", "SUPPLIES", "INVESTS_IN", "PARTICIPATES_IN", "RELATES_TO_TOPIC"}


def test_freeze_is_idempotent_and_a_changed_input_conflicts_without_writing(rig):
    first = rig.freeze()
    assert rig.freeze() == first and rig.rows() == 1
    error(rig.freeze(expected=2, sourceKind="actual"), "handoff_input_conflict")
    other = rig.manifest()
    other["sources"] = other["sources"][:1]
    error(rig.run("freeze", other, expected=2), "handoff_input_conflict")
    assert rig.rows() == 1 and rig.freeze() == first


# ---------------------------------------------------------------- pins: wrong source / version / file / provenance ---------------------

@pytest.mark.parametrize("name,change,code", [
    ("upstream digest", lambda m: m["sources"][0]["upstream"].update(digest="b" * 64), "upstream_changed"),
    ("relation input digest", lambda m: m["sources"][0]["relation"].update(inputDigest="b" * 64), "relation_input_mismatch"),
    ("review digest", lambda m: m["sources"][0].update(reviewDigest="b" * 64), "review_revision_changed"),
    ("unknown S3 job", lambda m: m["sources"][0]["relation"].update(jobId="rel-missing"), "job_not_found"),
    ("canonical file pin", lambda m: m["files"].update(canonical="b" * 64), "operator_file_pin_mismatch"),
    ("decisions file pin", lambda m: m["files"].update(decisions="b" * 64), "operator_file_pin_mismatch"),
    ("bindings file pin", lambda m: m["files"].update(bindings="b" * 64), "operator_file_pin_mismatch"),
    ("declared actual over synthetic source", lambda m: m.update(sourceKind="actual"), "provenance_conflict"),
])
def test_wrong_pins_are_refused_with_nothing_written(rig, name, change, code):
    manifest = rig.manifest()
    change(manifest)
    out = rig.run("freeze", manifest, expected=2)
    assert out["error"]["code"] == code, (name, out)
    assert rig.rows() == 0 and not list((rig.state / "bundles").iterdir())


def test_a_review_change_after_the_pin_refuses_a_new_freeze_but_not_an_unrelated_export(rig):
    pinned = rig.manifest()
    frozen = rig.freeze()
    hold = find(rig.world.jobs["rel-a"], "SHARES_ISSUE")
    rig.review("rel-a", hold["relationCandidateId"])
    # An excluded (HOLD) relation changed: the stored handoff does not depend on it, so export stays current and says the whole review state moved.
    out = rig.run("export", rig.sel())
    assert out["delivery"]["status"] == "current" and out["delivery"]["reviewDigestMatches"] is False
    assert out["bundle"]["digests"]["content"] == frozen["receipt"]["contentDigest"]
    assert out["manifest"] == pinned and hs.digest(out["manifest"]) == frozen["receipt"]["manifestDigest"]   # the frozen request, not today's review state
    # The real S3 reviewer name and note exist only in the relation ledger and must reach no export output, receipt or exclusion item.
    exported = json.dumps(out, ensure_ascii=False)
    assert hs.PRIVATE_REVIEWER not in exported and hs.PRIVATE_NOTE not in exported and all(p not in exported for p in hs.PRIVATE)
    assert "operator-asserted" in exported            # the legitimate public attestation status is still exported
    # A NEW handoff pinned to the old review state refuses (the operator pinned a state that no longer exists).
    error(rig.run("freeze", {**pinned, "handoffId": "h2"}, expected=2), "review_revision_changed")
    assert rig.rows() == 1


# ---------------------------------------------------------------- canonical issue identity / metadata conflict -------------------------

def test_merged_events_with_different_metadata_conflict_unless_the_operator_names_one_representative(rig):
    rig.docs["decisions"]["issues"][0]["representative"] = None
    rig.write()
    bundle = rig.bundle()
    assert "issue:supply-2026q3" not in issue_ids(bundle)
    found = [i for i in bundle["exclusions"]["items"] if i["id"] == "issue:supply"]
    assert found == [{"kind": "issue", "id": "issue:supply", "jobId": None, "code": "issue_metadata_conflict", "detail": {"fields": ["title"]}}]
    codes = excluded(bundle)
    assert codes[("structural", "issue:supply>co:synth-3")] == "issue_not_public" and codes[("follows", "issue:factory>issue:supply")] == "issue_not_public"
    assert issue_ids(bundle) == ["issue:factory-2026q4"]


def test_a_representative_that_is_not_a_member_is_refused_and_unreviewed_or_unsourced_issues_are_visible(rig):
    rig.docs["decisions"]["issues"][0]["representative"]["mentionId"] = "m-unknown"
    rig.docs["decisions"]["issues"] = [i for i in rig.docs["decisions"]["issues"] if i["canonicalId"] != "issue:overseas"]
    rig.docs["decisions"]["issues"].append({**rig.docs["decisions"]["issues"][1], "canonicalId": "issue:nothing", "publicId": "issue:nothing-pub"})
    rig.write()
    codes = excluded(rig.bundle())
    assert codes[("issue", "issue:supply")] == "issue_representative_invalid"
    assert codes[("issue", "issue:overseas")] == "issue_unreviewed"
    assert codes[("issue", "issue:nothing")] == "issue_source_missing"


def test_canonical_registry_entries_for_another_s2_input_never_apply(rig):
    for entry in rig.docs["canonical"]["entries"]:
        if entry["kind"] == "event" and entry["canonicalId"] == "issue:factory":
            entry["upstream"]["inputDigest"] = "c" * 64          # a decision for a DIFFERENT S2 input than the pinned upstream
    rig.write()
    bundle = rig.bundle()
    assert "issue:factory-2026q4" not in issue_ids(bundle) and excluded(bundle)[("issue", "issue:factory")] == "issue_source_missing"
    assert excluded(bundle)[("follows", "issue:factory>issue:supply")] == "canonical_event_unmapped"


# ---------------------------------------------------------------- geography ---------------------------------------------------------

def test_countries_class_is_a_pure_closed_function():
    assert [countries_class(c) for c in ([], ["KR"], ["US"], ["KR", "US"], ["kr"], ["KOR"], [""], ["KR", "KR"])] == [
        "unknown", "domestic", "international", "international", "invalid", "invalid", "invalid", "domestic"]


@pytest.mark.parametrize("name,change,code", [
    ("class contradicts verdict countries", lambda g, w: g.update(classification="international"), "geography_decision_mismatch"),
    ("verdict disagrees with the S2 country field", lambda g, w: g.update(classification="international", countries=["KR", "US"]), "geography_countries_disagree"),
    ("malformed country code", lambda g, w: g.update(countries=["kr"]), "geography_countries_invalid"),
    ("quote hash is not the pinned text", lambda g, w: g["evidence"][0].update(quoteSha256="d" * 64), "geography_evidence_mismatch"),
    ("span outside the text", lambda g, w: g["evidence"][0].update(start=10_000, end=10_010), "geography_evidence_mismatch"),
    ("span in a document that is not one of the issue's own", lambda g, w: g.update(evidence=[hs.span(w, "b", hs.QB)]), "geography_evidence_unbound"),
])
def test_geography_is_excluded_unless_the_field_verdict_matches_every_source_mention(rig, shared, name, change, code):
    change(rig.docs["decisions"]["issues"][0]["geography"], shared)
    rig.write()
    bundle = rig.bundle()
    assert excluded(bundle)[("issue", "issue:supply")] == code, (name, excluded(bundle))
    assert "issue:supply-2026q3" not in issue_ids(bundle)



def test_a_missing_country_field_excludes_the_issue_and_never_defaults_to_international(rig):
    bundle = rig.bundle()
    assert excluded(bundle)[("issue", "issue:overseas")] == "geography_unproven" and "issue:overseas-2026q4" not in issue_ids(bundle)
    assert {i["geography"]["value"] for i in bundle["issues"]} == {"domestic", "international"}
    assert all(i["geography"]["verification"] == "operator-field-verdict" and i["geography"]["policyVersion"] == POLICY and i["geography"]["evidenceIds"]
               for i in bundle["issues"])
    assert next(i for i in bundle["issues"] if i["id"] == "issue:factory-2026q4")["geography"]["countries"] == ["US"]


# ---------------------------------------------------------------- app bindings / evidence ------------------------------------------

def test_app_evidence_id_separates_documents_versions_and_the_other_namespaces():
    base = app_evidence_id("doc-" + HASH, HASH, 3, 9)
    assert base.startswith("ev-") and len(base) == 67
    assert app_evidence_id("doc-" + "b" * 64, HASH, 3, 9) != base          # same version/span in ANOTHER document
    assert app_evidence_id("doc-" + HASH, "b" * 64, 3, 9) != base          # same document/span in another version
    assert app_evidence_id("doc-" + HASH, HASH, 3, 10) != base and app_evidence_id("doc-" + HASH, HASH, 4, 9) != base
    s2 = "ev-" + hs.digest([HASH, 3, 9])[:32]                              # S2 id: excludes documentId, 32 hex
    s1 = "ev-" + hs.digest({"analysisId": "doc-" + HASH, "evidenceId": s2})  # S1 app id preimage
    assert base not in (s2, s1) and len(s2) == 35
    assert base == "ev-" + hashlib.sha256(json.dumps({"kind": "graph-body-span", "articleId": "doc-" + HASH, "articleVersion": HASH, "start": 3, "end": 9},
                                                    sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_every_evidence_binds_to_an_explicit_app_article_and_carries_only_coordinates_and_hashes(rig):
    bundle = rig.bundle()
    bound = {(b["documentId"], b["documentVersion"]): b for b in rig.docs["bindings"]["bindings"]}
    for e in bundle["evidence"]:
        binding = bound[(e["source"]["documentId"], e["source"]["documentVersion"])]
        assert (e["articleId"], e["articleVersion"]) == (binding["articleId"], binding["articleVersion"])
        assert e["id"] == app_evidence_id(e["articleId"], e["articleVersion"], e["start"], e["end"]) and e["offsetUnit"] == "unicode_code_point"
        assert e["source"]["sourceEvidenceId"].startswith("ev-") and len(e["source"]["sourceEvidenceId"]) == 35 and e["id"] != e["source"]["sourceEvidenceId"]
        assert e["rawLocatorIds"] and e["quoteSha256"] and "quote" not in e and "text" not in e
    sup = next(e for e in bundle["evidence"] if e["quoteSha256"] == hs.digest_text(hs.SUP))
    assert sup["end"] - sup["start"] == len(hs.SUP)                          # code points, with the emoji counted once
    assert [a["publicationPrecision"] for a in bundle["articles"] if a["articleId"] == rig.world.refs["b"]["documentId"]] == ["unknown"]
    assert next(a for a in bundle["articles"] if a["articleId"] == rig.world.refs["a"]["documentId"])["publicationPrecision"] == "datetime"
    assert all(a["observations"] and a["observations"][0]["grant"]["grantId"] for a in bundle["articles"])


def test_a_binding_whose_text_digest_is_not_the_source_text_never_reads_as_verified(rig):
    ref = rig.world.refs["a"]
    next(b for b in rig.docs["bindings"]["bindings"] if b["documentId"] == ref["documentId"])["textSha256"] = "e" * 64
    rig.write()
    bundle = rig.bundle()
    codes = excluded(bundle)
    assert codes[("issue", "issue:supply")] == "app_binding_text_mismatch" and issue_ids(bundle) == ["issue:factory-2026q4"]
    assert ref["documentId"] not in {a["articleId"] for a in bundle["articles"]}


def test_a_missing_binding_excludes_every_item_that_needs_it_without_guessing_an_article(rig):
    ref = rig.world.refs["b"]
    rig.docs["bindings"]["bindings"] = [b for b in rig.docs["bindings"]["bindings"] if b["documentId"] != ref["documentId"]]
    rig.write()
    bundle = rig.bundle()
    codes = excluded(bundle)
    assert codes[("issue", "issue:factory")] == "app_binding_missing" and "issue:factory-2026q4" not in issue_ids(bundle)
    assert ref["documentId"] not in {a["articleId"] for a in bundle["articles"]} and not any(r["type"] == "FOLLOWS" for r in bundle["relations"])


# ---------------------------------------------------------------- INVOLVES endpoints ------------------------------------------------

def test_an_endpoint_without_a_public_company_mapping_is_excluded_and_never_dangles(rig):
    bundle = rig.bundle()
    codes = excluded(bundle)
    unmapped = find(rig.world.jobs["rel-b"], "PARTICIPATES_IN", "SYNTH-2")["relationCandidateId"]
    assert codes[("relation", unmapped)] == "company_unmapped"
    company_ids = {c["id"] for c in bundle["companies"]}
    assert all(r["target"] in (company_ids if r["type"] != "FOLLOWS" else set(issue_ids(bundle))) for r in bundle["relations"])
    rig.docs["decisions"]["companies"] = [c for c in rig.docs["decisions"]["companies"] if c["canonicalId"] != "co:synth-1"]
    rig.write()
    bundle = rig.bundle("h2")
    assert bundle["relations"] == [] and bundle["issues"] == [] and bundle["companies"] == [] and bundle["evidence"] == []
    assert {c for c in excluded(bundle).values()} >= {"company_unmapped", "issue_without_involvement"}


def test_involves_uses_the_s3_direction_reversed_and_only_eligible_participation(rig):
    bundle = rig.bundle()
    rc = find(rig.world.jobs["rel-a"], "PARTICIPATES_IN")
    assert (rc["subject"]["kind"], rc["object"]["kind"]) == ("company", "event")          # S3: company -> event
    edge = next(r for r in bundle["relations"] if r["type"] == "INVOLVES" and r["source"] == "issue:supply-2026q3")
    assert (edge["source"], edge["target"]) == ("issue:supply-2026q3", "KRX:005930")       # public: issue -> company
    assert {"kind": "s3-relation", "jobId": "rel-a", "id": rc["relationCandidateId"]} in edge["sourceRefs"]
    assert all(r["eligibility"]["status"] == "eligible" for r in (rc,))


# ---------------------------------------------------------------- STRUCTURALLY_RELATED_TO ------------------------------------------

def structural_code(rig, handoff_id: str = "h1") -> tuple:
    bundle = rig.bundle(handoff_id)
    return excluded(bundle).get(("structural", "issue:supply>" + rig.docs["decisions"]["structural"][0]["company"])), bundle


def test_structural_is_a_labeled_manual_assertion_over_an_eligible_supplies_basis(rig):
    bundle = rig.bundle()
    edge = next(r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO")
    assert (edge["source"], edge["target"]) == ("issue:supply-2026q3", "KRX:000660") and edge["role"] is None
    p = edge["provenance"]
    assert p["origin"] == "manual-operator-review" and p["s3SemanticValidation"] == "none" and p["status"] == "operator-asserted" and p["reviewer"] == hs.REVIEWER
    assert p["bindingDigest"] == hs.structural_binding(rig.world) and p["decisionVersion"] == "v1"
    basis = edge["basis"][0]
    rc = find(rig.world.jobs["rel-a"], "SUPPLIES", "SYNTH-3", "SYNTH-1")
    assert basis["sourceRelation"] == {"jobId": "rel-a", "relationCandidateId": rc["relationCandidateId"]} and basis["relationType"] == "SUPPLIES"
    assert basis["validFrom"] is None and basis["validUntil"] is None and basis["countries"] == []
    history = [h for h in rc["history"] if h["kind"] == "verdict"]
    assert basis["verifiedAt"] == history[-1]["createdAt"] and len(basis["sourceArticles"]) == 1


@pytest.mark.parametrize("name,change,code", [
    ("wrong binding digest", lambda s: s["applicability"].update(bindingDigest="f" * 64), "applicability_binding_mismatch"),
    ("decision version moved without re-attestation", lambda s: s["applicability"].update(decisionVersion="v2"), "applicability_binding_mismatch"),
    ("target is already a participant", lambda s: s.update(company="co:synth-1"), "structural_target_is_participant"),
    ("target not reachable from a participant over the basis", lambda s: s.update(company="co:synth-4"), "basis_path_disconnected"),
    ("target without a public company mapping", lambda s: s.update(company="co:synth-2"), "company_unmapped"),
    ("unknown basis relation", lambda s: s["basis"][0].update(relationCandidateId="rc-" + "0" * 64), "basis_relation_missing"),
    ("unpinned basis job", lambda s: s["basis"][0].update(jobId="rel-other"), "basis_relation_missing"),
])
def test_structural_without_provable_source_basis_is_excluded_visibly(rig, name, change, code):
    rig.docs["decisions"]["companies"].append({"canonicalId": "co:synth-4", "publicId": "KRX:000999", "label": "합성투자", "decisionRef": "catalog-2026-10-16:4"})
    change(rig.docs["decisions"]["structural"][0])
    rig.write()
    found, bundle = structural_code(rig)
    assert found == code, (name, excluded(bundle))
    assert not any(r["type"] == "STRUCTURALLY_RELATED_TO" for r in bundle["relations"])


def test_structural_attestation_detail_names_the_digest_the_operator_must_review(rig):
    rig.docs["decisions"]["structural"][0]["applicability"]["decisionVersion"] = "v2"
    rig.write()
    bundle = rig.bundle()
    item = next(i for i in bundle["exclusions"]["items"] if i["kind"] == "structural")
    assert item["detail"] == {"expectedBindingDigest": hs.structural_binding(rig.world, decision_version="v2")}


def test_only_direct_eligible_supplies_can_be_a_structural_basis(rig):
    invest = find(rig.world.jobs["rel-a"], "INVESTS_IN")
    rig.docs["decisions"]["structural"][0]["basis"] = [{"jobId": "rel-a", "relationCandidateId": invest["relationCandidateId"]}]
    rig.write()
    found, _ = structural_code(rig)
    assert found == "basis_type_unsupported"
    hold = find(rig.world.jobs["rel-a"], "SHARES_ISSUE")
    rig.docs["decisions"]["structural"][0]["basis"] = [{"jobId": "rel-a", "relationCandidateId": hold["relationCandidateId"]}]
    rig.write()
    found, _ = structural_code(rig, "h2")
    assert found == "basis_relation_ineligible"


# ---------------------------------------------------------------- FOLLOWS -----------------------------------------------------------

@pytest.mark.parametrize("name,change,code", [
    ("group changed", lambda f: f["source"].update(groupDigest="9" * 64), "follows_group_changed"),
    ("reversed direction", lambda f: f.update({"from": "issue:supply", "to": "issue:factory"}), "follows_canonical_mismatch"),
    ("unknown comparison", lambda f: f["source"].update(targetEventId="event-none"), "follows_source_missing"),
    ("unpinned S2 upstream", lambda f: f["source"]["upstream"].update(jobId="s2-other"), "follows_source_unpinned"),
])
def test_follows_requires_the_exact_s2_comparison_and_the_operator_sequence_decision(rig, name, change, code):
    change(rig.docs["decisions"]["follows"][0])
    rig.write()
    bundle = rig.bundle()
    assert [v for (kind, _), v in excluded(bundle).items() if kind == "follows"] == [code], name
    assert not any(r["type"] == "FOLLOWS" for r in bundle["relations"])


def test_a_different_s2_comparison_is_not_a_sequence_even_with_an_operator_decision(rig):
    candidate = next(c for c in rig.world.s2["b"]["eventCandidates"] if c["eventCandidateId"] == rig.world.evc["b3"])
    comparison = candidate["comparisons"][0]
    assert comparison["effective"]["relation"] == "DIFFERENT"
    rig.docs["decisions"]["follows"] = [{"from": "issue:overseas", "to": "issue:supply", "decisionRef": "seq-2026-10-16:3", "decisionVersion": "s1",
                                         "source": {"upstream": hs.upstream(rig.world, "b"), "eventCandidateId": rig.world.evc["b3"], "targetEventId": "event-a",
                                                    "groupDigest": comparison["groupDigest"]}}]
    rig.write()
    bundle = rig.bundle()
    assert excluded(bundle)[("follows", "issue:overseas>issue:supply")] == "follows_source_not_follows" and not any(r["type"] == "FOLLOWS" for r in bundle["relations"])


# ---------------------------------------------------------------- current authority after freeze -------------------------------------

@pytest.mark.parametrize("name,code", [("canonical", "canonical_mapping_changed"), ("decisions", "decisions_changed"), ("bindings", "bindings_changed")])
def test_a_changed_operator_file_withholds_a_stored_ready_handoff(rig, name, code):
    rig.freeze()
    path = rig.root / f"{name}.json"
    path.write_bytes(path.read_bytes() + b" ")
    out = rig.run("export", rig.sel(), expected=2)
    assert set(out) == {"schemaVersion", "handoffId", "state", "publication", "delivery", "usage"} and out["delivery"] == {"status": "withheld", "code": code}, out
    assert rig.run("inspect", rig.sel())["state"] == "ready"                    # the ledger is untouched; only DELIVERY is withheld


def test_an_operator_file_that_no_longer_parses_withholds_instead_of_erroring_with_content(rig):
    rig.freeze()
    (rig.root / "decisions.json").write_bytes(b"{")
    out = rig.run("export", rig.sel(), expected=2)
    assert out["delivery"] == {"status": "withheld", "code": "decisions_invalid"} and "bundle" not in out


def test_a_revoked_grant_withholds_with_no_bundle_counts_or_ids_and_restoring_it_delivers_again(rig):
    rig.freeze()
    rig.grant(enabled=False)
    out = rig.run("export", rig.sel(), expected=2)
    assert set(out) == {"schemaVersion", "handoffId", "state", "publication", "delivery", "usage"} and out["delivery"]["status"] == "withheld", out
    assert out["delivery"]["code"] == "source_unauthorized"
    text = json.dumps(out, ensure_ascii=False)
    assert "issue:" not in text and "KRX:" not in text and "ev-" not in text
    rig.grant(enabled=True)
    assert rig.run("export", rig.sel())["delivery"]["status"] == "current"


def test_a_changed_grant_revision_withholds_because_the_upstream_pin_covers_it(rig):
    rig.freeze()
    rig.grant(revision="rights-2")
    out = rig.run("export", rig.sel(), expected=2)
    assert out["delivery"]["status"] == "withheld" and out["delivery"]["code"] in {"grant_revision_changed", "upstream_changed"}, out


def test_a_review_change_on_a_relation_behind_an_emitted_edge_withholds(rig):
    rig.freeze()
    basis = find(rig.world.jobs["rel-a"], "SUPPLIES", "SYNTH-3", "SYNTH-1")
    rig.review("rel-a", basis["relationCandidateId"])
    out = rig.run("export", rig.sel(), expected=2)
    assert out["delivery"] == {"status": "withheld", "code": "review_revision_changed"} and "bundle" not in out


def test_a_busy_writer_is_an_error_never_an_empty_or_partial_bundle(rig):
    rig.freeze()
    for lock, code in ((rig.state / "handoff.lock", "handoff_busy"), (rig.root / "relation" / "relation.lock", "relation_busy")):
        fd = os.open(lock, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            out = rig.run("export", rig.sel(), expected=2)
            assert out["error"]["code"] == code and "bundle" not in out and "delivery" not in out, out
        finally:
            os.close(fd)
    assert rig.run("export", rig.sel())["delivery"]["status"] == "current"


# ---------------------------------------------------------------- artifact integrity, recovery, immutability --------------------------

def artifact(rig, frozen: dict) -> Path:
    return rig.state / "bundles" / f"{frozen['receipt']['bundleDigest']}.json"


def test_an_altered_missing_or_foreign_artifact_is_never_served_or_called_ready(rig):
    frozen = rig.freeze()
    path = artifact(rig, frozen)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    original = path.read_bytes()
    for tampered in (original.replace(b'"KRX:000660"', b'"KRX:000661"', 1), original + b" ", original[:-5], b"{}"):
        os.chmod(path, 0o600)
        path.write_bytes(tampered)
        error(rig.run("inspect", rig.sel(), expected=2), "handoff_artifact_invalid")
        error(rig.run("export", rig.sel(), expected=2), "handoff_artifact_invalid")
    path.unlink()
    error(rig.run("inspect", rig.sel(), expected=2), "handoff_artifact_missing")
    error(rig.run("export", rig.sel(), expected=2), "handoff_artifact_missing")
    path.write_bytes(original)
    assert rig.run("inspect", rig.sel())["state"] == "ready"


def test_a_damaged_stored_manifest_is_never_exported_or_reported_ready_and_is_never_rebuilt_from_today(rig):
    frozen = rig.freeze()
    stored = rig.sql("SELECT manifest FROM handoffs")[0][0]
    assert stored == hs.canonical(rig.manifest())
    guards = ("immutable_handoffs_identity", "terminal_handoffs")
    originals = [rig.sql("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,))[0][0] for name in guards]

    def overwrite(text: str) -> None:
        """Throwaway rig only: simulate on-disk corruption past both ledger guards, then put the ORIGINAL trigger SQL back so the ledger schema is intact
        (the CLI's strict ownership preflight must pass and the damage must be found in the stored manifest itself)."""
        for name in guards:
            rig.sql(f"DROP TRIGGER {name}")
        rig.sql("UPDATE handoffs SET manifest=?", (text,))
        for sql in originals:
            rig.sql(sql)
    damaged = json.loads(stored)
    cases = {"non-canonical whitespace": json.dumps(damaged, indent=1), "wrong digest": hs.canonical({**damaged, "sourceKind": "actual"}),
             "wrong source pin": hs.canonical({**damaged, "sources": [{**damaged["sources"][0], "reviewDigest": "f" * 64}, *damaged["sources"][1:]]}),
             "wrong file pin": hs.canonical({**damaged, "files": {**damaged["files"], "bindings": "f" * 64}}),
             "wrong handoff id": hs.canonical({**damaged, "handoffId": "other"}), "unknown field": hs.canonical({**damaged, "operatorPath": "/private/x"}),
             "not json": "{", "empty": ""}
    for name, text in cases.items():
        overwrite(text)
        for command in ("inspect", "export"):
            error(rig.run(command, rig.sel(), expected=2), "handoff_artifact_invalid")
    overwrite(stored)
    assert rig.run("inspect", rig.sel())["state"] == "ready"
    out = rig.run("export", rig.sel())
    assert out["delivery"]["status"] == "current" and hs.digest(out["manifest"]) == frozen["receipt"]["manifestDigest"]


def test_the_manifest_never_leaves_a_withheld_export(rig):
    rig.freeze()
    path = rig.root / "decisions.json"
    path.write_bytes(path.read_bytes() + b" ")
    out = rig.run("export", rig.sel(), expected=2)
    assert "manifest" not in out and "bundle" not in out and out["delivery"] == {"status": "withheld", "code": "decisions_changed"}
    assert all(pin not in json.dumps(out) for pin in (*rig.hashes().values(), "rel-a", "rel-b"))


def test_the_ledger_is_append_only_and_a_ready_handoff_is_terminal(rig):
    rig.freeze()
    for statement in ("UPDATE handoffs SET bundle_digest='x'", "DELETE FROM handoffs", "UPDATE handoffs SET state='failed'", "UPDATE attempts SET outcome='confirmed'",
                      "DELETE FROM attempts", "UPDATE meta SET value='x'"):
        with pytest.raises(sqlite3.DatabaseError):
            rig.sql(statement)
    assert rig.rows() == 1


def test_a_crash_after_reservation_recovers_to_failed_from_the_ledger_only_and_never_regenerates(rig):
    before = {name: tree(rig.root / name) for name in ("ingestion", "extraction", "relation")}
    with mock.patch.object(Handoff, "_after_reserve", side_effect=RuntimeError("process died")):
        error(rig.freeze(expected=2), "handoff_internal_failure")
    assert rig.run("inspect", rig.sel())["state"] == "reserved" and rig.run("inspect", rig.sel())["next"] == "recover"
    error(rig.run("export", rig.sel(), expected=2), "handoff_not_ready", {"state": "reserved"})
    settled = rig.run("recover", rig.sel())          # no source flags at all: recovery cannot read or regenerate anything
    assert settled["state"] == "failed" and settled["failure"] == {"code": "handoff_artifact_missing"} and settled["next"] is None
    assert [(a["kind"], a["outcome"]) for a in settled["attempts"]] == [("recover", "artifact-missing")]
    error(rig.run("recover", rig.sel(), expected=2), "recovery_not_required", {"state": "failed"})
    assert rig.freeze() == settled                                                      # the same ID/input only echoes the terminal failure
    assert rig.freeze("h2")["state"] == "ready"                                         # the operator moves on with a NEW ID
    assert {name: tree(rig.root / name) for name in ("ingestion", "extraction", "relation")} == before


def test_a_crash_after_the_artifact_recovers_to_ready_from_the_stored_bytes(rig):
    with mock.patch.object(Handoff, "_after_artifact", side_effect=RuntimeError("process died")):
        error(rig.freeze(expected=2), "handoff_internal_failure")
    assert len(list((rig.state / "bundles").iterdir())) == 1
    settled = rig.run("recover", rig.sel())
    assert settled["state"] == "ready" and [(a["kind"], a["outcome"]) for a in settled["attempts"]] == [("recover", "confirmed")]
    hs.check_export(rig.world, rig.run("export", rig.sel()))
    error(rig.run("recover", rig.sel(), expected=2), "recovery_not_required", {"state": "ready"})
    assert rig.freeze()["attempts"] == settled["attempts"]                               # the same input echoes; no second artifact or attempt
    assert len(list((rig.state / "bundles").iterdir())) == 1


def test_a_reserved_handoff_with_an_altered_artifact_recovers_to_failed_not_ready(rig):
    with mock.patch.object(Handoff, "_after_artifact", side_effect=RuntimeError("process died")):
        rig.freeze(expected=2)
    path = next((rig.state / "bundles").iterdir())
    os.chmod(path, 0o600)
    path.write_bytes(path.read_bytes().replace(b'"KRX:000660"', b'"KRX:000661"', 1))
    settled = rig.run("recover", rig.sel())
    assert settled["state"] == "failed" and settled["failure"] == {"code": "handoff_artifact_invalid"}


def test_sources_and_operator_files_are_never_written_by_any_command(rig):
    names = ("ingestion", "extraction", "relation")
    before = {name: tree(rig.root / name) for name in names}
    files = {p.name: p.read_bytes() for p in rig.root.glob("*.json")}
    rig.freeze()
    rig.run("inspect", rig.sel())
    rig.run("export", rig.sel())
    assert {name: tree(rig.root / name) for name in names} == before
    assert {p.name: p.read_bytes() for p in rig.root.glob("*.json")} == files


def test_the_handoff_state_may_not_overlap_a_source_ledger_or_hold_foreign_files(rig):
    error(rig.run("freeze", rig.manifest(), expected=2, state=rig.root / "relation" / "inner"), "state_namespace_conflict")
    error(rig.run("freeze", rig.manifest(), expected=2, state=rig.root), "state_namespace_conflict")
    rig.freeze()
    (rig.state / "stray.txt").write_text("x")
    error(rig.run("inspect", rig.sel(), expected=2), "state_namespace_conflict")


def test_read_commands_never_create_state_and_a_missing_ledger_is_an_error(rig):
    error(rig.run("inspect", rig.sel(), expected=2), "handoff_state_missing")
    error(rig.run("recover", rig.sel(), expected=2), "handoff_state_missing")
    assert not rig.state.exists()
    rig.freeze()
    error(rig.run("inspect", rig.sel("unknown"), expected=2), "handoff_not_found")


# ---------------------------------------------------------------- strict bundle validator (what an importer must also refuse) ----------

@pytest.fixture(scope="module")
def valid_bundle(shared, tmp_path_factory):
    return Rig(shared, tmp_path_factory.mktemp("zoop-handoff-valid")).bundle()


def mutated(bundle: dict, change) -> dict:
    copy = json.loads(json.dumps(bundle))
    change(copy)
    return copy


def test_the_valid_bundle_validates_and_every_listed_corruption_is_refused(valid_bundle):
    validate_bundle(valid_bundle)
    cases = {
        "forged evidence id": lambda b: b["evidence"][0].update(id="ev-" + "0" * 64),
        "missing geography": lambda b: b["issues"][0].update(geography=None),
        "dangling endpoint": lambda b: b["relations"][0].update(target="KRX:999999"),
        "unknown top key": lambda b: b.update(extra=1),
        "unknown nested key": lambda b: b["issues"][0].update(extra=1),
        "wrong article version": lambda b: b["evidence"][0].update(articleVersion="f" * 64),
        "shares issue edge": lambda b: b["relations"][0].update(type="SHARES_ISSUE"),
        "orphan evidence": lambda b: b["evidence"].append({**b["evidence"][0], "id": app_evidence_id("doc-" + HASH, HASH, 1, 2), "articleId": "doc-" + HASH,
                                                           "articleVersion": HASH, "start": 1, "end": 2}),
        "evidence reference outside the set": lambda b: b["relations"][0]["evidenceIds"].append("ev-" + "1" * 64),
        "count mismatch": lambda b: b["counts"].update(issues=99),
        "content digest mismatch": lambda b: b["digests"].update(content="0" * 64),
        "exclusion tally mismatch": lambda b: b["exclusions"]["counts"].update(geography_unproven=7),
        "declared differs from observed": lambda b: b["provenance"].update(observedSourceKind="actual"),
        "readiness upgraded": lambda b: b["readiness"].update(publicActivation="active"),
        "app-side check claimed as confirmed": lambda b: b["checks"]["producerConfirmed"].append("app_text_sha256_equals_binding"),
        "structural without manual label": lambda b: next(r for r in b["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO")["provenance"].update(origin="s3"),
        "empty evidence": lambda b: b["relations"][0].update(evidenceIds=[]),
        "float start": lambda b: b["evidence"][0].update(start=1.5),
        "duplicate issue": lambda b: b["issues"].append(json.loads(json.dumps(b["issues"][0]))),
    }
    for name, change in cases.items():
        with pytest.raises(ExtractionFailure) as exc:
            validate_bundle(mutated(valid_bundle, change))
        assert exc.value.code == "handoff_bundle_invalid", name


# ---------------------------------------------------------------- wire contracts ------------------------------------------------------

def test_manifest_is_strict_closed_and_unique_per_job(rig):
    good = rig.manifest()
    Manifest.model_validate(good)
    for bad in ({**good, "extra": 1}, {**good, "schemaVersion": "zoop-ai-handoff-2"}, {**good, "sources": []}, {**good, "policyVersion": "other"},
                {**good, "sourceKind": "real"}, {**good, "sources": [good["sources"][0], good["sources"][0]]}, {**good, "files": {**good["files"], "extra": "a" * 64}},
                {**good, "files": {**good["files"], "canonical": "A" * 64}}):
        with pytest.raises(ValidationError):
            Manifest.model_validate(bad)
    for text in HOSTILE:
        with pytest.raises(ValidationError):
            Manifest.model_validate({**good, "handoffId": text})
    error(rig.run("freeze", None, expected=2, raw=b"{"), "input_or_configuration_invalid")
    error(rig.run("freeze", None, expected=2, raw=b" " * 70_000), "command_input_limit")
    error(rig.run("inspect", {"schemaVersion": SCHEMA, "handoffId": "h1", "extra": 1}, expected=2), "input_or_configuration_invalid")
    assert rig.rows() == 0 and not rig.state.exists()


def test_decisions_and_bindings_refuse_duplicates_overlaps_and_unknown_keys(rig):
    good = rig.docs["decisions"]
    Decisions.model_validate(good)
    company = good["companies"][0]
    for name, bad in {
        "duplicate company canonical": {**good, "companies": [company, {**company, "publicId": "KRX:1"}]},
        "duplicate company public": {**good, "companies": [company, {**company, "canonicalId": "co:other"}]},
        "overlapping namespaces": {**good, "companies": [{**company, "publicId": good["issues"][0]["publicId"]}]},
        "duplicate issue": {**good, "issues": [good["issues"][0], good["issues"][0]]},
        "duplicate structural": {**good, "structural": [good["structural"][0], good["structural"][0]]},
        "three-edge basis": {**good, "structural": [{**good["structural"][0], "basis": good["structural"][0]["basis"] * 3}]},
        "duplicate basis relation": {**good, "structural": [{**good["structural"][0], "basis": good["structural"][0]["basis"] * 2}]},
        "unknown key": {**good, "extra": 1},
        "applicability not manual": {**good, "structural": [{**good["structural"][0], "applicability": {**good["structural"][0]["applicability"], "status": "verified"}}]},
        "empty geography evidence": {**good, "issues": [{**good["issues"][0], "geography": {**good["issues"][0]["geography"], "evidence": []}}]},
        "missing representative key": {**good, "issues": [{k: v for k, v in good["issues"][0].items() if k != "representative"}]},
    }.items():
        with pytest.raises(ValidationError):
            Decisions.model_validate(bad)
        assert name
    binding = rig.docs["bindings"]["bindings"][0]
    for bad in ({**rig.docs["bindings"], "bindings": [binding, binding]}, {**rig.docs["bindings"], "bindings": [binding, {**binding, "documentId": "doc-x"}]},
                {**rig.docs["bindings"], "bindings": [{**binding, "offsetUnit": "utf16"}]}, {**rig.docs["bindings"], "bindings": [{**binding, "articleId": "article-1"}]},
                {**rig.docs["bindings"], "bindings": [{k: v for k, v in binding.items() if k != "textSha256"}]}):
        with pytest.raises(ValidationError):
            Bindings.model_validate(bad)


def test_time_precision_is_by_format_only_and_never_invents_midnight():
    assert [time_precision(v) for v in (None, "2026", "2026-09", "2026-09-30", "2026-09-30T10:00:00+09:00")] == ["unknown", "year", "month", "day", "datetime"]
    for bad in ("2026-13", "2026-09-31", "2026-09-30T10:00:00", "soon", "20260930", "2026/09/30"):
        with pytest.raises(ValueError):
            time_precision(bad)


# ======================================================================================================================================
# Integrity review regressions H1-H6 (written BEFORE the fixes: each one is expected RED against the current producer).
# ======================================================================================================================================

def during_rebuild(mutate):
    """Run `mutate` INSIDE the export command: after the rebuilt plan exists and before the producer decides to deliver."""
    original = Planner.run

    def run(self):
        plan = original(self)
        mutate()
        return plan
    return mock.patch.object(Planner, "run", run)


def assert_withheld_without_content(out: dict) -> None:
    assert out["delivery"]["status"] == "withheld" and isinstance(out["delivery"]["code"], str) and out["delivery"]["code"], out
    assert "bundle" not in out and set(out) == {"schemaVersion", "handoffId", "state", "publication", "delivery", "usage"}, sorted(out)


# ---- H1: authority/operator-file changes INSIDE the producer command ---------------------------------------------------------------

@pytest.mark.parametrize("name", ["canonical", "decisions", "bindings"])
def test_h1_an_operator_file_changed_while_export_rebuilds_withholds_instead_of_delivering_current(rig, name):
    rig.freeze()
    path = rig.root / f"{name}.json"
    with during_rebuild(lambda: path.write_bytes(path.read_bytes() + b" ")):
        out = rig.run("export", rig.sel(), expected=2)
    assert_withheld_without_content(out)


def test_h1_a_grant_withdrawn_while_export_rebuilds_withholds_instead_of_delivering_current(rig):
    rig.freeze()
    with during_rebuild(lambda: rig.grant(enabled=False)):
        out = rig.run("export", rig.sel(), expected=2)
    assert_withheld_without_content(out)


def test_h1_withdrawal_is_noticed_even_when_a_constituent_source_contributes_no_emitted_evidence(rig):
    """rel-b is a constituent whose canonical decisions are all absent, so it emits nothing; the final authority check must still cover it."""
    rig.docs["canonical"]["entries"] = [e for e in rig.docs["canonical"]["entries"] if e["upstream"]["jobId"] != "s2-b"]
    rig.docs["decisions"]["follows"] = []
    rig.write()
    frozen = rig.freeze()
    assert {s["relation"]["jobId"] for s in frozen["receipt"]["sources"]} == {"rel-a", "rel-b"}
    bundle = rig.run("export", rig.sel())["bundle"]
    assert not any(r["jobId"] == "rel-b" for r in (x for r in bundle["relations"] for x in r["sourceRefs"]))        # rel-b really emits nothing
    with during_rebuild(lambda: rig.grant(enabled=False)):
        out = rig.run("export", rig.sel(), expected=2)
    assert_withheld_without_content(out)


# ---- H2: the same local mentionId in two different documents is two source members -----------------------------------------------

def collision_rig(world, tmp_path) -> Rig:
    rig = Rig(world, tmp_path)
    rig.docs["decisions"]["issues"][0]["representative"] = None      # no representative: every member must agree (or conflict)
    rig.docs["decisions"]["structural"] = []                         # the attestation preimage of the base world does not describe this one
    rig.write()
    return rig


def test_h2_two_documents_with_the_same_local_mention_id_are_both_kept_as_source_members(collision_same, tmp_path):
    rig = collision_rig(collision_same, tmp_path)
    bundle = rig.bundle()
    supply = next(i for i in bundle["issues"] if i["id"] == "issue:supply-2026q3")
    assert len(supply["sourceEvents"]) == 3, supply["sourceEvents"]                  # event candidate + BOTH snapshot members (distinct documents)
    assert hs.evidence_id(collision_same, "a2", hs.EVT_A2) in supply["evidenceIds"]  # the second document's evidence was not silently discarded


def test_h2_a_metadata_conflict_with_the_second_same_id_member_is_detected_not_dropped(collision_title, tmp_path):
    bundle = collision_rig(collision_title, tmp_path).bundle()
    found = [i for i in bundle["exclusions"]["items"] if i["id"] == "issue:supply"]
    assert found == [{"kind": "issue", "id": "issue:supply", "jobId": None, "code": "issue_metadata_conflict", "detail": {"fields": ["title"]}}], found
    assert "issue:supply-2026q3" not in issue_ids(bundle)


def test_h2_a_country_disagreement_in_the_second_same_id_member_excludes_the_issue(collision_us, tmp_path):
    bundle = collision_rig(collision_us, tmp_path).bundle()
    assert excluded(bundle)[("issue", "issue:supply")] == "geography_countries_disagree"
    assert "issue:supply-2026q3" not in issue_ids(bundle)


# ---- H3: a structural basis' validity dates need their own evidence, binding and article ------------------------------------------

def test_h3_a_dated_basis_exports_the_validity_evidence_and_its_article(dated_world, tmp_path):
    rig = Rig(dated_world, tmp_path)
    bundle = rig.bundle()
    edge = next(r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO")
    basis = edge["basis"][0]
    assert basis["sourceRelation"]["jobId"] == "rel-b" and (basis["validFrom"], basis["validUntil"]) == ("2026-01-01", "2026-12-31")
    validity = hs.evidence_id(dated_world, "b", hs.VALID2)
    assert validity in basis["evidenceIds"] and hs.evidence_id(dated_world, "a", hs.SUP) in basis["evidenceIds"]
    assert {"articleId": dated_world.refs["b"]["documentId"], "articleVersion": dated_world.refs["b"]["documentVersion"]} in basis["sourceArticles"]
    assert validity in {e["id"] for e in bundle["evidence"]}


@pytest.mark.parametrize("name,change,code", [
    ("validity document has no app binding", lambda b, ref: b.remove(next(x for x in b if x["documentId"] == ref["documentId"])), "app_binding_missing"),
    ("validity document binding has another text digest", lambda b, ref: next(x for x in b if x["documentId"] == ref["documentId"]).update(textSha256="e" * 64),
     "app_binding_text_mismatch"),
])
def test_h3_a_validity_document_without_a_verified_binding_excludes_the_structural_edge(dated_world, tmp_path, name, change, code):
    rig = Rig(dated_world, tmp_path)
    change(rig.docs["bindings"]["bindings"], dated_world.refs["b"])
    rig.write()
    bundle = rig.bundle()
    assert "issue:supply-2026q3" in issue_ids(bundle), name                           # the supply issue itself does not need document b
    assert excluded(bundle).get(("structural", "issue:supply>co:synth-3")) == code, (name, excluded(bundle))
    assert not any(r["type"] == "STRUCTURALLY_RELATED_TO" for r in bundle["relations"])


# ---- FS042: a basis is valid for `validFrom <= eventTime <= validUntil` (the end day is the last valid day); unknown bounds stay unknown ---------------

STRUCTURAL = ("structural", "issue:supply>co:synth-3")


def structural_edges(bundle: dict) -> list:
    return [r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO"]


def test_validity_ending_before_the_event_day_excludes_the_structural_basis(until_before_event_day, tmp_path):
    rig = Rig(until_before_event_day, tmp_path)
    bundle = rig.bundle()
    assert next(i for i in bundle["issues"] if i["id"] == "issue:supply-2026q3")["eventTime"] == "2026-09-30"
    assert not structural_edges(bundle)
    assert excluded(bundle)[STRUCTURAL] == "basis_validity_outside_event_time"
    assert any(r["type"] == "INVOLVES" and r["source"] == "issue:supply-2026q3" for r in bundle["relations"])      # the issue itself is not affected


def test_validity_ending_on_the_event_day_keeps_the_basis_verbatim(until_on_event_day, tmp_path):
    bundle = Rig(until_on_event_day, tmp_path).bundle()
    assert next(i for i in bundle["issues"] if i["id"] == "issue:supply-2026q3")["eventTime"] == "2026-09-30"
    (edge,) = structural_edges(bundle)
    assert (edge["basis"][0]["validFrom"], edge["basis"][0]["validUntil"]) == ("2026-01-01", "2026-09-30")        # the last valid day is the event day: no +1 day, no midnight
    assert STRUCTURAL not in excluded(bundle)


def test_validity_ending_the_day_after_the_event_keeps_the_basis_verbatim(until_after_event_day, tmp_path):
    bundle = Rig(until_after_event_day, tmp_path).bundle()
    (edge,) = structural_edges(bundle)
    assert (edge["basis"][0]["validFrom"], edge["basis"][0]["validUntil"]) == ("2026-01-01", "2026-10-01")
    assert STRUCTURAL not in excluded(bundle)


def test_validity_starting_on_the_event_day_keeps_the_basis_and_an_unknown_end_stays_null(from_on_event_day, tmp_path):
    bundle = Rig(from_on_event_day, tmp_path).bundle()
    (edge,) = structural_edges(bundle)
    assert (edge["basis"][0]["validFrom"], edge["basis"][0]["validUntil"]) == ("2026-09-30", None)
    assert STRUCTURAL not in excluded(bundle)


def test_validity_starting_after_the_event_day_excludes_the_basis(from_after_event_day, tmp_path):
    bundle = Rig(from_after_event_day, tmp_path).bundle()
    assert not structural_edges(bundle)
    assert excluded(bundle)[STRUCTURAL] == "basis_validity_outside_event_time"


@pytest.mark.parametrize("fixture,precision", [("event_time_unknown", "unknown"), ("event_time_month", "month")])
def test_a_dated_basis_is_unprovable_for_an_event_time_without_day_precision(request, tmp_path, fixture, precision):
    world = request.getfixturevalue(fixture)
    bundle = Rig(world, tmp_path).bundle()
    assert next(i for i in bundle["issues"] if i["id"] == "issue:supply-2026q3")["timePrecision"] == precision
    assert not structural_edges(bundle)
    assert excluded(bundle)[STRUCTURAL] == "basis_validity_unprovable"


def test_an_undated_basis_needs_no_event_time_and_keeps_both_bounds_unknown(event_time_unknown_undated, tmp_path):
    bundle = Rig(event_time_unknown_undated, tmp_path).bundle()
    (edge,) = structural_edges(bundle)
    assert (edge["basis"][0]["validFrom"], edge["basis"][0]["validUntil"]) == (None, None)
    assert next(i for i in bundle["issues"] if i["id"] == "issue:supply-2026q3")["eventTime"] is None


def exclusive_end(when: str, validity: dict) -> bool:
    """The producer predicate of the earlier local revision (END EXCLUSIVE: `validUntil` day itself excluded). Used ONLY to freeze a legacy artifact; the bundle is validated as usual."""
    return bool((validity["from"] and when[:10] < validity["from"][:10]) or (validity["until"] and when[:10] >= validity["until"][:10]))


def stored(rig) -> dict:
    """Everything a handoff persists: ledger rows, attempts and artifact bytes."""
    return {"handoffs": rig.sql("SELECT * FROM handoffs ORDER BY handoff_id"), "attempts": rig.sql("SELECT * FROM attempts ORDER BY handoff_id, n"),
            "files": {p.name: p.read_bytes() for p in sorted((rig.state / "bundles").iterdir())}}


def test_a_bundle_frozen_under_the_exclusive_end_is_withheld_never_served_as_end_inclusive_and_is_preserved(until_on_event_day, tmp_path):
    rig = Rig(until_on_event_day, tmp_path)
    with mock.patch("zoop_ai_pipeline.handoff.outside_validity", exclusive_end):
        legacy = rig.bundle()
    assert not structural_edges(legacy) and excluded(legacy)[STRUCTURAL] == "basis_validity_outside_event_time"     # the legacy artifact dropped a basis whose last valid day is its event day
    before = stored(rig)
    assert len(before["files"]) == 1

    out = rig.run("export", rig.sel(), expected=2)
    assert out["delivery"] == {"status": "withheld", "code": "handoff_content_changed"} and out["state"] == "ready"
    assert set(out) == {"schemaVersion", "handoffId", "state", "publication", "delivery", "usage"}                  # no bundle, manifest or counts
    assert rig.run("inspect", rig.sel())["state"] == "ready"                                                         # the stored artifact still verifies as frozen
    assert rig.freeze()["receipt"]["bundleDigest"] == json.loads(before["handoffs"][0][6])["bundleDigest"]          # same request echoes the same receipt
    assert stored(rig) == before                                                                                     # nothing was rewritten, regenerated or deleted

    fresh = rig.bundle("h2")                                                                                         # the operator re-freezes under a new ID
    (edge,) = structural_edges(fresh)
    assert edge["basis"][0]["validUntil"] == "2026-09-30" and STRUCTURAL not in excluded(fresh)
    assert {k: v for k, v in stored(rig)["files"].items() if k in before["files"]} == before["files"]



# ---- H4: every frozen observation of a document version is kept and checked for metadata consistency -----------------------------

def test_h4_two_observations_of_one_document_version_with_different_urls_are_a_metadata_conflict(observation_world, tmp_path):
    y1, y2 = observation_world.refs["y1"], observation_world.refs["y2"]
    assert (y1["documentId"], y1["documentVersion"]) == (y2["documentId"], y2["documentVersion"]) and y1["roundId"] != y2["roundId"]
    export1, export2 = observation_world.kit.export(y1), observation_world.kit.export(y2)
    assert export1["observation"]["url"] != export2["observation"]["url"] and export1["observation"]["title"] == export2["observation"]["title"]
    rig = Rig(observation_world, tmp_path, docs=hs.observation_docs(observation_world))
    out = rig.freeze(expected=2)
    assert out["error"]["code"] == "article_metadata_conflict", out
    assert rig.rows() == 0

def test_h4_matching_metadata_preserves_both_exact_observations_without_duplicate_articles(matching_observation_world, tmp_path):
    rig = Rig(matching_observation_world, tmp_path, docs=hs.observation_docs(matching_observation_world))
    bundle = rig.bundle()
    ref = matching_observation_world.refs["y1"]
    matches = [a for a in bundle["articles"] if (a["documentId"], a["documentVersion"]) == (ref["documentId"], ref["documentVersion"])]
    assert len(matches) == 1
    assert {(o["roundId"], o["sourceId"], o["page"], o["ordinal"]) for o in matches[0]["observations"]} == {
        (r["roundId"], r["sourceId"], r["page"], r["ordinal"]) for r in (matching_observation_world.refs["y1"], matching_observation_world.refs["y2"])}
    assert len(matches[0]["observations"]) == 2


# ---- H5: nested schema, source-reference closure and id formulas hold even when the content digest is refreshed --------------------

def rehashed(bundle: dict, change) -> dict:
    copy = json.loads(json.dumps(bundle))
    change(copy)
    copy["digests"]["content"] = content_digest(copy)      # the corruption can no longer be caught by the global digest mismatch alone
    return copy


def first_relation(bundle: dict, kind: str) -> dict:
    return next(r for r in bundle["relations"] if r["type"] == kind)


def h5_mutations():
    return {
        "unknown key in a source audit": lambda b: b["sources"][0]["audit"].update(surprise=1),
        "unknown key in source policies": lambda b: b["sources"][0]["policies"].update(surprise="x"),
        "source event with a malformed upstream": lambda b: b["issues"][0]["sourceEvents"][0].update(upstream={"jobId": "s2-a"}),
        "source event naming an upstream that is not pinned": lambda b: b["issues"][0]["sourceEvents"][0].update(upstream={"jobId": "s2-x", "inputDigest": "a" * 64}),
        "geography basis naming an unpinned upstream": lambda b: b["issues"][0]["geography"]["basis"][0].update(upstream={"jobId": "s2-x", "inputDigest": "a" * 64}),
        "representative that is not a closed object": lambda b: b["issues"][0].update(representative={"surprise": 1}),
        "FOLLOWS falsely claiming S3 semantic validation": lambda b: first_relation(b, "FOLLOWS")["provenance"].update(s3SemanticValidation="independent-verifier-supported-all-claims"),
        "FOLLOWS provenance with an unknown key": lambda b: first_relation(b, "FOLLOWS")["provenance"].update(surprise=1),
        "INVOLVES provenance with another origin": lambda b: first_relation(b, "INVOLVES")["provenance"].update(origin="manual-operator-review"),
        "source reference to a job that is not a source": lambda b: first_relation(b, "INVOLVES")["sourceRefs"][0].update(jobId="rel-x"),
        "source reference with an unknown kind": lambda b: first_relation(b, "INVOLVES")["sourceRefs"][0].update(kind="topic"),
        "structural basis with an empty sourceRelation": lambda b: first_relation(b, "STRUCTURALLY_RELATED_TO")["basis"][0].update(sourceRelation={}),
        "structural basis naming an unpinned job": lambda b: first_relation(b, "STRUCTURALLY_RELATED_TO")["basis"][0]["sourceRelation"].update(jobId="rel-x"),
        "structural basis with malformed sourceArticles": lambda b: first_relation(b, "STRUCTURALLY_RELATED_TO")["basis"][0].update(sourceArticles=[{"articleId": "x"}]),
        "structural basis article that is not in articles": lambda b: first_relation(b, "STRUCTURALLY_RELATED_TO")["basis"][0].update(
            sourceArticles=[{"articleId": "doc-" + HASH, "articleVersion": HASH}]),
        "exclusion detail that is not a closed form": lambda b: (b["exclusions"]["items"].append({"kind": "issue", "id": "x", "jobId": None, "code": "geography_unproven",
                                                                                                   "detail": {"surprise": [1, 2]}}),
                                                                 b["exclusions"]["counts"].update(geography_unproven=b["exclusions"]["counts"].get("geography_unproven", 0) + 1),
                                                                 b["counts"].update(exclusions=b["counts"]["exclusions"] + 1)),
        "INVOLVES id that is not its formula": lambda b: first_relation(b, "INVOLVES").update(id="edge-" + "0" * 64),
        "FOLLOWS id that is not its formula": lambda b: first_relation(b, "FOLLOWS").update(id="edge-" + "0" * 64),
        "STRUCTURAL id that is not its basis formula": lambda b: first_relation(b, "STRUCTURALLY_RELATED_TO").update(id="edge-" + "0" * 64),
    }


@pytest.mark.parametrize("name,change", list(h5_mutations().items()), ids=list(h5_mutations()))
def test_h5_nested_corruption_is_refused_even_with_a_refreshed_content_digest(valid_bundle, name, change):
    validate_bundle(valid_bundle)
    broken = rehashed(valid_bundle, change)
    assert broken["digests"]["content"] == content_digest(broken)
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(broken)
    assert exc.value.code == "handoff_bundle_invalid", name


# ---- H6: a refused foreign state directory or database is left byte/schema/mode untouched --------------------------------------------

def namespace_snapshot(path: Path) -> tuple:
    entries = {p.name: (p.is_dir(), stat.S_IMODE(p.stat().st_mode), None if p.is_dir() else p.read_bytes()) for p in sorted(path.iterdir())}
    return entries, stat.S_IMODE(path.stat().st_mode)


def test_h6_a_foreign_directory_is_refused_without_creating_or_changing_anything(rig):
    foreign = rig.root / "foreign"
    foreign.mkdir(mode=0o755)
    (foreign / "notes.txt").write_text("not ours")
    os.chmod(foreign, 0o755)
    before = namespace_snapshot(foreign)
    error(rig.run("freeze", rig.manifest(), expected=2, state=foreign), "state_namespace_conflict")
    assert namespace_snapshot(foreign) == before             # no `bundles/`, no lock, no database, no chmod


@pytest.mark.parametrize("with_foreign_marker", [False, True])
def test_h6_a_foreign_sqlite_database_is_refused_without_a_byte_schema_or_mode_change(rig, with_foreign_marker):
    foreign = rig.root / "foreign-db"
    foreign.mkdir(mode=0o755)
    database = foreign / "handoff.sqlite3"
    db = sqlite3.connect(database)
    db.execute("CREATE TABLE notes(text TEXT)")
    db.execute("INSERT INTO notes VALUES('foreign data')")
    if with_foreign_marker:
        db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO meta VALUES('ledger','foreign-ledger')")
    db.commit()
    schema = db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
    db.close()
    os.chmod(database, 0o644)
    os.chmod(foreign, 0o755)
    before = namespace_snapshot(foreign)
    out = rig.run("freeze", rig.manifest(), expected=2, state=foreign)
    assert out["error"]["code"] in {"ledger_version_unknown", "handoff_state_invalid", "state_namespace_conflict"}, out
    assert namespace_snapshot(foreign) == before
    check = sqlite3.connect(database)
    try:
        assert check.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall() == schema
        assert check.execute("SELECT text FROM notes").fetchall() == [("foreign data",)]
    finally:
        check.close()


def _export(published, collection=None):
    observation = {"title": "t", "url": "https://example.invalid/a", "publishedAt": published}
    if collection is not None:
        observation["collection"] = {"published": collection}
    return {"observation": observation}


def test_article_publication_keeps_a_collected_day_as_a_day_and_never_widens_it():
    day = {"raw": "2026-10-14", "precision": "day", "date": "2026-10-14", "basis": "declared"}
    assert article_metadata(_export(None, day)) == ("t", "https://example.invalid/a", "2026-10-14", "day")
    instant = {"raw": "2026-10-14T09:00:00+09:00", "precision": "instant", "date": None, "basis": "declared"}
    assert article_metadata(_export("2026-10-14T09:00:00+09:00", instant)) == ("t", "https://example.invalid/a", "2026-10-14T09:00:00+09:00", "datetime")
    # An offset-less declared time is not an instant: the bundle says unknown instead of assuming a timezone.
    unresolved = {"raw": "2026-10-14T09:30:00", "precision": "unresolved", "date": None, "basis": "declared"}
    assert article_metadata(_export(None, unresolved)) == ("t", "https://example.invalid/a", None, "unknown")
    assert article_metadata(_export(None, {"raw": None, "precision": "unknown", "date": None, "basis": "none declared"}))[2:] == (None, "unknown")
    # Authored exports (no collection key) keep the earlier rule exactly.
    assert article_metadata(_export("2026-10-08T00:00:00+00:00"))[2:] == ("2026-10-08T00:00:00+00:00", "datetime")
    assert article_metadata(_export(None))[2:] == (None, "unknown")


def test_a_day_article_validates_and_inconsistent_precision_is_refused(rig):
    bundle = rig.bundle()
    target = rig.world.refs["b"]["documentId"]

    def validated(**changes):
        candidate = copy.deepcopy(bundle)
        next(a for a in candidate["articles"] if a["articleId"] == target).update(changes)
        candidate["digests"]["content"] = content_digest(candidate)
        validate_bundle(candidate)

    validated(publishedAt="2026-10-14", publicationPrecision="day")
    for bad in ({"publishedAt": "2026-10-14T00:00:00Z", "publicationPrecision": "day"}, {"publishedAt": None, "publicationPrecision": "day"},
                {"publishedAt": "2026-10-14", "publicationPrecision": "unknown"}, {"publishedAt": None, "publicationPrecision": "datetime"},
                {"publishedAt": "2026-10-14", "publicationPrecision": "date"}):
        with pytest.raises(ExtractionFailure):
            validated(**bad)


# ======================================================================================================================================
# Original mentions (bundle `-2`): what each source mention says, exactly as extracted, and nothing nobody decided.
# ======================================================================================================================================

MENTION_KEYS = {"documentId", "documentVersion", "mentionId", "articleId", "articleVersion", "verification", "title", "action", "target", "eventTime", "timePrecision",
                "period", "assertionStatus", "background", "participants", "evidenceIds"}


def mentions_of(bundle: dict) -> dict:
    return {i["id"]: i["mentions"] for i in bundle["issues"]}


def supply_of(bundle: dict) -> dict:
    return next(i for i in bundle["issues"] if i["id"] == "issue:supply-2026q3")


def participants_of(bundle: dict) -> dict:
    """(issue, local mention id, participant name) -> public company id: the name is unique inside each authored mention."""
    return {(i["id"], m["mentionId"], p["name"]): p["companyId"] for i in bundle["issues"] for m in i["mentions"] for p in m["participants"]}


def keys_of(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys_of(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys_of(item)


def test_every_public_issue_carries_its_hand_written_original_mentions_with_reachable_evidence(rig):
    bundle = rig.bundle()
    assert bundle["schemaVersion"] == "zoop-graph-handoff-bundle-2"
    assert mentions_of(bundle) == hs.expected_mentions(rig.world)
    hs.assert_mentions_reachable(bundle)
    assert rig.run("inspect", rig.sel())["receipt"]["bundleSchema"] == "zoop-graph-handoff-bundle-2"


def test_a_mention_is_a_closed_unverified_source_record_and_no_decision_support_approval_publisher_or_impact_is_invented(rig):
    bundle = rig.bundle()
    mentions = [m for i in bundle["issues"] for m in i["mentions"]]
    assert mentions and all(set(m) == MENTION_KEYS and m["verification"] == "none" and type(m["background"]) is bool for m in mentions)
    assert all(set(p) == {"sourceCompanyId", "companyId", "name", "role"} for m in mentions for p in m["participants"])
    assert not {"fieldDecisions", "sourceSupport", "approval", "publisher", "impact", "roleUnconfirmed", "verified"} & set(keys_of(bundle))


def test_a_mention_carried_by_two_upstreams_is_one_mention_and_every_source_event_identity_is_represented_exactly_once(rig):
    bundle = rig.bundle()
    for issue in bundle["issues"]:
        identities = [(m["documentId"], m["documentVersion"], m["mentionId"]) for m in issue["mentions"]]
        assert identities == sorted(set(identities)), issue["id"]
        assert set(identities) == {(s["documentId"], s["documentVersion"], s["mentionId"]) for s in issue["sourceEvents"]}, issue["id"]
    supply = supply_of(bundle)
    assert len(supply["sourceEvents"]) == 3 and len(supply["mentions"]) == 2          # document a's `m-a` is carried by upstream a (candidate) and upstream b (snapshot)


def test_two_documents_with_the_same_local_mention_id_are_two_mentions_each_with_its_own_evidence(collision_same, tmp_path):
    bundle = collision_rig(collision_same, tmp_path).bundle()
    supply = supply_of(bundle)
    assert len(supply["sourceEvents"]) == 3 and [m["mentionId"] for m in supply["mentions"]] == ["m-a", "m-a"]
    a, a2 = collision_same.refs["a"]["documentId"], collision_same.refs["a2"]["documentId"]
    assert {m["documentId"]: m["evidenceIds"] for m in supply["mentions"]} == {a: [hs.evidence_id(collision_same, "a", hs.EVT_A)],
                                                                               a2: [hs.evidence_id(collision_same, "a2", hs.EVT_A2)]}
    hs.assert_mentions_reachable(bundle)


def test_a_participant_is_public_only_where_every_carrying_upstream_maps_it_to_a_published_company(rig):
    bundle = rig.bundle()
    assert participants_of(bundle) == {
        ("issue:supply-2026q3", "m-a", "합성기업"): "KRX:005930", ("issue:supply-2026q3", "m-a", "합성부품"): "KRX:000660", ("issue:supply-2026q3", "m-a", "미상 거래처"): None,
        ("issue:supply-2026q3", "m-a2", "합성기업"): "KRX:005930",
        ("issue:factory-2026q4", "m-b", "합성기업"): "KRX:005930", ("issue:factory-2026q4", "m-b", "합성협력"): None,              # mapped to a company no public decision carries
        ("issue:factory-2026q4", "m-b", "미등록 법인"): None}                                                                    # no canonical entry at all
    # The participant as extracted is kept whether or not it is mapped; a name without a company id stays a name.
    assert {p["name"]: p["sourceCompanyId"] for i in bundle["issues"] for m in i["mentions"] for p in m["participants"]} == {
        "합성기업": "SYNTH-1", "합성부품": "SYNTH-3", "미상 거래처": None, "합성협력": "SYNTH-2", "미등록 법인": "SYNTH-9"}


def canonical_entry(rig, job: str, kind: str, ref: str) -> dict:
    return next(e for e in rig.docs["canonical"]["entries"] if (e["upstream"]["jobId"], e["kind"], e["ref"]) == (job, kind, ref))


def test_upstreams_that_map_one_company_id_to_different_companies_leave_the_participant_unmapped(rig):
    canonical_entry(rig, "s2-b", "company", "SYNTH-3")["canonicalId"] = "co:synth-1"       # b: the issuer's company, a: the supplier's: two published companies, no agreement
    rig.write()
    got = participants_of(rig.bundle())
    assert got[("issue:supply-2026q3", "m-a", "합성부품")] is None
    assert got[("issue:supply-2026q3", "m-a", "합성기업")] == "KRX:005930"                 # both upstreams agree on SYNTH-1


def test_a_company_id_that_one_carrying_upstream_cannot_map_is_unmapped_for_every_upstream(rig):
    rig.docs["canonical"]["entries"].remove(canonical_entry(rig, "s2-b", "company", "SYNTH-3"))
    rig.write()
    got = participants_of(rig.bundle())
    assert got[("issue:supply-2026q3", "m-a", "합성부품")] is None and got[("issue:supply-2026q3", "m-a", "합성기업")] == "KRX:005930"


def test_a_company_the_operator_maps_but_this_bundle_does_not_publish_is_not_claimed(rig):
    rig.docs["decisions"]["structural"] = []              # KRX:000660 is then the target of no relation, so the bundle no longer lists it
    rig.write()
    bundle = rig.bundle()
    assert [c["id"] for c in bundle["companies"]] == ["KRX:005930"]
    got = participants_of(bundle)
    assert got[("issue:supply-2026q3", "m-a", "합성부품")] is None and got[("issue:supply-2026q3", "m-a", "합성기업")] == "KRX:005930"
    assert "SYNTH-3" in {p["sourceCompanyId"] for m in supply_of(bundle)["mentions"] for p in m["participants"]}      # still there, as extracted


def test_one_mention_identity_with_different_values_in_two_upstreams_excludes_the_issue_and_publishes_neither(upstreams_disagree, tmp_path):
    bundle = Rig(upstreams_disagree, tmp_path).bundle()
    assert [i for i in bundle["exclusions"]["items"] if i["id"] == "issue:supply"] == [{"kind": "issue", "id": "issue:supply", "jobId": None, "code": "mention_values_conflict"}]
    assert issue_ids(bundle) == ["issue:factory-2026q4"]
    assert mentions_of(bundle) == {"issue:factory-2026q4": hs.expected_mentions(upstreams_disagree)["issue:factory-2026q4"]}
    text = json.dumps(bundle, ensure_ascii=False)
    assert hs.ACTION_SNAPSHOT not in text and "공급 계약 발표" not in text                    # neither value, and no last-wins
    assert {"mention_values_conflict", "issue_not_public"} <= set(excluded(bundle).values())      # what depended on the issue is excluded visibly, not dangling
    validate_bundle(bundle)


def test_a_members_event_time_without_an_offset_excludes_the_issue_although_the_issue_time_itself_is_clean(a2_time_offsetless, tmp_path):
    bundle = Rig(a2_time_offsetless, tmp_path).bundle()
    assert [i for i in bundle["exclusions"]["items"] if i["id"] == "issue:supply"] == [{"kind": "issue", "id": "issue:supply", "jobId": None,
                                                                                         "code": "mention_event_time_unsupported"}]
    assert issue_ids(bundle) == ["issue:factory-2026q4"] and "event_time_unsupported" not in set(excluded(bundle).values())


def test_a_members_iso_week_event_time_is_unsupported_even_though_python_parses_it_as_a_day(a2_time_iso_week, tmp_path):
    bundle = Rig(a2_time_iso_week, tmp_path).bundle()
    assert [i for i in bundle["exclusions"]["items"] if i["id"] == "issue:supply"] == [{"kind": "issue", "id": "issue:supply", "jobId": None,
                                                                                         "code": "mention_event_time_unsupported"}]
    assert issue_ids(bundle) == ["issue:factory-2026q4"]


def test_an_issue_whose_every_member_carries_an_iso_week_time_is_excluded_visibly_while_other_issues_still_freeze(event_time_iso_week, tmp_path):
    bundle = Rig(event_time_iso_week, tmp_path).bundle()          # freeze and export both succeed
    assert [i for i in bundle["exclusions"]["items"] if i["id"] == "issue:supply"] == [{"kind": "issue", "id": "issue:supply", "jobId": None,
                                                                                         "code": "mention_event_time_unsupported"}]
    assert issue_ids(bundle) == ["issue:factory-2026q4"] and "2026-W40-3" not in json.dumps(bundle)


def test_a_datetime_without_seconds_is_a_valid_mention_time_and_exports_as_a_datetime(event_time_no_seconds, tmp_path):
    bundle = Rig(event_time_no_seconds, tmp_path).bundle()
    assert "issue:supply" not in {i["id"] for i in bundle["exclusions"]["items"]}
    supply = supply_of(bundle)
    assert (supply["eventTime"], supply["timePrecision"]) == ("2026-09-30T09:00Z", "datetime")
    assert {m["mentionId"]: (m["eventTime"], m["timePrecision"]) for m in supply["mentions"]} == {"m-a": ("2026-09-30T09:00Z", "datetime"), "m-a2": ("2026-09-30T09:00Z", "datetime")}
    assert next(r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO")["source"] == "issue:supply-2026q3"       # the operator's attestation still binds


def test_a_members_coarser_event_time_keeps_its_own_precision_and_is_never_widened(a2_time_month, tmp_path):
    supply = supply_of(Rig(a2_time_month, tmp_path).bundle())
    assert (supply["eventTime"], supply["timePrecision"]) == ("2026-09-30", "day")
    assert {m["mentionId"]: (m["eventTime"], m["timePrecision"]) for m in supply["mentions"]} == {"m-a": ("2026-09-30", "day"), "m-a2": ("2026-09", "month")}


def test_counts_policy_and_attestations_are_the_earlier_bundles_so_operator_decisions_still_bind(rig):
    bundle = rig.bundle()
    assert set(bundle["counts"]) == {"companies", "issues", "relations", "evidence", "articles", "exclusions"} and bundle["counts"] == hs.expected(rig.world)["counts"]
    assert bundle["policy"]["version"] == POLICY
    edge = next(r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO")
    assert edge["provenance"]["bindingDigest"] == hs.structural_binding(rig.world)         # the operator's hand-computed digest over the source events alone still binds
    assert rig.run("inspect", rig.sel())["receipt"]["counts"] == bundle["counts"]


def mention_mutations():
    mentions = lambda b: supply_of(b)["mentions"]  # noqa: E731
    three = lambda b: next(m for m in mentions(b) if len(m["participants"]) == 3)  # noqa: E731
    return {
        "the issue without its mentions": lambda b: supply_of(b).pop("mentions"),
        "mentions that are not a list": lambda b: supply_of(b).update(mentions=None),
        "unknown key in a mention": lambda b: mentions(b)[0].update(surprise=1),
        "a mention without a key": lambda b: mentions(b)[0].pop("period"),
        "a verified mention": lambda b: mentions(b)[0].update(verification="verified"),
        "a field decision smuggled in": lambda b: mentions(b)[0].update(fieldDecisions={}),
        "a time precision that is not the event time's": lambda b: three(b).update(timePrecision="month"),
        "a time that cannot be classified": lambda b: three(b).update(eventTime="soon", timePrecision="unknown"),
        "background that is not a boolean": lambda b: mentions(b)[0].update(background="false"),
        "background as a number": lambda b: mentions(b)[0].update(background=0),
        "an assertion status outside the S2 values": lambda b: mentions(b)[0].update(assertionStatus="verified"),
        "a title that is not text": lambda b: mentions(b)[0].update(title=None),
        "participants that are not a list": lambda b: mentions(b)[0].update(participants=None),
        "a participant that is not an object": lambda b: mentions(b)[0].update(participants=["x"]),
        "a participant with an unknown key": lambda b: three(b)["participants"][0].update(surprise=1),
        "a participant name that is not text": lambda b: three(b)["participants"][0].update(name=None),
        "a public company that is not in the bundle": lambda b: three(b)["participants"][0].update(companyId="KRX:999999"),
        "a public company without a source company id": lambda b: three(b)["participants"][2].update(companyId="KRX:005930"),
        "evidence of another article": lambda b: three(b).update(evidenceIds=[next(e["id"] for e in b["evidence"] if e["articleId"] != three(b)["articleId"])]),
        "a mention without evidence": lambda b: three(b).update(evidenceIds=[]),
        "duplicate mention evidence": lambda b: three(b).update(evidenceIds=three(b)["evidenceIds"] * 2),
        "mentions out of order": lambda b: mentions(b).reverse(),
        "a duplicated mention": lambda b: mentions(b).append(copy.deepcopy(mentions(b)[0])),
        "a mention that is not a source event's": lambda b: three(b).update(mentionId="m-unknown"),
        "a source event without its mention": lambda b: mentions(b).pop(),
        "an article that is not the mention's own": lambda b: three(b).update(articleId=next(a["articleId"] for a in b["articles"] if a["articleId"] != three(b)["articleId"])),
        "an article version that is not the bound one": lambda b: three(b).update(articleVersion="f" * 64),
        "issue evidence missing a mention's evidence": lambda b: supply_of(b)["evidenceIds"].pop(),
        "issue evidence beyond the mentions' and geography's": lambda b: supply_of(b).update(evidenceIds=sorted(
            [*supply_of(b)["evidenceIds"], next(e["id"] for e in b["evidence"] if e["id"] not in supply_of(b)["evidenceIds"])])),
        "the earlier schema version": lambda b: b.update(schemaVersion="zoop-graph-handoff-bundle-1"),
    }


@pytest.mark.parametrize("name,change", list(mention_mutations().items()), ids=list(mention_mutations()))
def test_mention_closure_is_refused_even_with_a_refreshed_content_digest(valid_bundle, name, change):
    validate_bundle(valid_bundle)
    broken = rehashed(valid_bundle, change)
    assert broken["digests"]["content"] == content_digest(broken)
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(broken)
    assert exc.value.code == "handoff_bundle_invalid", name


def test_mention_text_is_verbatim_so_empty_strings_and_nulls_are_valid(valid_bundle):
    def blank(b):
        mention = supply_of(b)["mentions"][0]
        mention.update(title="", action="", target=None, period=None, eventTime=None, timePrecision="unknown")
        mention["participants"][0].update(name="", role="")
    validate_bundle(rehashed(valid_bundle, blank))


# ======================================================================================================================================
# Handoffs frozen under the earlier bundle schema (`-1`): immutable history, decided from the ledger alone.
# ======================================================================================================================================

CONTRACT_CHANGED = {"status": "withheld", "code": "handoff_contract_changed"}
LEGACY_ROWS = {"legacy-ready": ("ready", "written"), "legacy-reserved": ("reserved", "missing"), "legacy-failed": ("failed", "garbage")}


def legacy_rig(rig, rows: dict | None = None, **plant) -> dict:
    """The rig's handoff ledger holding rows of the build BEFORE original mentions (a real current handoff creates the ledger first; the earlier rows are this build's
    own export minus the new field, inserted with the ledger's own statements)."""
    bundle = rig.bundle("current-0")
    return {name: hs.plant_legacy_handoff(rig.state, rig.manifest(name), bundle, row_state=state, artifact=artifact, **plant)
            for name, (state, artifact) in (rows or LEGACY_ROWS).items()}


def test_a_handoff_frozen_under_the_earlier_bundle_schema_is_history_answered_from_the_ledger_alone(rig):
    planted = legacy_rig(rig)
    manifests = {name: rig.manifest(name) for name in planted}
    # Nothing a legacy answer must NOT need exists any more: the grant is revoked, an operator file is gone and another unreadable, the source ledgers are deleted,
    # two of the three artifacts are missing or garbage, and the ledger directory has modes that any writer would reset to 0700/0600.
    rig.grant(enabled=False)
    (rig.root / "decisions.json").write_bytes(b"{")
    (rig.root / "canonical.json").unlink()
    for name in ("relation", "extraction"):
        shutil.rmtree(rig.root / name)
    os.chmod(rig.state, 0o755)
    for path in rig.state.rglob("*"):
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    before = hs.ledger_snapshot(rig.state)
    for name, row in planted.items():
        seen = rig.run("inspect", rig.sel(name), expected=2)
        assert seen["state"] == row["state"] and seen["next"] is None and seen["delivery"] == CONTRACT_CHANGED and seen["publication"] == "not-published", seen
        assert seen["receipt"] == row["receipt"] and seen["attempts"] == row["attempts"] and "bundle" not in seen
        assert rig.run("export", rig.sel(name), expected=2) == {"schemaVersion": SCHEMA, "handoffId": name, "state": row["state"], "publication": "not-published",
                                                              "delivery": CONTRACT_CHANGED, "usage": {"providerCalls": 0, "modelCalls": 0}}
        error(rig.run("recover", rig.sel(name), expected=2), "handoff_contract_changed")
        error(rig.run("freeze", manifests[name], expected=2), "handoff_contract_changed")
        error(rig.run("freeze", {**manifests[name], "sourceKind": "actual"}, expected=2), "handoff_contract_changed")        # not an input conflict: the row is history
    assert hs.ledger_snapshot(rig.state) == before          # no byte, mode, mtime or file changed: nothing was opened for writing, created, settled or marked failed


def test_the_methods_recheck_the_contract_under_their_own_lock_without_the_cli_preflight(rig):
    planted = legacy_rig(rig)
    manifests = {name: Manifest.model_validate(rig.manifest(name)) for name in planted}
    paths = HandoffPaths(rig.root / "relation", rig.root / "extraction", rig.root / "ingestion", rig.sources, rig.root / "canonical.json", rig.root / "decisions.json",
                         rig.root / "bindings.json")
    before = stored(rig)
    store = Store(rig.state, paths.relation, paths.extraction, paths.ingestion, mode="write")        # the WRITER, exactly what the preflight keeps legacy commands away from
    try:
        handoff = Handoff(store, paths)
        for name in planted:
            selector = Selector.model_validate(rig.sel(name))
            for refused in (lambda: handoff.recover(selector), lambda: handoff.freeze(manifests[name])):  # noqa: B023
                with pytest.raises(ExtractionFailure) as exc:
                    refused()
                assert exc.value.code == "handoff_contract_changed"
            assert handoff.inspect(selector)["delivery"] == CONTRACT_CHANGED
            assert handoff.export(selector)["delivery"] == CONTRACT_CHANGED
    finally:
        store.close()
    assert stored(rig) == before          # no attempt was added, no state settled, no file written


def test_a_new_handoff_id_freezes_and_exports_beside_the_legacy_history_which_stays_as_it_was(rig):
    planted = legacy_rig(rig)

    def history() -> dict:
        return {"rows": rig.sql("SELECT * FROM handoffs WHERE handoff_id LIKE 'legacy-%' ORDER BY handoff_id"),
                "attempts": rig.sql("SELECT * FROM attempts WHERE handoff_id LIKE 'legacy-%' ORDER BY handoff_id, n"),
                "files": {name: (p["artifact"].read_bytes() if p["artifact"].exists() else None) for name, p in planted.items()}}

    before = history()
    bundle = rig.bundle("h2")
    assert bundle["schemaVersion"] == "zoop-graph-handoff-bundle-2" and bundle["handoffId"] == "h2"
    assert history() == before


def test_a_receipt_that_names_no_bundle_schema_is_damaged_state_never_history(rig):
    legacy_rig(rig, {"damaged": ("ready", "written")}, schema=None)
    for command in ("inspect", "export", "recover"):
        error(rig.run(command, rig.sel("damaged"), expected=2), "handoff_state_invalid")


def test_a_bundle_of_the_earlier_schema_is_never_a_valid_current_bundle(rig, valid_bundle):
    old = hs.legacy_bundle(valid_bundle, rig.manifest("old"))
    assert old["schemaVersion"] == "zoop-graph-handoff-bundle-1" and all("mentions" not in i for i in old["issues"])
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(old)
    assert exc.value.code == "handoff_bundle_invalid"

