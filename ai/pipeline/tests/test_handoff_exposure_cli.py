"""The ACTUAL `zoop-ai-handoff-exposure` CLI (installed console-script entry point, child processes) over REAL authored ingestion + S2 + S3 worlds and REAL frozen handoffs.

Every expectation is hand-written from the authored world (see scripts/handoff_exposure_smoke.py, which owns the worlds, the audit-guarded runner and the case tables); no core
function computes one. Each child runs under an audit hook that aborts on a network attempt, a process spawn, a write under the owned state root or a non-immutable SQLite
connection, and every run compares the whole owned tree (modes, mtimes, sizes, hashes) before and after. No model, no network, no ledger write.

A report is a private proposal for the SELECTED handoffs: it is never applied to the app, and an empty or smaller report is no statement of global safety.

The pure closure and the query contract are in tests/test_handoff_exposure.py. These tests need `make pipeline-install` (the console script and its entry point).
"""
from __future__ import annotations

import pytest

from scripts import handoff_exposure_smoke as ex


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    """The authored worlds (default+uncited source, chain, rich impact), each built once on first use; the tests never leave a world changed."""
    return ex.Worlds(tmp_path_factory.mktemp("zoop-handoff-exposure") / "owned")


def test_the_audit_guard_aborts_every_forbidden_action_and_allows_read_only_access(tmp_path):
    ex.guard_effective(tmp_path.resolve() / "guard")


def test_the_authored_worlds_are_what_the_hand_written_expectations_assume(worlds):
    ex.check_authored_worlds(worlds)


def test_the_report_over_the_selected_bundles_is_identical_before_and_after_a_revoked_uncited_source_while_export_withholds(worlds):
    ex.check_revoked_uncited_source(worlds)


def test_source_changes_report_only_matching_articles_and_quotes_and_every_model_input_relation_of_an_affected_upstream(worlds):
    ex.check_source_closures(worlds)


def test_a_relation_retraction_is_precise_never_withdraws_a_quote_and_needs_no_source_ledger(worlds):
    ex.check_relation_retraction(worlds)


def test_structural_anchors_and_unavailable_paths_are_marked_conservatively_on_a_retraction(worlds):
    ex.check_chain_retraction(worlds)


def test_an_impact_only_sentence_is_reached_by_a_change_of_its_document(worlds):
    ex.check_impact_evidence(worlds)


def test_unknown_identities_are_refused_and_recorded_but_unbound_ones_report_nothing_bound(worlds):
    ex.check_identities(worlds)


def test_malformed_input_and_flag_combinations_are_refused_before_any_ledger_opens(worlds):
    ex.check_invalid_input(worlds)


def test_one_unmappable_selected_handoff_refuses_the_whole_report(worlds):
    ex.check_selection_refusals(worlds)


def test_a_current_schema_receipt_with_forged_digests_or_source_pins_is_damaged_state(worlds):
    ex.check_damaged_current_receipts(worlds)


def test_a_hot_wal_is_a_failure_with_no_artifact_fast_path_and_no_recovery(worlds):
    ex.check_hot_wal(worlds)


def test_missing_hot_damaged_empty_wrong_and_busy_source_ledgers_refuse_without_touching_anything(worlds):
    ex.check_source_ledgers(worlds)


def test_the_same_query_gives_the_same_bytes_and_an_oversized_report_refuses_whole(worlds):
    ex.check_determinism_and_limits(worlds)


def test_the_installed_console_script_prints_what_the_guarded_entry_point_prints(worlds):
    ex.check_console_script(worlds)
