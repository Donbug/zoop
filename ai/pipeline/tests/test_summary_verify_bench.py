"""Consumer checks for native summary-verifier capture; all HTTP is owned loopback.

The standalone smoke exercises the actual native send/receipt/decode path, both
scripted controls, scorer integrity, crash assembly and deny-all live preflight.
No runtime is mocked and no production receipt is manufactured here.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
SCRIPT = PIPELINE / "scripts/summary_verify_bench.py"
EVALUATION = PIPELINE.parent / "evaluation"
CASES = EVALUATION / "corpus/fin-summary-verify-ko-v1/cases.json"
CONTROLS = EVALUATION / "fixtures/summary-verification"


def command(arguments, home, extra_env=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1", **(extra_env or {})}
    done = subprocess.run([sys.executable, str(SCRIPT), *map(str, arguments)], env=env, capture_output=True, text=True, timeout=240)
    assert not done.stderr, done.stderr
    return done.returncode, json.loads(done.stdout)


def test_native_controls_crash_assembly_and_tamper_matrix(tmp_path):
    code, report = command(["smoke"], tmp_path)
    assert code == 0, report
    assert report["status"] == "passed"
    assert report["casesPerControl"] == 24
    assert report["executionMode"] == "loopback" and report["provenanceKind"] == "authored_control"
    assert report["controlHttpRequests"] == 48 and report["crashHttpRequests"] == 3
    assert report["externalProviderRequests"] == report["externalModelCalls"] == 0
    assert report["modelQualityMeasured"] is False
    assert report["scores"]["oracle"]["claims"]["accuracy"] == {"num": 30, "den": 30, "value": 1.0}
    assert report["scores"]["oracle"]["outcomes"]["accuracy"] == {"num": 24, "den": 24, "value": 1.0}
    assert report["scores"]["deviations"]["claims"]["accuracy"]["num"] == 22
    assert report["scores"]["deviations"]["outcomes"]["accuracy"]["num"] == 14
    assert report["scores"]["deviations"]["errors"]["total"] == 5
    assert report["scores"]["deviations"]["errors"]["unknown"] == 1
    assert len(report["tamperChecks"]) == 28
    assert report["crashBoundaries"] == ["intent", "receipt", "intent-unpublished", "receipt-unpublished", "outcome-unpublished"]
    assert report["goldOpenedAfterProducers"] and report["externalNetworkBlocked"]


def test_loopback_does_not_inherit_provider_credentials_or_proxy(tmp_path):
    sentinel = "synthetic-parent-key-must-never-be-sent"
    out = tmp_path / "run.json"
    code, result = command(["loopback", "--script", CONTROLS / "oracle.script.json", "--out", out, "--run-id", "clean-child"], tmp_path,
                           {"TYPESAFE_API_KEY": sentinel, "ZOOP_AI_API_KEY": sentinel, "OPENAI_API_KEY": sentinel,
                            "HTTP_PROXY": "http://203.0.113.1:1", "HTTPS_PROXY": "http://203.0.113.1:1",
                            "ALL_PROXY": "http://203.0.113.1:1", "TYPESAFE_BASE_URL": "https://must-not-contact.invalid/v1"})
    assert code == 0, result
    assert len(result["records"]) == 24 and all(r["status"] == "ok" for r in result["records"])
    assert result["system"]["binding"]["verifier"]["endpoint"].startswith("http://127.0.0.1:")
    assert all(sentinel.encode() not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    # Assembly is a keyless, read-only consumer and refuses to replace an existing export.
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
    code, assembled = command(["assemble", "--out-dir", str(out) + ".journal"], tmp_path)
    assert code == 0 and assembled == result
    code, refusal = command(["assemble", "--out-dir", str(out) + ".journal", "--out", out], tmp_path)
    assert code == 2 and refusal["error"] == "bench_FileExistsError"
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}


@pytest.mark.parametrize("argument", ["--cases", "--script"])
def test_loopback_refuses_gold_before_opening_or_creating_state(tmp_path, argument):
    out = tmp_path / "run.json"
    arguments = ["loopback", "--out", out]
    arguments += ["--script", CASES.with_name("gold.json")] if argument == "--script" else [
        "--script", CONTROLS / "oracle.script.json", "--cases", CASES.with_name("gold.json")]
    code, result = command(arguments, tmp_path)
    assert code == 2 and result["error"] == "bench_gold_forbidden"
    assert not list(tmp_path.iterdir())


def test_existing_loopback_output_is_never_replaced(tmp_path):
    out = tmp_path / "existing.json"
    out.write_bytes(b"operator-owned output\n")
    code, result = command(["loopback", "--script", CONTROLS / "oracle.script.json", "--out", out], tmp_path)
    assert code == 2 and result["error"] == "bench_output_exists"
    assert out.read_bytes() == b"operator-owned output\n"
    assert list(tmp_path.iterdir()) == [out]


@pytest.mark.parametrize("mode", ["loopback", "live"])
def test_unset_endpoint_never_defaults_to_real_provider(tmp_path, mode):
    code, result = command(["run", "--mode", mode, "--check", "--out-dir", tmp_path / "journal", "--run-id", "unset-url"], tmp_path)
    assert code == 2 and result["error"] == "bench_endpoint_required"
    assert not list(tmp_path.iterdir())


def test_mode_is_an_explicit_cli_requirement(tmp_path):
    done = subprocess.run([sys.executable, str(SCRIPT), "run", "--check", "--out-dir", str(tmp_path / "journal"), "--run-id", "no-mode"],
                          env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"},
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 2 and "--mode" in done.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("boundary,posts,first", [
    ("intent", 0, "bench_not_attempted"),
    ("receipt", 1, "bench_outcome_unrecorded"),
    ("outcome", 1, "ok"),
])
def test_killed_midwrite_assembles_without_resending(tmp_path, boundary, posts, first):
    sys.path.insert(0, str(PIPELINE))
    from scripts import summary_verify_bench as bench

    inputs = bench.load_summary_inputs(CASES)
    script = bench.load_summary_script(CONTROLS / "oracle.script.json", inputs)
    key = "tsk-summary-loopback-midwrite-test"
    server = bench.Loopback(inputs, script, key)
    journal = tmp_path / "journal"
    env = bench.child_env(server.base, key, 24, tmp_path, tmp_path / "budget")
    arguments = ["run", "--mode", "loopback", "--out-dir", journal, "--run-id", "midwrite-" + boundary,
                 "--script-sha256", bench.digest(script)]
    # Kill the real child after flushing half a JSON write. The wrapper follows
    # the destination operation, regardless of whether its fd is final or staged.
    hook = (
        "import os\n_original=b.exclusive_json\n_fdopen=b.os.fdopen\n_active=False\n"
        "def _capture(path,value):\n"
        " global _active\n"
        f" _active=str(path).endswith('.{boundary}.json')\n"
        " return _original(path,value)\n"
        "def _open(fd,*args,**kwargs):\n"
        " stream=_fdopen(fd,*args,**kwargs)\n"
        " if not _active: return stream\n"
        " class KilledWrite:\n"
        "  def __enter__(self): return self\n"
        "  def __exit__(self,*args): stream.close()\n"
        "  def write(self,data):\n"
        "   stream.write(data[:max(1,len(data)//2)])\n"
        "   stream.flush()\n"
        "   os.fsync(stream.fileno())\n"
        "   os._exit(9)\n"
        " return KilledWrite()\n"
        "b.exclusive_json=_capture\nb.os.fdopen=_open\n")
    try:
        killed = bench.child(arguments, env, hook=hook, network_port=server.port)
        assert killed.returncode == 9, (killed.stdout, killed.stderr)
        assert len(server.requests) == posts
        snapshot = {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in journal.iterdir()}
        assembled = bench.child(["assemble", "--out-dir", journal], {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
        assert assembled.returncode == 0, assembled.stdout
        records = json.loads(assembled.stdout)["records"]
        if first == "ok":
            assert records[0]["status"] == "ok" and records[0]["result"]["outcome"] == "available"
        else:
            assert records[0]["error"]["code"] == first
            assert records[0]["error"]["outcome"] == ("unknown" if boundary == "receipt" else "definite")
        assert all(r["error"]["code"] == "bench_not_attempted" for r in records[1:])
        assert not (journal / f"000.{boundary}.json").exists()
        assert any(p.name.endswith(".pending") for p in journal.iterdir())
        assert snapshot == {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in journal.iterdir()}
        refused = bench.child(arguments, env, network_port=server.port)
        assert refused.returncode == 2 and json.loads(refused.stdout)["error"] == "bench_directory_exists"
        assert len(server.requests) == posts
        assert all(p.stat().st_mode & 0o777 == 0o600 for p in journal.iterdir())
        # Only unpublished staging is ignored. A malformed published artifact
        # must still fail closed rather than becoming an unknown/empty record.
        (journal / f"000.{boundary}.json").write_bytes(b'{"partial":')
        malformed = bench.child(["assemble", "--out-dir", journal], {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
        assert malformed.returncode == 2 and json.loads(malformed.stdout)["error"] == "json_invalid"
        assert len(server.requests) == posts
    finally:
        server.close()


@pytest.mark.parametrize("symlink", [False, True])
def test_atomic_publication_never_clobbers_existing_destination(tmp_path, symlink):
    sys.path.insert(0, str(PIPELINE))
    from scripts import summary_verify_bench as bench

    target = tmp_path / "operator.json"
    target.write_bytes(b"operator-owned bytes")
    destination = tmp_path / "outcome.json" if symlink else target
    if symlink:
        destination.symlink_to(target)
    before = {p.name: (p.read_bytes(), p.lstat().st_mode, p.lstat().st_mtime_ns) for p in tmp_path.iterdir()}
    with pytest.raises(FileExistsError):
        bench.exclusive_json(destination, {"result": "must not replace"})
    assert before == {p.name: (p.read_bytes(), p.lstat().st_mode, p.lstat().st_mtime_ns) for p in tmp_path.iterdir()}
    assert not list(tmp_path.glob("*.pending"))
