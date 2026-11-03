"""Refusal-class mapping of the synchronous observation read, against a scripted child outcome."""
from __future__ import annotations

import copy

import pytest

from zoop_ai_service.jobs import ApiError, Observation
from zoop_ai_service.observation_reads import ObservationReads
from zoop_ai_service.observation_wire import ObservationExport, ObservationExportRequest, digest
from zoop_ai_service.runtime import Outcome

TEXT = "합성 본문입니다."
MAPPING, RAW = "a" * 64, "b" * 64
PROFILE = {"parser": "p", "lxml": "1", "pypdf": "1", "mappingVersion": "m", "htmlDecoding": "d", "htmlScope": "s", "pdfExtraction": "x",
           "articleXPath": None}
SOURCE_HASH = digest(TEXT)
VERSION = digest(["doc-1", RAW, PROFILE, "exact-copy-1", SOURCE_HASH, MAPPING])
RUN = {"start": 0, "end": len(TEXT)}
LOCATOR = "loc-" + digest([VERSION, RUN, MAPPING])
SELECTOR = {"schemaVersion": "zoop-ingestion-s2-1", "roundId": "round-1", "sourceId": "src", "page": 0, "ordinal": 0,
            "documentId": "doc-1", "rawVersion": RAW, "documentVersion": VERSION}
EXPORT = {
    "schemaVersion": "zoop-ingestion-s2-1",
    "observation": {"roundId": "round-1", "sourceId": "src", "page": 0, "ordinal": 0, "pageId": "page-0", "observedAt": "2026-10-29T00:00:00Z",
                    "documentId": "doc-1", "rawVersion": RAW, "documentVersion": VERSION, "url": "https://example.invalid/a", "title": "t",
                    "publishedAt": None, "modifiedAt": None, "sourceRevision": None, "mediaType": "text/html"},
    "grant": {"grantId": "g", "revision": "1"},
    "document": {"documentId": "doc-1", "documentVersion": VERSION, "sourceId": "src", "textArtifactId": "text-" + VERSION, "inputKind": "body",
                 "cleanerVersion": "exact-copy-1", "text": TEXT, "sourceHash": SOURCE_HASH,
                 "rawLocators": [{"locatorId": LOCATOR, "start": 0, "end": len(TEXT)}]},
    "locatorMetadata": {"rawArtifactId": "raw-" + RAW, "rawHash": RAW, "rawVersion": RAW, "representationHash": "c" * 64,
                        "mappingHash": MAPPING, "parserProfile": PROFILE, "limitations": []},
}


class Scripted:
    def __init__(self, outcome: Outcome):
        self.outcome, self.calls = outcome, []

    def export(self, request):
        self.calls.append(request.wire())
        return self.outcome


def read(outcome: Outcome):
    process = Scripted(outcome)
    seen = Observation()
    return ObservationReads(process).export(ObservationExportRequest.model_validate(SELECTOR), seen), process, seen


def refused(outcome: Outcome) -> ApiError:
    with pytest.raises(ApiError) as caught:
        read(outcome)
    return caught.value


def test_fixture_is_a_valid_native_export():
    assert ObservationExport.model_validate(EXPORT).wire() == EXPORT


def test_success_returns_canonical_native_bytes_once_per_request():
    raw, process, seen = read(Outcome("result", result=EXPORT, exit_code=0))
    assert raw.endswith(b"\n") and TEXT.encode() in raw
    assert process.calls == [SELECTOR] and seen.runtime == [{"command": "export", "kind": "result", "exit": 0}]


@pytest.mark.parametrize("code,status,error,runtime", [
    ("source_unauthorized", 403, "source_unauthorized", None),
    ("round_not_found", 404, "round_not_found", None),
    ("observation_not_found", 404, "observation_not_found", None),
    ("document_version_not_in_round", 404, "document_version_not_in_round", None),
    ("registry_changed", 409, "registry_changed", None),
    ("scope_configuration_conflict", 409, "scope_configuration_conflict", None),
    ("preparation_profile_unbound", 409, "preparation_profile_unbound", None),
    ("ingestion_busy", 503, "runtime_busy", "ingestion_busy"),
    ("ingestion_recovery_required", 503, "service_configuration_invalid", "ingestion_recovery_required"),
])
def test_native_error_codes_map_to_distinct_safe_refusals(code, status, error, runtime):
    caught = refused(Outcome("error", code=code, exit_code=2))
    assert (caught.status, caught.code, caught.runtime_code) == (status, error, runtime)


@pytest.mark.parametrize("outcome", [Outcome("contract", exit_code=0), Outcome("abnormal", exit_code=-9), Outcome("timeout")])
def test_unusable_child_output_never_relays_content(outcome):
    caught = refused(outcome)
    assert caught.status in (500, 503) and TEXT not in repr(vars(caught))


def test_changed_selector_binding_or_corrupt_export_is_a_contract_failure():
    moved = copy.deepcopy(EXPORT)
    moved["observation"]["ordinal"] = 1
    assert refused(Outcome("result", result=moved, exit_code=0)).code == "runtime_binding_mismatch"
    corrupt = copy.deepcopy(EXPORT)
    corrupt["document"]["sourceHash"] = "0" * 64
    assert refused(Outcome("result", result=corrupt, exit_code=0)).code == "runtime_contract_mismatch"
    extra = copy.deepcopy(EXPORT)
    extra["observation"]["observationId"] = "invented"
    assert refused(Outcome("result", result=extra, exit_code=0)).code == "runtime_contract_mismatch"


