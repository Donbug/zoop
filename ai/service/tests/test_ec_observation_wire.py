"""EC body exports bind the original response and closed representation/DOM selection."""
from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from test_observation_reads import EXPORT, PROFILE, RAW, SOURCE_HASH, TEXT, MAPPING, RUN
from zoop_ai_service.observation_wire import ObservationExport, digest


def body_export(json_member=True):
    value = copy.deepcopy(EXPORT)
    media = "application/json" if json_member else "text/html"
    profile = "eu-commission-json-html-body-ranges-1" if json_member else "eu-commission-html-body-ranges-1"
    metadata = value["locatorMetadata"]
    baseline = {**PROFILE, "articleXPath": "/html/body"}
    representation = {"sourceHash": SOURCE_HASH, "representationHash": "c" * 64, "mappingHash": MAPPING,
                      "parserProfile": baseline}
    if json_member:
        representation.update(decoder="ec-presscorner-json-html-1", jsonPointer="/docuLanguageResource/htmlContent",
                              decodedHtmlUtf8Sha256="e" * 64, expectedReference="IP/SYNTHETIC", expectedLanguage="EN")
    parent = {"documentId": "doc-1", "rawVersion": RAW, "rawHash": metadata["rawHash"], "collectionReceiptSha256": "f" * 64}
    units = [{"unitId": "p1", "domPath": "/html/body/p", "classification": "commission-narrative",
              "spans": [{"domPath": "/html/body/p", "slot": "text", "sourceStart": 0, "sourceEnd": len(TEXT),
                         "textUtf8Sha256": "1" * 64}], "textUtf8Sha256": "1" * 64}]
    descriptor = {"profile": profile, "descriptorHash": "d" * 64}
    metadata["parserProfile"] = {**baseline, "textProjection": descriptor}
    metadata["textProjection"] = {**descriptor, "parent": parent, "representation": representation,
        "parentBindingHash": digest({"parent": parent, "representation": representation}), "selectionHash": digest(units),
        "boundaryDecisionRevision": "review-1", "rightsReceiptHash": "2" * 64, "retainedUnits": units}
    value["observation"].update(mediaType=media, provenance="collected_http", collection={
        "provenance": "collected_http", "collectionId": "synthetic", "receipt": {"file": "receipt.json", "sha256": "f" * 64},
        "fetchedAt": "2026-10-08T00:00:00+00:00", "finalUrl": "https://example.invalid/a", "httpStatus": 200,
        "contentType": media, "bodySha256": metadata["rawHash"], "documentKind": "news", "network": "synthetic_loopback",
        "published": {"raw": None, "precision": "unknown", "date": None, "basis": "synthetic"}})
    version = digest(["doc-1", RAW, metadata["parserProfile"], "exact-copy-1", SOURCE_HASH, MAPPING])
    value["observation"]["documentVersion"] = value["document"]["documentVersion"] = version
    value["document"]["textArtifactId"] = "text-" + version
    value["document"]["rawLocators"][0]["locatorId"] = "loc-" + digest([version, RUN, MAPPING])
    return value


@pytest.mark.parametrize("json_member", [True, False])
def test_closed_body_projection_round_trips_exactly(json_member):
    value = body_export(json_member)
    assert ObservationExport.model_validate(value).wire() == value


@pytest.mark.parametrize("fault", ["extra", "pointer", "raw", "receipt", "selection", "binding", "media", "profile"])
def test_body_projection_rejects_broken_raw_to_dom_chain(fault):
    value = body_export()
    projection = value["locatorMetadata"]["textProjection"]
    if fault == "extra":
        projection["representation"]["untyped"] = True
    elif fault == "pointer":
        projection["representation"]["jsonPointer"] = "/other"
    elif fault in {"raw", "receipt"}:
        projection["parent"]["rawHash" if fault == "raw" else "collectionReceiptSha256"] = "0" * 64
    elif fault in {"selection", "binding"}:
        projection["selectionHash" if fault == "selection" else "parentBindingHash"] = "0" * 64
    elif fault == "media":
        value["observation"]["mediaType"] = "text/html"
    else:
        projection["profile"] = "eu-commission-html-body-ranges-1"
    with pytest.raises(ValidationError):
        ObservationExport.model_validate(value)
