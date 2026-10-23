"""Installed CLI -> actual HTTP, with independently authored closure expectations and read-only snapshots."""
from real_exposure_support import build, exercise


def test_real_exposure_transport_and_post_revocation_identity_reads(tmp_path):
    world = build(tmp_path / "world")
    result = exercise(tmp_path / "service", world)
    assert result["status"] == "passed"
