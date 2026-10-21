"""The original-mention `eventTime` grammar of the handoff bundle, shared with the app by ONE vector file, and its effect on the PUBLIC bundle validator.

`api/src/test/resources/graph-handoff/mention-time-vectors.json` is read by this test and by the app's `HandoffMentionTimeTest`, so the producer's
`mention_time_precision` and the app's `HandoffTime.mentionEventTime` accept and refuse exactly the same strings. The vectors are hand-written; nothing is
derived from the code under test. The grammar is the set both sides already accepted (raw strings are kept verbatim); only forms the app refuses for the whole
bundle although Python's stdlib takes them (ISO week dates, compact forms, comma fractions, offsets without a colon) are unsupported, so the producer excludes
the issue (`mention_event_time_unsupported`) instead of freezing a bundle the app can never import.
"""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from zoop_ai_pipeline.extraction_contracts import ExtractionFailure
from zoop_ai_pipeline.handoff_contracts import content_digest, mention_time_precision, validate_bundle

RESOURCES = Path(__file__).resolve().parents[3] / "api" / "src" / "test" / "resources" / "graph-handoff"
DOC = json.loads((RESOURCES / "mention-time-vectors.json").read_text("utf-8"))
EXPORT = json.loads((RESOURCES / "export-valid.json").read_text("utf-8"))["bundle"]
PRECISIONS = ("unknown", "year", "month", "day", "datetime")


def test_the_vector_file_is_the_one_this_test_expects():
    assert DOC["schemaVersion"] == "zoop-mention-time-vectors-1"
    assert len(DOC["accept"]) >= 20 and len(DOC["reject"]) >= 50
    assert {item["precision"] for item in DOC["accept"]} == set(PRECISIONS)


@pytest.mark.parametrize("item", DOC["accept"], ids=lambda item: repr(item["value"]))
def test_a_calendar_form_of_the_grammar_is_classified_by_its_format(item):
    assert mention_time_precision(item["value"]) == item["precision"]


@pytest.mark.parametrize("item", DOC["reject"], ids=lambda item: item["why"])
def test_everything_else_is_unsupported_and_never_rewritten(item):
    with pytest.raises(ValueError):
        mention_time_precision(item["value"])


def test_the_stdlib_forms_the_app_refuses_are_the_reason_for_the_grammar():
    """`date.fromisoformat` takes a 10-character ISO week date; the old classifier therefore called `2026-W40-3` a `day`, which the app refuses for the whole bundle."""
    assert date.fromisoformat("2026-W40-3") == date(2026, 9, 30)
    with pytest.raises(ValueError):
        mention_time_precision("2026-W40-3")


def test_a_non_string_is_not_a_time():
    for value in (5, 2026, True, b"2026", ["2026"]):
        with pytest.raises(ValueError):
            mention_time_precision(value)


# ---- the public validator (`validate_bundle`) over the producer's real export ---------------------------------------------------------------

def sealed(value, precision) -> dict:
    """A copy of the real export whose supply issue's NON-representative mention (`m-a2`) carries this time, with the content digest recomputed so only the targeted rule
    can refuse it. The issue keeps the representative's time `2026-09-30`, so by hand: `m-a2` stays listed as stating the issue's eventTime only when it carries exactly
    that string, and is otherwise dropped from that one list (field provenance is exact equality, never a normalised time)."""
    bundle = copy.deepcopy(EXPORT)
    supply = next(issue for issue in bundle["issues"] if issue["id"] == "issue:supply-2026q3")
    mention = next(m for m in supply["mentions"] if m["mentionId"] == "m-a2")
    mention["eventTime"], mention["timePrecision"] = value, precision
    if value != supply["eventTime"]:
        listed = supply["fieldProvenance"]["sameValueMentions"]
        listed["eventTime"] = [ref for ref in listed["eventTime"] if ref["mentionId"] != "m-a2"]
    bundle["digests"]["content"] = content_digest(bundle)
    return bundle


def test_the_real_export_validates_and_so_do_valid_mention_times_it_did_not_carry():
    validate_bundle(EXPORT)
    for value, precision in (("2026-09", "month"), ("2026", "year"), (None, "unknown"), ("2026-09-30T09:00Z", "datetime"),
                             ("2026-09-30T09:00:00.1234567+09:00", "datetime"), ("2026-09-30T09:00:00-00:00", "datetime")):
        validate_bundle(sealed(value, precision))


@pytest.mark.parametrize("value,precision", [("2026-W40-3", "day"), ("2026-W40-3", "unknown"), ("20260930T090000Z", "datetime"),
                                             ("2026-09-30T09:00:00+0900", "datetime"), ("2026-09-30T09:00:00,5Z", "datetime"),
                                             ("2026-09-30T09:00:00z", "datetime"), ("2026-02-30", "day")])
def test_the_public_validator_refuses_a_mention_time_the_app_would_refuse_instead_of_freezing_it(value, precision):
    """`2026-W40-3` was classified `day` by the old validator (a week date is a valid `date.fromisoformat` input), so a bundle the app cannot import was valid."""
    with pytest.raises(ExtractionFailure) as refused:
        validate_bundle(sealed(value, precision))
    assert refused.value.code == "handoff_bundle_invalid" and refused.value.detail == {"at": "issue.mention.timePrecision"}


def test_a_stated_precision_that_is_not_the_formats_is_refused_without_widening():
    for value, precision in (("2026-09-30", "month"), ("2026-09", "day"), ("2026-09-30", "datetime"), ("2026-09-30", "unknown"), (None, "day")):
        with pytest.raises(ExtractionFailure):
            validate_bundle(sealed(value, precision))
