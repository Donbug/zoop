"""Real installed native commands and authenticated HTTP; external network denied."""
from round_service_support import run_scenario


def test_round_plan_admission_analysis_freeze_restart_and_current_authority(tmp_path):
    report = run_scenario(tmp_path / "round-service")
    assert report["state"] == "passed"
    assert report["providerCalls"] == 0 and report["networkAttempts"] == 0


def test_first_committed_tick_lost_output_does_not_poison_later_slots(tmp_path):
    report = run_scenario(tmp_path / "lost-first-tick", lost_first_tick=True)
    assert report["state"] == "passed"
    assert report["committedUnknownRecoveredByFutureSlot"] and report["originalUnknownPreserved"]
    assert report["unclaimedObservationCarried"]
    assert report["providerCalls"] == report["networkAttempts"] == 0
