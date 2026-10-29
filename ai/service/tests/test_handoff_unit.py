"""The read-only handoff door, everything that needs no child process: all-or-nothing configuration, the export allowlist, the exit-code and canonical-line
interpretation, the CLOSED bundle model (checked exhaustively over every node of a bundle carrying every variant), the delivery rules (with a scripted process
object) and the generated examples.

The behavior that needs a real service process (argv, environment, working directory, concurrency, deadlines, logs) lives in `test_handoff_http.py` with a
test-owned stand-in command; the real installed `zoop-ai-handoff` over an actual two-job world is `pipeline_tests/test_handoff_real_cli.py` and
`scripts/handoff_service_smoke.py`.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import pytest
from pydantic import ValidationError

from handoff_support import (HANDOFF, HANDOFF_VARS, OTHER_HANDOFF, PRINCIPAL, SOURCE_DATA, HandoffWorkspace, envelope, error_output, export_entry, full_bundle,
                             live_bundle, manifest_of, mutated, seal, withheld_output)
from support import canonical
from zoop_ai_service import handoff_access
from zoop_ai_service.config import ConfigError, load
from zoop_ai_service.handoff_doc import examples, example_bundle, pins, summary_of
from zoop_ai_service.handoff_reads import HandoffError, HandoffReads
from zoop_ai_service.handoff_runtime import interpret
from zoop_ai_service.handoff_wire import (MAX_COMPANIES, Bundle, Export, HdBundle, HdErrorEnvelope, HdStatus)
from zoop_ai_service.jobs import Observation
from zoop_ai_service.relation_runtime import RelationGate
from zoop_ai_service.runtime import Outcome

BASE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1"}


def refused(env: dict[str, str]) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        load(env)
    return caught.value


def without_handoff(ws: HandoffWorkspace) -> dict[str, str]:
    return {key: value for key, value in ws.env().items() if key not in HANDOFF_VARS}


# ---- configuration: all or nothing -------------------------------------------------------------------------------------

def test_without_any_handoff_variable_the_feature_is_off_and_naming_its_roots_never_switches_another_group_on(tmp_path):
    ws = HandoffWorkspace(tmp_path)
    assert load(without_handoff(ws)).handoff is None
    config = load(ws.env())
    assert config.handoff is not None and config.relation is None and config.extraction is None and config.graph is None


def test_a_complete_group_loads_and_its_child_gets_the_ownership_environment_and_nothing_else(tmp_path):
    ws = HandoffWorkspace(tmp_path, with_relation=True)
    config = load({**ws.env(), "ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_USER": "u", "ZOOP_GRAPH_PASSWORD": "p", "OPENAI_API_KEY": "k"})
    handoff = config.handoff
    assert handoff is not None and handoff.shared_gate and handoff.state_dir == ws.handoff_state and handoff.exports_path == ws.exports
    assert (handoff.canonical_path, handoff.decisions_path, handoff.bindings_path) == (ws.canonical, ws.decisions, ws.bindings)
    assert dict(handoff.child_env) == {**BASE_ENV, "ZOOP_STATE_DIR": str(ws.app_state), "ZOOP_AI_WORKER_STATE_DIR": str(ws.worker)}
    assert config.relation is not None and config.graph is None
    assert not [key for key in handoff.child_env if key.startswith(("ZOOP_GRAPH_", "OPENAI", "TYPESAFE", "ZOOP_AI_API"))]
    standalone = load(HandoffWorkspace(tmp_path / "alone").env()).handoff
    assert standalone is not None and not standalone.shared_gate   # no S2/S3 group in this process: nothing of theirs to serialize against


@pytest.mark.parametrize("name", HANDOFF_VARS)
def test_a_partial_group_refuses_to_start_and_names_the_missing_variable(tmp_path, name):
    ws = HandoffWorkspace(tmp_path)
    error = refused(ws.env(**{name: None}))
    assert (error.field, error.reason) == (name, "handoff_group_incomplete")


def test_every_member_is_validated_when_any_is_present_and_no_value_is_ever_named(tmp_path):
    ws = HandoffWorkspace(tmp_path)
    assert refused(ws.env(ZOOP_STATE_DIR=None)).field == "ZOOP_STATE_DIR"
    assert refused(ws.env(ZOOP_AI_SERVICE_HANDOFF_COMMAND="relative/cli")).reason == "not_absolute_normalized"
    assert refused(ws.env(ZOOP_AI_SERVICE_HANDOFF_COMMAND=str(ws.sources))).reason == "file_unusable"   # exists, is not executable
    for name in ("ZOOP_AI_HANDOFF_STATE_DIR", "ZOOP_AI_HANDOFF_RELATION_STATE_DIR", "ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR", "ZOOP_AI_HANDOFF_INGESTION_STATE_DIR"):
        error = refused(ws.env(**{name: str(tmp_path / "absent")}))
        assert (error.field, error.reason) == (name, "directory_missing")
    for name in ("ZOOP_AI_SERVICE_HANDOFF_SOURCES", "ZOOP_AI_SERVICE_HANDOFF_CANONICAL", "ZOOP_AI_SERVICE_HANDOFF_DECISIONS", "ZOOP_AI_SERVICE_HANDOFF_BINDINGS",
                 "ZOOP_AI_SERVICE_HANDOFF_EXPORTS"):
        error = refused(ws.env(**{name: str(tmp_path / "absent.json")}))
        assert (error.field, error.reason) == (name, "file_unusable")
    link = tmp_path / "linked"
    link.symlink_to(ws.handoff_state, target_is_directory=True)
    assert refused(ws.env(ZOOP_AI_HANDOFF_STATE_DIR=str(link))).reason == "symlinked_component"
    error = refused(ws.env(ZOOP_AI_SERVICE_HANDOFF_EXPORTS=str(tmp_path / "secret-name.json")))
    assert str(error) == "ZOOP_AI_SERVICE_HANDOFF_EXPORTS" and "secret-name" not in repr(error)


def test_the_handoff_roots_may_not_overlap_each_other_or_the_service_worker_and_app_roots(tmp_path):
    ws = HandoffWorkspace(tmp_path)
    inner = ws.relation_state / "inner"
    inner.mkdir()
    ws.worker.mkdir(exist_ok=True)
    for name, value in (("ZOOP_AI_HANDOFF_STATE_DIR", str(ws.state)), ("ZOOP_AI_HANDOFF_STATE_DIR", str(ws.worker)), ("ZOOP_AI_HANDOFF_STATE_DIR", str(inner)),
                        ("ZOOP_AI_HANDOFF_STATE_DIR", str(ws.ingestion_state)), ("ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR", str(ws.ingestion_state)),
                        ("ZOOP_STATE_DIR", str(ws.handoff_state)), ("ZOOP_AI_HANDOFF_STATE_DIR", str(tmp_path))):
        error = refused(ws.env(**{name: value}))
        assert error.reason in {"handoff_roots_overlap", "overlaps_worker_state", "overlaps_app_state"}, (name, value, error.reason)


def test_the_handoff_reads_exactly_the_ledgers_an_s3_group_of_the_same_process_writes(tmp_path):
    ws = HandoffWorkspace(tmp_path, with_relation=True)
    other = tmp_path / "other"
    other.mkdir()
    for name in ("ZOOP_AI_HANDOFF_RELATION_STATE_DIR", "ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR", "ZOOP_AI_HANDOFF_INGESTION_STATE_DIR"):
        error = refused(ws.env(**{name: str(other)}))
        assert (error.field, error.reason) == (name, "handoff_source_inconsistent")
    registry = tmp_path / "other-sources.json"
    registry.write_text("{}")
    error = refused(ws.env(ZOOP_AI_SERVICE_HANDOFF_SOURCES=str(registry)))
    assert (error.field, error.reason) == ("ZOOP_AI_SERVICE_HANDOFF_SOURCES", "handoff_source_inconsistent")
    assert load(ws.env()).handoff is not None


# ---- the export allowlist ------------------------------------------------------------------------------------------------

def document(*entries: Any, **extra: Any) -> str:
    return json.dumps({"schemaVersion": handoff_access.SCHEMA, "handoffs": list(entries), **extra})


@pytest.mark.parametrize("content,reason", [
    ("{not json", "handoff_allowlist_not_json"),
    ("[]", "handoff_allowlist_shape"),
    (json.dumps({"schemaVersion": "wrong", "handoffs": []}), "handoff_allowlist_shape"),
    (document(extra=1), "handoff_allowlist_shape"),
    (document({"principal": PRINCIPAL}), "handoff_allowlist_entry_shape"),
    (document({**export_entry(), "storeId": "store-1"}), "handoff_allowlist_entry_shape"),
    (document({k: v for k, v in export_entry().items() if k != "bundleDigest"}), "handoff_allowlist_entry_shape"),   # both pins are required
    (document({k: v for k, v in export_entry().items() if k != "manifestDigest"}), "handoff_allowlist_entry_shape"),
    (document(export_entry(manifestDigest="short")), "handoff_allowlist_entry_invalid"),
    (document(export_entry(bundleDigest="A" * 64)), "handoff_allowlist_entry_invalid"),
    (document(export_entry(handoff_id="bad id")), "handoff_allowlist_entry_invalid"),
    (document(export_entry(handoff_id="x" * 201)), "handoff_allowlist_entry_invalid"),
    (document(export_entry(bundleDigest=7)), "handoff_allowlist_entry_invalid"),
    (document(export_entry(principal="nobody")), "handoff_allowlist_unknown_principal"),
    (document(export_entry(), export_entry(bundleDigest="d" * 64)), "handoff_allowlist_duplicate"),
    ('{"schemaVersion":"%s","handoffs":[],"handoffs":[]}' % handoff_access.SCHEMA, "handoff_allowlist_not_json"),
    ('{"schemaVersion":"%s","handoffs":[{"principal":"handoffer","handoffId":"a","handoffId":"b","manifestDigest":"%s","bundleDigest":"%s"}]}'
     % (handoff_access.SCHEMA, "a" * 64, "b" * 64), "handoff_allowlist_not_json"),
    ("x" * (handoff_access.MAX_BYTES + 1), "handoff_allowlist_too_large"),
])
def test_the_export_allowlist_is_strict_and_fails_closed_at_start(tmp_path, content, reason):
    ws = HandoffWorkspace(tmp_path)
    ws.exports.write_text(content)
    error = refused(ws.env())
    assert (error.field, error.reason) == ("ZOOP_AI_SERVICE_HANDOFF_EXPORTS", reason)


def test_the_allowlist_binds_a_principal_to_exact_handoffs_and_both_pins_and_is_read_fresh(tmp_path):
    path = tmp_path / "exports.json"
    path.write_text(document(export_entry(), export_entry("alpha", OTHER_HANDOFF, bundle=full_bundle())))
    access = handoff_access.load(path, [PRINCIPAL, "alpha"])
    fixed = pins(example_bundle())
    assert access.find(PRINCIPAL, HANDOFF) == handoff_access.Entry(PRINCIPAL, HANDOFF, fixed["manifestDigest"], fixed["bundleDigest"])
    assert access.find("alpha", HANDOFF) is None and access.find(PRINCIPAL, OTHER_HANDOFF) is None   # another principal's handoff is not yours
    path.write_text(document())
    assert handoff_access.load(path, [PRINCIPAL]).find(PRINCIPAL, HANDOFF) is None
    path.unlink()
    with pytest.raises(handoff_access.AccessError) as caught:
        handoff_access.load(path, [PRINCIPAL])
    assert caught.value.code == "handoff_allowlist_unreadable"


# ---- the exit-code and canonical-line interpretation ---------------------------------------------------------------------------

def line(value: Any) -> bytes:
    return (canonical(value) + "\n").encode("utf-8")


def test_exit_zero_is_a_current_result_and_exit_two_a_withheld_result_or_an_error_object():
    current = interpret(0, line(envelope()))
    assert (current.kind, current.exit_code, current.result["handoffId"]) == ("result", 0, HANDOFF)
    assert interpret(0, canonical(envelope()).encode()).kind == "result"        # the trailing newline is optional
    withheld = interpret(2, line(withheld_output()))
    assert (withheld.kind, withheld.exit_code) == ("result", 2)
    refusal = interpret(2, line(error_output("handoff_not_ready", {"state": "reserved"})))
    assert (refusal.kind, refusal.code, refusal.exit_code) == ("error", "handoff_not_ready", 2)
    assert refusal.result["error"]["detail"] == {"state": "reserved"}


@pytest.mark.parametrize("code,raw", [
    (0, line(withheld_output())), (2, line(envelope())), (0, line(error_output("handoff_busy"))), (3, line(envelope())), (1, b""), (0, b"not json"), (0, b"[]"),
    (0, line({**envelope(), "schemaVersion": "zoop-relation-s3"})), (0, line({**envelope(), "handoffId": None})), (0, line({**envelope(), "delivery": None})),
    (2, line(error_output("Not A Code"))), (2, line({"schemaVersion": "zoop-ai-handoff-1", "error": "x"})), (2, b"\xff\xfe"),
    (0, json.dumps(envelope(), sort_keys=True).encode()),                                           # ensure_ascii escapes: not the producer's canonical line
    (0, json.dumps(envelope(), ensure_ascii=False, separators=(",", ":")).encode()),                 # unsorted keys
    (0, line(envelope()) + b"\n"), (0, b" " + line(envelope())),                                     # extra whitespace changes the line
    (0, b'{"handoffId":"x","handoffId":"y","schemaVersion":"zoop-ai-handoff-1"}\n'), (0, b'{"a":NaN}\n'), (0, b'{"a":Infinity}\n'),
])
def test_anything_else_is_abnormal_and_never_read_as_a_result(code, raw):
    assert interpret(code, raw).kind == "abnormal"


# ---- the closed bundle model ---------------------------------------------------------------------------------------------------

def walk(node: Any, path: tuple = ()):
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk(value, (*path, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, (*path, index))


def at(root: Any, path: tuple) -> Any:
    for step in path:
        root = root[step]
    return root


OPEN_MAPS = {("sources", 0, "audit", "eligibleNotPublicByType"), ("sources", 1, "audit", "eligibleNotPublicByType"), ("exclusions", "counts")}
SAMPLES = [("example", example_bundle()), ("every-variant", full_bundle())]


@pytest.mark.parametrize("name,bundle", SAMPLES, ids=[n for n, _ in SAMPLES])
def test_the_model_accepts_exactly_what_it_was_given_and_dumps_it_back_unchanged(name, bundle):
    parsed = Bundle.model_validate(bundle)
    assert parsed.wire() == bundle and canonical(parsed.wire()) == canonical(bundle)
    shuffled = json.loads(json.dumps(bundle, sort_keys=True))   # key order is never part of the contract
    assert canonical(Bundle.model_validate(shuffled).wire()) == canonical(bundle)
    assert json.loads(json.dumps(parsed.wire())) == bundle


def test_source_policy_discriminator_keeps_historical_bytes_and_requires_current_country_pin():
    current = example_bundle()
    assert Bundle.model_validate(current).wire() == current
    historical = copy.deepcopy(current)
    for source in historical["sources"]:
        source["policies"]["policy"] = "zoop-relation-policy-1"
        del source["policies"]["countryContext"]
    assert Bundle.model_validate(historical).wire() == historical
    for change in (lambda p: p.pop("countryContext"), lambda p: p.update(countryContext="zoop-country-context-2"),
                   lambda p: p.update(countryContext=None), lambda p: p.update(countryContext=""),
                   lambda p: p.update(policy="zoop-relation-policy-1"), lambda p: p.update(policy="zoop-relation-policy-3"),
                   lambda p: p.update(unrecognized="pin")):
        broken = copy.deepcopy(current)
        change(broken["sources"][0]["policies"])
        with pytest.raises(ValidationError):
            Bundle.model_validate(broken)


@pytest.mark.parametrize("name,bundle", SAMPLES, ids=[n for n, _ in SAMPLES])
def test_a_key_the_producer_did_not_define_is_refused_at_every_level(name, bundle):
    checked = 0
    for path, node in walk(bundle):
        if isinstance(node, dict):
            broken = copy.deepcopy(bundle)
            at(broken, path)["bad key!"] = 1          # not an identifier: refused even where a map is open
            with pytest.raises(ValidationError):
                Bundle.model_validate(broken)
            if path not in OPEN_MAPS:
                broken = copy.deepcopy(bundle)
                at(broken, path)["extraField"] = "x"
                with pytest.raises(ValidationError):
                    Bundle.model_validate(broken)
            checked += 1
    assert checked >= 30


@pytest.mark.parametrize("name,bundle", SAMPLES, ids=[n for n, _ in SAMPLES])
def test_every_node_refuses_a_value_of_the_wrong_json_type(name, bundle):
    checked = 0
    for path, node in walk(bundle):
        if not path:
            continue
        broken = copy.deepcopy(bundle)
        replacement = {"unexpected": 1} if not isinstance(node, dict) else 5
        at(broken, path[:-1])[path[-1]] = replacement
        with pytest.raises(ValidationError):
            Bundle.model_validate(broken)
        checked += 1
    assert checked >= 200


@pytest.mark.parametrize("name,bundle", SAMPLES, ids=[n for n, _ in SAMPLES])
def test_a_missing_required_key_is_refused_everywhere_except_the_one_optional_detail(name, bundle):
    checked = 0
    for path, node in walk(bundle):
        if isinstance(node, dict) and path not in OPEN_MAPS:
            for key in node:
                broken = copy.deepcopy(bundle)
                del at(broken, path)[key]
                if key == "detail":
                    assert Bundle.model_validate(broken).wire() == broken   # absent detail stays absent: no default is added on the way back
                else:
                    with pytest.raises(ValidationError):
                        Bundle.model_validate(broken)
                checked += 1
    assert checked >= 100


@pytest.mark.parametrize("value", [1.0, 1.5, True, "1", None, -1, float("nan")])
def test_numbers_are_integers_only_so_a_float_bool_or_string_never_reaches_the_digest(value):
    bundle = example_bundle()
    bundle["articles"][0]["observations"][0]["page"] = value
    with pytest.raises(ValidationError):
        Bundle.model_validate(bundle)


def test_a_float_that_equals_an_integer_is_not_an_integer_and_a_null_or_bool_is_not_a_count():
    for name, value in (("float", 3.0), ("bool", True), ("null", None)):
        bundle = example_bundle()
        bundle["counts"]["companies"] = value
        with pytest.raises(ValidationError):
            Bundle.model_validate(bundle)


def test_the_documented_limits_are_enforced():
    bundle = example_bundle()
    bundle["companies"] = [copy.deepcopy(bundle["companies"][0]) for _ in range(MAX_COMPANIES + 1)]
    with pytest.raises(ValidationError):
        Bundle.model_validate(bundle)
    for change in (lambda b: b["sources"].clear(), lambda b: b["sources"].extend(copy.deepcopy(b["sources"][0]) for _ in range(20)),
                   lambda b: b["articles"][0].update(title="x" * 2001), lambda b: b["articles"][0].update(url="x" * 4001),
                   lambda b: b["articles"][0].update(observations=[]), lambda b: b["relations"][0].update(basis=[{}, {}, {}]),
                   lambda b: b["issues"][0]["geography"].update(countries=["KR"] * 11), lambda b: b["companies"][0].update(id="a" * 201),
                   lambda b: b["checks"].update(producerConfirmed=["x"] * 21),
                   lambda b: b["issues"][0].update(mentions=[copy.deepcopy(b["issues"][0]["mentions"][0]) for _ in range(1001)]),
                   lambda b: b["issues"][0]["mentions"][0].update(participants=[copy.deepcopy(b["issues"][0]["mentions"][0]["participants"][0]) for _ in range(1001)]),
                   lambda b: b["issues"][0]["mentions"][0].update(evidenceIds=[]),
                   lambda b: b["issues"][0]["mentions"][0].update(title="x" * (6 * 1024 * 1024 + 1))):
        broken = example_bundle()
        change(broken)
        with pytest.raises(ValidationError):
            Bundle.model_validate(broken)


def test_native_empty_and_long_s2_mention_strings_are_relayed_verbatim_not_refused():
    """S2 puts no emptiness or length rule on a mention's title/action/target/period or a participant's source id, name and role: the model keeps them as given."""
    bundle = example_bundle()
    mention = bundle["issues"][0]["mentions"][0]
    mention.update(title="", action="", target="", period="")
    mention["participants"][0].update(sourceCompanyId="", name="", role="")
    mention["participants"][1].update(name="  공백 보존  ", role="x" * 50_000)
    parsed = Bundle.model_validate(bundle)
    assert parsed.wire() == bundle and canonical(parsed.wire()) == canonical(bundle)


FIELDS = ("title", "action", "target", "eventTime", "period", "assertionStatus")


def provenance_refusals() -> list[tuple[str, Callable[[dict], Any]]]:
    def at_issue(change: Callable[[dict], Any]) -> Callable[[dict], Any]:
        return lambda bundle: change(bundle["issues"][0]["fieldProvenance"])
    cases: list[tuple[str, Callable[[dict], Any]]] = [
        ("selection-unknown", at_issue(lambda p: p.update(selection="consensus"))),
        ("selection-null", at_issue(lambda p: p.update(selection=None))),
        ("verification-verified", at_issue(lambda p: p.update(verification="operator-field-verdict"))),
        ("verification-null", at_issue(lambda p: p.update(verification=None))),
        ("same-value-null", at_issue(lambda p: p.update(sameValueMentions=None))),
        ("same-value-geography", at_issue(lambda p: p["sameValueMentions"].update(geography=[]))),
        ("same-value-time-precision", at_issue(lambda p: p["sameValueMentions"].update(timePrecision=[]))),
        ("field-decisions-in-provenance", at_issue(lambda p: p.update(fieldDecisions=[]))),
        ("field-decisions-in-issue", lambda bundle: bundle["issues"][0].update(fieldDecisions=[])),
        ("provenance-missing", lambda bundle: bundle["issues"][0].pop("fieldProvenance")),
        ("provenance-null", lambda bundle: bundle["issues"][0].update(fieldProvenance=None)),
        ("reference-extra-key", at_issue(lambda p: p["sameValueMentions"]["title"][0].update(articleId="doc-" + "c" * 64))),
        ("reference-version-short", at_issue(lambda p: p["sameValueMentions"]["title"][0].update(documentVersion="a" * 63))),
        ("reference-mention-empty", at_issue(lambda p: p["sameValueMentions"]["title"][0].update(mentionId=""))),
        ("reference-index", at_issue(lambda p: p["sameValueMentions"].update(title=[0]))),
        ("list-over-limit", at_issue(lambda p: p["sameValueMentions"].update(title=[copy.deepcopy(p["sameValueMentions"]["title"][0]) for _ in range(1001)]))),
    ]
    for field in FIELDS:
        cases += [(f"{field}-empty", at_issue(lambda p, f=field: p["sameValueMentions"].update({f: []}))),
                  (f"{field}-missing", at_issue(lambda p, f=field: p["sameValueMentions"].pop(f))),
                  (f"{field}-null", at_issue(lambda p, f=field: p["sameValueMentions"].update({f: None})))]
    return cases


@pytest.mark.parametrize("name,change", provenance_refusals(), ids=[name for name, _ in provenance_refusals()])
def test_the_field_provenance_is_closed_in_shape_and_a_malformed_one_is_refused(name, change):
    for bundle in (example_bundle(), full_bundle()):
        change(bundle)
        with pytest.raises(ValidationError):
            Bundle.model_validate(bundle)


def test_the_model_checks_the_shape_of_the_provenance_and_never_its_semantics():
    """Exactness, order, closure and the selection rule belong to the producer: a shape-valid list the producer would refuse is relayed as it came, because
    the service neither repairs nor judges it (the producer's validator and the application importer refuse it)."""
    bundle = full_bundle()
    mentions = bundle["issues"][0]["fieldProvenance"]["sameValueMentions"]
    mentions["title"] = list(reversed(mentions["action"]))
    mentions["target"] = mentions["action"] + mentions["action"]
    parsed = Bundle.model_validate(bundle)
    assert parsed.wire() == bundle and canonical(parsed.wire()) == canonical(bundle)


def test_the_example_and_the_every_variant_fixture_state_a_truthful_provenance():
    """The authored provenance of both fixtures equals what the producer's rule derives: exact equality of every headline value, null equal null."""
    for bundle in (example_bundle(), full_bundle()):
        issue = bundle["issues"][0]
        provenance = issue["fieldProvenance"]
        assert provenance["verification"] == "none"
        assert provenance["selection"] == ("operator-representative" if issue["representative"] is not None else "unanimous")
        assert set(provenance["sameValueMentions"]) == set(FIELDS)
        for field in FIELDS:
            expected = [{key: mention[key] for key in ("documentId", "documentVersion", "mentionId")} for mention in issue["mentions"] if mention[field] == issue[field]]
            assert expected and provenance["sameValueMentions"][field] == expected, field
        if provenance["selection"] == "unanimous":
            assert all(len(provenance["sameValueMentions"][field]) == len(issue["mentions"]) for field in FIELDS)


def verdict_refusals() -> list[tuple[str, Callable[[dict], Any]]]:
    def at_verdict(change: Callable[[dict], Any]) -> Callable[[dict], Any]:
        return lambda bundle: change(bundle["issues"][0]["fieldVerdicts"][0])
    return [
        ("missing-list", lambda b: b["issues"][0].pop("fieldVerdicts")), ("null-list", lambda b: b["issues"][0].update(fieldVerdicts=None)),
        ("list-over-limit", lambda b: b["issues"][0].update(fieldVerdicts=[copy.deepcopy(b["issues"][0]["fieldVerdicts"][0]) for _ in range(2001)])),
        ("withheld-missing", lambda b: b["issues"][0]["fieldProvenance"].pop("withheld")), ("withheld-null", lambda b: b["issues"][0]["fieldProvenance"].update(withheld=None)),
        ("withheld-unknown-field", lambda b: b["issues"][0]["fieldProvenance"].update(withheld=["title"])),
        ("withheld-over-limit", lambda b: b["issues"][0]["fieldProvenance"].update(withheld=["eventTime", "period", "period"])),
        ("extra-key", at_verdict(lambda v: v.update(extra=1))), ("free-text-note", at_verdict(lambda v: v.update(note="review prose"))),
        ("raw-spans", at_verdict(lambda v: v.update(evidence=[{"start": 0, "end": 1}]))), ("field-title", at_verdict(lambda v: v.update(field="title"))),
        ("value-null", at_verdict(lambda v: v.update(value=None))), ("decision-lowercase", at_verdict(lambda v: v.update(decision="allow"))),
        ("reason-unknown", at_verdict(lambda v: v.update(reasonCode="other"))), ("verification-none", at_verdict(lambda v: v.update(verification="none"))),
        ("allow-without-spans", at_verdict(lambda v: v.update(evidenceIds=[]))), ("allow-wrong-reason", at_verdict(lambda v: v.update(reasonCode="ambiguous"))),
        ("reject-stated", at_verdict(lambda v: v.update(decision="REJECT"))), ("hold-unstated-with-span", at_verdict(lambda v: v.update(decision="HOLD", reasonCode="unstated"))),
        ("hold-ambiguous-no-span", at_verdict(lambda v: v.update(decision="HOLD", reasonCode="ambiguous", evidenceIds=[]))),
        ("hold-contradicted", at_verdict(lambda v: v.update(decision="HOLD", reasonCode="contradicted"))),
        ("evidence-bad-id", at_verdict(lambda v: v.update(evidenceIds=["x"]))),
        ("evidence-over-limit", at_verdict(lambda v: v.update(evidenceIds=[v["evidenceIds"][0]] * 21))),
        ("reviewer-bad", at_verdict(lambda v: v.update(reviewer="a b"))), ("mention-id-empty", at_verdict(lambda v: v.update(mentionId=""))),
    ]


@pytest.mark.parametrize("name,change", verdict_refusals(), ids=[name for name, _ in verdict_refusals()])
def test_a_malformed_field_verdict_or_withheld_list_is_refused(name, change):
    for bundle in (example_bundle(), full_bundle()):
        change(bundle)
        with pytest.raises(ValidationError):
            Bundle.model_validate(bundle)


def test_verdict_shapes_are_accepted_and_relayed_exactly_without_semantic_judgement():
    """All four legal decision/reason/span combinations pass, an empty list is legal (no verdict is not a verification) and a verdict the producer would refuse
    (a value no mention carries) is still relayed: the service judges shape only."""
    bundle = full_bundle()
    base = bundle["issues"][0]["fieldVerdicts"][0]
    span = base["evidenceIds"]
    bundle["issues"][0]["fieldVerdicts"] = [
        {**base, "decision": "ALLOW", "reasonCode": "stated", "evidenceIds": span}, {**base, "decision": "HOLD", "reasonCode": "unstated", "evidenceIds": []},
        {**base, "decision": "HOLD", "reasonCode": "ambiguous", "evidenceIds": span}, {**base, "decision": "REJECT", "reasonCode": "contradicted", "evidenceIds": span},
        {**base, "value": "not-a-mention-value"}]
    bundle["issues"][0]["fieldProvenance"]["withheld"] = ["eventTime", "period"]
    assert Bundle.model_validate(bundle).wire() == bundle
    for empty in (example_bundle(), full_bundle()):
        empty["issues"][0]["fieldVerdicts"] = []
        empty["issues"][0]["summary"] = summary_of(empty, "not-requested")    # no HOLD/REJECT is left: the issue is no longer `temporal-review-pending`
        assert Bundle.model_validate(empty).wire() == empty


def test_the_fixtures_carry_closed_verdict_keys_and_no_review_prose():
    for bundle in (example_bundle(), full_bundle()):
        for verdict in bundle["issues"][0]["fieldVerdicts"]:
            assert set(verdict) == {"documentId", "documentVersion", "mentionId", "field", "value", "decision", "reasonCode", "evidenceIds", "verification", "reviewer",
                                    "decisionRef", "decisionVersion"} and verdict["verification"] == "operator-field-verdict"
        assert bundle["issues"][0]["fieldProvenance"]["withheld"] == []


def test_the_envelope_projection_drops_what_the_application_may_not_read_and_keeps_the_bundle_as_received():
    view = Export.model_validate(envelope())
    assert view.bundle == example_bundle() and view.receipt is not None and view.receipt.bundle_digest == pins(example_bundle())["bundleDigest"]
    assert view.manifest == manifest_of(example_bundle())
    assert not {"attempts", "next", "failure", "sources", "files", "counts", "exclusionCodes", "checks", "frozenAt"} & set(view.model_dump(by_alias=True))
    assert not {"sources", "files", "counts", "frozenAt", "provenance"} & set(view.receipt.model_dump(by_alias=True))


@pytest.mark.parametrize("mutate", [
    lambda out: out.pop("usage"), lambda out: out["usage"].update(providerCalls=1), lambda out: out["usage"].update(modelCalls=True),
    lambda out: out["delivery"].update(status="maybe"), lambda out: out.update(state="published"), lambda out: out.update(publication="published"),
    lambda out: out["delivery"].update(checkedAt="yesterday"), lambda out: out["receipt"].update(bundleDigest="short"),
    lambda out: out["receipt"].update(bundleSchema="zoop-graph-handoff-bundle-1"), lambda out: out["receipt"].update(bundleSchema="zoop-graph-handoff-bundle-2"),
    lambda out: out["receipt"].update(bundleSchema="zoop-graph-handoff-bundle-3"), lambda out: out["receipt"].update(bundleSchema="zoop-graph-handoff-bundle-4"),
    lambda out: out["receipt"].update(bundleSchema="zoop-graph-handoff-bundle-5"), lambda out: out["receipt"].update(bundleSchema="zoop-graph-handoff-bundle-6"),
    lambda out: out["receipt"].update(bundleBytes=0), lambda out: out["receipt"].update(bundleSchema="other"), lambda out: out.update(bundle=[]),
    lambda out: out.update(manifest=[]),
])
def test_the_envelope_projection_fails_closed_on_a_missing_or_mistyped_field(mutate):
    out = envelope()
    mutate(out)
    with pytest.raises(ValidationError):
        Export.model_validate(out)


# ---- delivery, with a scripted process ---------------------------------------------------------------------------------------

def result(out: dict, code: int = 0) -> Outcome:
    return Outcome("result", result=out, exit_code=code)


def refusal(code: str, detail: dict | None = None) -> Outcome:
    return Outcome("error", result=error_output(code, detail), code=code, exit_code=2)


class Scripted:
    """The process object of `HandoffReads`: answers what the test queued and records what it was asked."""

    def __init__(self, *outcomes: Outcome, on_call: Callable[[], None] | None = None):
        self.outcomes, self.calls, self.on_call = list(outcomes), [], on_call

    def export(self, handoff_id: str) -> Outcome:
        self.calls.append(handoff_id)
        if self.on_call:
            self.on_call()
        return self.outcomes.pop(0)


def reads(tmp_path: Path, *outcomes: Outcome, gate: RelationGate | None = None, exports: list[dict] | None = None, busy_wait: float = 0.05,
          on_call: Callable[[], None] | None = None) -> tuple[HandoffReads, Scripted, HandoffWorkspace]:
    ws = HandoffWorkspace(tmp_path, exports=exports)
    process = Scripted(*outcomes, on_call=on_call)
    return HandoffReads(load(ws.env()), process, gate, busy_wait=busy_wait), process, ws


def body(reply) -> dict:
    assert reply.status == 200
    return reply.body.wire()


def refusal_of(call: Callable[[], Any]) -> HandoffError:
    with pytest.raises(HandoffError) as caught:
        call()
    return caught.value


def test_a_current_status_and_bundle_carry_identity_digests_and_the_bundle_only_on_its_own_route(tmp_path):
    service, process, _ = reads(tmp_path, result(envelope()), result(envelope()))
    status = body(service.status(PRINCIPAL, HANDOFF, Observation()))
    full = body(service.bundle(PRINCIPAL, HANDOFF, Observation()))
    bundle, fixed = example_bundle(), pins(example_bundle())
    assert status["schemaVersion"] == "zoop-ai-internal-handoff-1" and (status["publication"], status["appImport"]) == ("not-published", "pending")
    assert status["delivery"] == {"state": "current", "reason": None, "checkedAt": "2026-10-16T03:00:00.123456+00:00"}
    assert status["verification"] == {**fixed, "counts": bundle["counts"], "sources": 1, "provenance": bundle["provenance"]} and "bundle" not in status
    assert "manifest" not in status
    assert {key: value for key, value in full.items() if key not in ("manifest", "bundle", "observedAt")} == {key: value for key, value in status.items() if key != "observedAt"}
    assert full["bundle"] == bundle and full["manifest"] == manifest_of(bundle) and process.calls == [HANDOFF, HANDOFF]
    assert hashlib.sha256(canonical(full["manifest"]).encode()).hexdigest() == fixed["manifestDigest"] == bundle["manifestDigest"]
    assert hashlib.sha256(canonical(full["bundle"]).encode()).hexdigest() == fixed["bundleDigest"]
    assert json.loads(json.dumps(full)) == full


def test_every_withheld_shape_has_identity_state_and_a_reason_and_nothing_of_the_bundle(tmp_path):
    outcomes = [result(withheld_output(code="source_unauthorized"), 2), refusal("handoff_not_ready", {"state": "reserved"}), result(envelope())]
    service, _, ws = reads(tmp_path, *outcomes, *outcomes, exports=[export_entry(bundleDigest="0" * 64)])
    for _ in range(2):
        for operation in (service.status, service.bundle):
            wire = body(operation(PRINCIPAL, HANDOFF, Observation()))
            assert wire["verification"] is None and wire.get("bundle") is None and wire.get("manifest") is None and wire["delivery"]["state"] == "withheld"
            assert wire["delivery"]["reason"] in {"source_unauthorized", "handoff_not_ready", "handoff_pin_mismatch"}
            text = json.dumps(wire)
            for private in (*SOURCE_DATA, "KRX:005930", "ev-", pins(example_bundle())["bundleDigest"]):
                assert private not in text


def test_a_handoff_frozen_under_the_earlier_bundle_schema_is_withheld_with_its_reason_and_no_receipt_content(tmp_path):
    legacy = withheld_output(code="handoff_contract_changed")
    service, _, _ = reads(tmp_path, result(legacy, 2), result(legacy, 2))
    for operation in (service.status, service.bundle):
        wire = body(operation(PRINCIPAL, HANDOFF, Observation()))
        assert wire["delivery"] == {"state": "withheld", "reason": "handoff_contract_changed", "checkedAt": None}
        assert wire["verification"] is None and wire.get("bundle") is None and wire.get("manifest") is None
        text = json.dumps(wire)
        for old in ("zoop-graph-handoff-bundle-1", "zoop-graph-handoff-bundle-2", "zoop-graph-handoff-bundle-3", "zoop-graph-handoff-bundle-4", "zoop-graph-handoff-bundle-5",
                    "zoop-graph-handoff-bundle-6", "bundleSchema", "receipt", "summary", pins(example_bundle())["bundleDigest"]):
            assert old not in text


@pytest.mark.parametrize("code,status,public", [
    ("handoff_busy", 503, "runtime_busy"), ("ingestion_busy", 503, "runtime_busy"), ("handoff_recovery_required", 503, "service_configuration_invalid"),
    ("handoff_artifact_invalid", 503, "service_configuration_invalid"), ("operator_file_pin_mismatch", 503, "service_configuration_invalid"),
    ("analysis_contract_changed", 503, "service_configuration_invalid"),
    ("handoff_not_found", 404, "handoff_not_found"), ("never_seen_before", 500, "internal_error")])
def test_producer_refusals_map_to_stable_codes_and_never_to_an_empty_bundle(tmp_path, code, status, public):
    service, _, _ = reads(tmp_path, refusal(code, {"path": "/private"}))
    error = refusal_of(lambda: service.bundle(PRINCIPAL, HANDOFF, Observation()))
    assert (error.status, error.code) == (status, public)
    envelope_ = error.envelope("req-1").wire()
    assert "/private" not in json.dumps(envelope_) and set(envelope_["error"]) == {"code", "retryable", "requestId", "runtimeCode", "field"}


def test_a_listed_handoff_whose_state_is_not_withholdable_is_unavailable_not_withheld(tmp_path):
    for outcome in (refusal("handoff_not_ready", {"state": "ready"}), refusal("handoff_not_ready"), Outcome("timeout"), Outcome("abnormal", exit_code=1),
                    Outcome("unavailable")):
        service, _, _ = reads(tmp_path / str(id(outcome)), outcome)
        error = refusal_of(lambda: service.status(PRINCIPAL, HANDOFF, Observation()))
        assert (error.status, error.code, error.headers["Retry-After"]) == (503, "runtime_unavailable", "2")


def test_the_pins_the_digests_of_the_received_bytes_and_the_receipt_must_all_agree(tmp_path):
    service, _, _ = reads(tmp_path / "a", result(envelope()), exports=[export_entry(manifestDigest="1" * 64)])
    assert body(service.bundle(PRINCIPAL, HANDOFF, Observation()))["delivery"]["reason"] == "handoff_pin_mismatch"
    for index, receipt in enumerate(({"bundleDigest": "1" * 64}, {"contentDigest": "2" * 64}, {"manifestDigest": "3" * 64}, {"bundleBytes": 7})):
        service, _, _ = reads(tmp_path / f"b{index}", result(envelope(receipt=receipt)))
        error = refusal_of(lambda: service.bundle(PRINCIPAL, HANDOFF, Observation()))
        assert (error.status, error.code) == (500, "runtime_binding_mismatch"), receipt
    service, _, _ = reads(tmp_path / "c", result(envelope(handoff_id=OTHER_HANDOFF)))
    assert refusal_of(lambda: service.status(PRINCIPAL, HANDOFF, Observation())).code == "runtime_binding_mismatch"


def test_a_self_consistent_bundle_with_an_unknown_nested_field_is_refused_and_a_status_does_not_trust_its_counts(tmp_path):
    bundle = mutated(lambda b: b["counts"]["relations"].update(SHARES_ISSUE=1))
    for index, operation in enumerate(("status", "bundle")):
        service, _, _ = reads(tmp_path / operation, result(envelope(bundle)), exports=[export_entry(bundle=bundle)])
        error = refusal_of(lambda: getattr(service, operation)(PRINCIPAL, HANDOFF, Observation()))
        assert (error.status, error.code) == (500, "runtime_contract_mismatch") and error.code not in {"runtime_unavailable"}, index


def test_a_model_that_would_normalise_anything_is_refused_not_delivered(tmp_path, monkeypatch):
    """The relayed bytes must equal the hashed bytes: if a model ever dumped something else, the digest could no longer match the pin."""
    service, _, _ = reads(tmp_path, result(envelope()))
    real = Bundle.wire

    def altered(self):
        out = real(self)
        out["articles"][0]["publishedAt"] = out["articles"][0]["publishedAt"].replace("+00:00", "Z")
        return out

    monkeypatch.setattr(Bundle, "wire", altered)
    error = refusal_of(lambda: service.bundle(PRINCIPAL, HANDOFF, Observation()))
    assert (error.status, error.code) == (500, "runtime_contract_mismatch")


def test_the_allowlist_is_checked_before_the_child_after_the_wait_and_again_after_the_answer(tmp_path):
    ws = HandoffWorkspace(tmp_path / "ordering")
    seen_calls: list[str] = []

    def revoke() -> None:
        seen_calls.append("child")
        ws.write_exports([])

    process = Scripted(result(envelope()), on_call=revoke)
    service = HandoffReads(load(ws.env()), process, None)
    error = refusal_of(lambda: service.bundle(PRINCIPAL, HANDOFF, Observation()))
    assert (error.status, error.code) == (403, "handoff_not_allowed") and seen_calls == ["child"]   # revoked while the child ran: nothing of its answer
    other = refusal_of(lambda: service.bundle("alpha", HANDOFF, Observation()))
    assert other.code == "handoff_not_allowed" and process.calls == [HANDOFF]                       # unlisted: no second child at all
    unknown = refusal_of(lambda: service.status(PRINCIPAL, "never-existed", Observation()))
    assert unknown.code == "handoff_not_allowed" and process.calls == [HANDOFF]


def test_the_slot_limit_and_the_shared_gate_answer_busy_and_never_start_a_child(tmp_path):
    gate = RelationGate()
    service, process, _ = reads(tmp_path / "gated", result(envelope()), gate=gate)
    assert gate.acquire(0)   # an S2/S3 child of this process holds the gate
    error = refusal_of(lambda: service.status(PRINCIPAL, HANDOFF, Observation()))
    assert (error.status, error.code, error.headers["Retry-After"]) == (503, "runtime_busy", "2") and process.calls == []
    gate.release()
    assert body(service.status(PRINCIPAL, HANDOFF, Observation()))["delivery"]["state"] == "current"
    service, process, _ = reads(tmp_path / "slots", result(envelope()))
    taken = [service._slots.acquire(blocking=False) for _ in range(2)]
    assert all(taken)
    error = refusal_of(lambda: service.status(PRINCIPAL, HANDOFF, Observation()))
    assert (error.status, error.code) == (503, "service_busy") and process.calls == []
    for _ in taken:
        service._slots.release()


def test_handoff_errors_use_their_own_envelope_without_a_message(tmp_path):
    wire = HandoffError(404, "handoff_not_found", runtime_code="handoff_not_found").envelope("req-1").wire()
    assert wire == {"schemaVersion": "zoop-ai-internal-handoff-1", "error": {"code": "handoff_not_found", "retryable": False, "requestId": "req-1",
                                                                             "runtimeCode": "handoff_not_found", "field": None}}
    assert "message" not in HdErrorEnvelope.model_json_schema()["$defs"]["ErrorBody"]["properties"]
    assert HandoffError(503, "runtime_busy").envelope("r").error.retryable is True and HandoffError(500, "runtime_contract_mismatch").envelope("r").error.retryable is False


# ---- generated examples ------------------------------------------------------------------------------------------------------

def test_every_authored_handoff_example_validates_through_the_wire_models_and_withheld_ones_carry_no_content():
    sample = examples()
    for example in sample["status"].values():
        HdStatus.model_validate(example["value"])
    for name, example in sample["bundle"].items():
        wire = HdBundle.model_validate(example["value"]).wire()
        assert wire == example["value"]
        if name == "withheld":
            assert wire["bundle"] is None and wire["verification"] is None and wire["manifest"] is None
        else:
            assert canonical(wire["bundle"]) == canonical(example_bundle("temporal-review-pending" if name == "currentSummaryHeld" else "available"))
            assert hashlib.sha256(canonical(wire["bundle"]).encode()).hexdigest() == wire["verification"]["bundleDigest"]
            assert hashlib.sha256(canonical(wire["manifest"]).encode()).hexdigest() == wire["verification"]["manifestDigest"] == wire["bundle"]["manifestDigest"]
    for example in sample["errors"].values():
        HdErrorEnvelope.model_validate(example["value"])
    assert seal(copy.deepcopy(example_bundle())) == example_bundle()   # the authored content digest is a real digest of the authored content


# ---- live provenance, the approval basis and source support ---------------------------------------------------------------------

ORIGIN = {"originId": "origin-1", "reviewer": "reviewer-1", "decisionRef": "origin-2026-10-21:1", "decisionVersion": "v1", "verification": "operator-declared-origin"}


def test_the_provenance_pairs_the_approval_basis_and_the_source_support_are_closed_and_exact():
    bundle = example_bundle()
    live = live_bundle()      # a LIVE export carries provider and independent-verifier summary identities (a replay summary can never sit in a live bundle)
    assert Bundle.model_validate(live).wire() == live
    manual = copy.deepcopy(bundle)
    manual["sources"][0]["reviewUsed"][0]["approvalBasis"] = {"kind": "operator-final-approval", "revision": 1, "reviewer": "ops-1",
                                                              "decidedAt": "2026-10-13T00:00:02+00:00"}
    manual["relations"][0]["provenance"]["s3SemanticValidation"] = "manual-operator-final-approval"   # the INVOLVES edge says whose approval it rests on
    manual["impacts"][0].update(impactCandidateId=None, status="not-applicable", code=None, label=None, targetVerdict=None, effects=None, verifier="not-called",
                                verifierRequestDigest=None, proposal=None)       # an operator-final-approval source has no impact candidate (contract: not-applicable, all null)
    manual["sources"][0]["audit"]["impactCandidates"] = 0
    assert Bundle.model_validate(manual).wire() == manual
    declared = copy.deepcopy(bundle)
    declared["articles"][0]["origin"] = dict(ORIGIN)
    declared["issues"][0]["sourceSupport"].update(knownLineageCount=1, unknownLineageArticles=[], independentSourceCount=1)
    assert Bundle.model_validate(declared).wire() == declared
    used = lambda b: b["sources"][0]["reviewUsed"][0]  # noqa: E731
    for change in (lambda b: b["provenance"].update(executionMode="live"), lambda b: b["provenance"].update(recordingKind="provider"),
                   lambda b: b["sources"][0]["provenance"].update(executionMode="live"), lambda b: b["sources"][0].pop("provenance"),
                   lambda b: used(b)["approvalBasis"].update(revision=9), lambda b: used(b)["approvalBasis"].update(reviewer="operator"),
                   lambda b: used(b)["approvalBasis"].update(kind="operator-final-approval"), lambda b: used(b)["approvalBasis"].update(kind="operator-review"),
                   lambda b: used(b).update(extra=1), lambda b: used(b).pop("approvalBasis"), lambda b: b["sources"][0].update(reviewUsed=[["rc-" + "4" * 64, 1]]),
                   lambda b: b["policy"].update(sourceSupport="other"), lambda b: b["policy"].pop("sourceSupport"),
                   lambda b: b["articles"][0].pop("textSha256"), lambda b: b["articles"][0].update(textSha256="short"),
                   lambda b: b["articles"][0].update(origin={"originId": "o"}), lambda b: b["articles"][0].update(origin={**ORIGIN, "verification": "inferred"}),
                   lambda b: b["issues"][0].pop("sourceSupport"), lambda b: b["issues"][0]["sourceSupport"].update(extra=1),
                   lambda b: b["issues"][0]["sourceSupport"].update(duplicateGroups=[["doc-" + "c" * 64]]),      # a group has two members at least
                   lambda b: b["issues"][0]["sourceSupport"].update(independentSourceCount=-1),
                   lambda b: b["relations"][0]["provenance"].update(s3SemanticValidation="none")):
        broken = copy.deepcopy(bundle)
        change(broken)
        with pytest.raises(ValidationError):
            Bundle.model_validate(broken)


REVIEWERS = ("ops@example.invalid", "검수자 김서진", "alpha", "Reviewer With Spaces & Punctuation!", "x" * 200, "é")


@pytest.mark.parametrize("reviewer", REVIEWERS)
def test_a_bounded_free_text_reviewer_is_relayed_exactly_by_the_handoff_and_the_relation_projection(reviewer):
    """The producer (`handoff_contracts`) and the S3 review wire accept any non-blank reviewer of at most 200 characters, so neither service model may
    redact it, reject it as an identifier pattern, or normalise it."""
    from zoop_ai_service.handoff_wire import BApprovalBasis
    from zoop_ai_service.relation_wire import RcApprovalBasis
    wire = {"kind": "operator-final-approval", "revision": 2, "reviewer": reviewer, "decidedAt": "2026-10-20T00:00:00+00:00"}
    assert BApprovalBasis.model_validate(wire).model_dump(by_alias=True)["reviewer"] == reviewer
    assert RcApprovalBasis.model_validate({**wire}).model_dump(by_alias=True)["reviewer"] == reviewer


@pytest.mark.parametrize("reviewer", ("", "   ", "\t\n", "x" * 201))
def test_a_blank_or_over_long_reviewer_is_refused_and_the_automatic_verifier_has_none(reviewer):
    from zoop_ai_service.handoff_wire import BApprovalBasis
    from zoop_ai_service.relation_wire import RcApprovalBasis
    wire = {"kind": "operator-final-approval", "revision": 2, "reviewer": reviewer, "decidedAt": "2026-10-20T00:00:00+00:00"}
    for model in (BApprovalBasis, RcApprovalBasis):
        with pytest.raises(ValidationError):
            model.model_validate(wire)
    automatic = {"kind": "automatic-verifier", "revision": 1, "reviewer": None, "decidedAt": "2026-10-20T00:00:00+00:00"}
    assert BApprovalBasis.model_validate(automatic).reviewer is None and RcApprovalBasis.model_validate(automatic).reviewer is None
    with pytest.raises(ValidationError):
        BApprovalBasis.model_validate({**automatic, "reviewer": "someone"})   # a verifier verdict has no human reviewer
