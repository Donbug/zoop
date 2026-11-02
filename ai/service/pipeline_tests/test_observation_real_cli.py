"""The same source-pinned real HTTP/CLI scenario used by the standalone smoke."""
from observation_support import smoke


def test_observation_export_native_http(tmp_path):
    report = smoke(tmp_path / "observation")
    assert report["status"] == "passed" and report["sourceWrites"] == report["providerCalls"] == 0