def test_a_third_concurrent_export_is_service_busy_without_starting_a_child():
    reads = ObservationReads(Scripted(Outcome("result", result=EXPORT, exit_code=0)))
    assert reads._slots.acquire(blocking=False) and reads._slots.acquire(blocking=False)
    with pytest.raises(ApiError) as caught:
        reads.export(ObservationExportRequest.model_validate(SELECTOR), Observation())
    assert (caught.value.status, caught.value.code) == (503, "service_busy") and reads.process.calls == []


def projected_export(profile):
    value = copy.deepcopy(EXPORT)
    descriptor = {"profile": profile, "descriptorHash": "d" * 64}
    metadata = value["locatorMetadata"]
    metadata["parserProfile"]["textProjection"] = descriptor
    projection = {**descriptor, "parentDocumentVersion": VERSION,
                  "boundaryDecisionRevision": "approved-1", "rightsReceiptHash": "e" * 64}
    if profile == "korea-kogl1-caption-boundary-1":
        projection["excludedSourceSlots"] = [{"domPath": "/html/body/article/figure/figcaption", "slot": "text"}]
    else:
        value["observation"]["mediaType"] = "application/pdf"
        ranges = [{"pageNumber": 1, "pageTextHash": "f" * 64, "sourceStart": 0, "sourceEnd": len(TEXT),
                   "textUtf8Sha256": "1" * 64, "reviewUnitId": "body-1"}]
        projection.update(parentDocumentId="doc-1", parentRawVersion=RAW, selectionHash=digest(ranges),
                          retainedSourceRanges=ranges)
        metadata.update(pageCount=1, emptyPageCount=0)
    metadata["textProjection"] = projection
    version = digest(["doc-1", RAW, metadata["parserProfile"], "exact-copy-1", SOURCE_HASH, MAPPING])
    value["observation"]["documentVersion"] = value["document"]["documentVersion"] = version
    value["document"]["textArtifactId"] = "text-" + version
    value["document"]["rawLocators"][0]["locatorId"] = "loc-" + digest([version, RUN, MAPPING])
    return value


@pytest.mark.parametrize("profile", ["korea-kogl1-caption-boundary-1", "eu-commission-pdf-body-ranges-1"])
def test_projected_native_export_preserves_exact_metadata_and_unicode(profile):
    value = projected_export(profile)
    selector = {key: value["observation"][key] for key in SELECTOR if key != "schemaVersion"}
    request = ObservationExportRequest.model_validate({"schemaVersion": SELECTOR["schemaVersion"], **selector})
    raw = ObservationReads(Scripted(Outcome("result", result=value, exit_code=0))).export(request, Observation())
    from zoop_ai_service.handoff_runtime import canonical
    assert raw == (canonical(value) + "\n").encode("utf-8")


@pytest.mark.parametrize("profile", ["korea-kogl1-caption-boundary-1", "eu-commission-pdf-body-ranges-1"])
@pytest.mark.parametrize("fault", ["extra", "private-receipt", "hash", "profile", "missing", "null", "descriptor", "identity"])
def test_projected_metadata_contract_failures_are_refused(profile, fault):
    value = projected_export(profile)
    metadata = value["locatorMetadata"]
    projection = metadata["textProjection"]
    if fault == "extra":
        projection["unexpected"] = "untrusted"
    elif fault == "private-receipt":
        projection["rightsReceipt"] = {"path": "/private/receipt.json", "content": "private"}
    elif fault == "hash":
        projection["rightsReceiptHash"] = "not-a-hash"
    elif fault == "profile":
        projection["profile"] = "unknown-profile"
    elif fault == "missing":
        del metadata["textProjection"]
    elif fault == "null":
        metadata["textProjection"] = None
    elif fault == "descriptor":
        projection["descriptorHash"] = "0" * 64
    else:
        value["document"]["documentVersion"] = "0" * 64
    assert refused(Outcome("result", result=value, exit_code=0)).code == "runtime_contract_mismatch"


@pytest.mark.parametrize("fault", ["extra", "page", "hash", "bounds", "order", "selection", "parent", "slot"])
def test_projected_source_boundaries_are_strict(fault):
    profile = "korea-kogl1-caption-boundary-1" if fault == "slot" else "eu-commission-pdf-body-ranges-1"
    value = projected_export(profile)
    projection = value["locatorMetadata"]["textProjection"]
    if fault == "slot":
        projection["excludedSourceSlots"][0]["slot"] = "attribute"
    elif fault == "parent":
        projection["parentRawVersion"] = "0" * 64
    elif fault == "selection":
        projection["selectionHash"] = "0" * 64
    else:
        span = projection["retainedSourceRanges"][0]
        if fault == "extra":
            span["text"] = TEXT
        elif fault == "page":
            span["pageNumber"] = 0
        elif fault == "hash":
            span["pageTextHash"] = "BAD"
        elif fault == "bounds":
            span["sourceEnd"] = span["sourceStart"]
        else:
            projection["retainedSourceRanges"].append(copy.deepcopy(span))
    assert refused(Outcome("result", result=value, exit_code=0)).code == "runtime_contract_mismatch"
