"""`scripts/setup_ai_env.py`: 사람이 실행하는 .env 설정 CLI. 합성 값만 쓰며 실제 .env·key·네트워크·모델 호출은 없다.

실제 CLI 를 PTY 에서 구동해(숨김 입력, EOF/Ctrl-C, 동의, 동시 수정) 쓰기 동작을 검증하고, 병합·경로 안전·감사
기록은 같은 모듈을 직접 호출한다. 기본 대상(ai/worker/.env)은 어떤 테스트도 열지 않는다: 모든 실행에 임시 경로를 넘긴다.
"""
from __future__ import annotations

import errno
import fcntl
import importlib.util
import json
import os
import pty
import re
import select
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from zoop_ai.doctor import build_report

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_ai_env.py"
_spec = importlib.util.spec_from_file_location("setup_ai_env", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules["setup_ai_env"] = mod
_spec.loader.exec_module(mod)

MARK = "SYNTHSECRETMARK"
KEY_A = f"sk-{MARK}-A_b.c~d+e/f=g:h"  # 허용 문자 전부(영숫자 + -_.~+/=:)
KEY_B = f"ts-{MARK}-B"
UNRELATED = "# my comment\nOTHER_KEY=keep-me\nexport FOO=\"bar baz\"\n"
YES = "[yes/N]"


class Session:
    """pty.fork 로 실제 CLI 를 띄우고 출력을 기다리며 입력을 보낸다."""

    def __init__(self, args: list[str], home: Path):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "LANG": "C.UTF-8",
               "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        self.out, self.pos, self.status = "", 0, None
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            try:
                os.execve(sys.executable, [sys.executable, "-I", "-B", str(SCRIPT), *args], env)
            finally:
                os._exit(127)

    def _pump(self, timeout: float) -> bool:
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return True
        try:
            data = os.read(self.fd, 4096)
        except OSError as exc:
            if exc.errno == errno.EIO:
                return False
            raise
        if not data:
            return False
        self.out += data.decode("utf-8", "replace")
        return True

    def expect(self, text: str, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while text not in self.out[self.pos:]:
            if time.monotonic() > deadline or not self._pump(0.2):
                pytest.fail(f"expected {text!r}; output so far:\n{self.out}")
        self.pos = self.out.index(text, self.pos) + len(text)

    def send(self, data: str | bytes) -> None:
        os.write(self.fd, data.encode() if isinstance(data, str) else data)

    def wait(self, timeout: float = 20.0) -> int:
        deadline = time.monotonic() + timeout
        while self._pump(0.2):
            if time.monotonic() > deadline:
                pytest.fail(f"CLI did not exit; output so far:\n{self.out}")
        _, status = os.waitpid(self.pid, 0)
        self.status = status
        return os.waitstatus_to_exitcode(status)

    def close(self) -> None:
        if self.status is None:
            try:
                os.kill(self.pid, signal.SIGKILL)
                os.waitpid(self.pid, 0)
            except OSError:
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass


@pytest.fixture
def work(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    root.chmod(0o755)
    return root


@pytest.fixture
def launch(tmp_path):
    sessions = []

    def start(args):
        sessions.append(Session(args, tmp_path))
        return sessions[-1]

    yield start
    for session in sessions:
        session.close()


def paths(work: Path):
    return work / ".env", work / "var" / "setup-audit.jsonl"


def cli_args(env: Path, audit: Path):
    return ["--env-file", str(env), "--audit-file", str(audit)]


def full_run(launch, env, audit, first="", second=""):
    session = launch(cli_args(env, audit))
    session.expect(YES)
    session.send("yes\n")
    session.expect("ZOOP_AI_API_KEY (")
    session.send(first + "\n")
    session.expect("TYPESAFE_API_KEY (")
    session.send(second + "\n")
    return session, session.wait()


def audit_records(audit: Path):
    return [json.loads(line) for line in audit.read_text().splitlines()]


def written(env: Path) -> dict[str, str]:
    return dict(re.findall(r"^([A-Z_]+)='(.*)'$", env.read_text(), re.M))


def record(env: Path, **extra):
    return {"v": 1, "ts": mod._now(), "operationId": "ab" * 16, "target": str(env),
            "variableNames": sorted(mod.MANAGED), "skippedNames": [], "profile": mod.PROFILE, **extra}


# ---- PTY: 정상 기록 -------------------------------------------------------------------------------------------
def test_pty_writes_pinned_profile_hidden_keys_preserves_unrelated_and_leaves_live_disabled(launch, work, monkeypatch):
    env, audit = paths(work)
    env.write_text(UNRELATED + "ZOOP_AI_LIVE_ENABLED=1\nZOOP_AI_GLOBAL_MAX_CALLS=5\n")
    env.chmod(0o644)
    inode_before = env.stat().st_ino
    session, code = full_run(launch, env, audit, KEY_A, KEY_B)
    assert code == 0, session.out
    assert MARK not in session.out  # 입력이 에코되지 않고 어디에도 출력되지 않는다
    assert "yes\r\n" in session.out  # 대조군: 숨기지 않는 입력(동의)은 같은 캡처에 에코된다
    # 대상/감사 경로, 고정 프로필, live 강제 안내가 동의 전에 출력된다.
    assert str(env) in session.out and str(audit) in session.out and "gpt-6-luna" in session.out and "jev-1.14.0" in session.out

    text = env.read_text()
    assert text.startswith(UNRELATED)                       # 관련 없는 줄은 그대로
    assert text.splitlines()[3] == "ZOOP_AI_LIVE_ENABLED='0'"  # 기존 관리 줄은 제자리에서 교체
    values = written(env)
    assert values["ZOOP_AI_LIVE_ENABLED"] == "0" and values["ZOOP_AI_GLOBAL_MAX_CALLS"] == "0"
    assert values["TYPESAFE_VALIDATION_MODEL"] == "jev-1.14.0"
    assert values["TYPESAFE_BASE_URL"] == "https://api.typesafe.ai/v1"
    for stage in ("DOCUMENT_SUMMARY", "DOCUMENT_SENTIMENT", "BRIEFING_OUTLOOK"):
        assert values[f"ZOOP_AI_{stage}_MODEL"] == "gpt-6-luna"
        assert values[f"ZOOP_AI_{stage}_REASONING_EFFORT"] == "high"
    # VERIFY is native Jev: selected by provider, modelled by TYPESAFE_VALIDATION_MODEL, and no Luna verify setting is written.
    assert values["ZOOP_AI_VERIFY_PROVIDER"] == "typesafe-native"
    assert "ZOOP_AI_VERIFY_MODEL" not in values and "ZOOP_AI_VERIFY_REASONING_EFFORT" not in values
    assert stat.S_IMODE(env.stat().st_mode) == 0o600 and env.stat().st_ino != inode_before  # 원자적 교체
    assert sorted(p.name for p in work.iterdir()) == [".env", "var"]                         # 임시 파일·백업 없음

    # 쉘이 같은 리터럴로 읽는다.
    shown = subprocess.run(["/bin/sh", "-c", 'set -a; . "$1"; printf "%s\\n%s\\n%s\\n%s" "$ZOOP_AI_API_KEY" "$TYPESAFE_API_KEY" '
                            '"$ZOOP_AI_LIVE_ENABLED" "$OTHER_KEY"', "sh", str(env)], capture_output=True, text=True, check=True).stdout
    assert shown.split("\n") == [KEY_A, KEY_B, "0", "keep-me"]

    # 감사 기록: planned→committed, 이름·고정 프로필만, 값 없음, 0600.
    records = audit_records(audit)
    assert [r["outcome"] for r in records] == ["planned", "committed"] and records[0]["operationId"] == records[1]["operationId"]
    assert records[1]["target"] == str(env) and records[1]["skippedNames"] == []
    assert {"ZOOP_AI_API_KEY", "TYPESAFE_API_KEY", "ZOOP_AI_LIVE_ENABLED"} <= set(records[1]["variableNames"])
    assert records[1]["profile"] == {"llm": "gpt-6-luna", "reasoningEffort": "high", "verify": "typesafe-native", "jevModel": "jev-1.14.0",
                                    "jevMode": "native-verify", "liveEnabled": 0, "globalMaxCalls": 0}
    assert records[1]["removedNames"] == []
    assert MARK not in audit.read_text()
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600 and stat.S_IMODE(audit.parent.stat().st_mode) == 0o700

    # worker 의 오프라인 doctor 가 이 값을 읽으면 설정은 유효하지만 live 는 닫혀 있다.
    for name in list(os.environ):
        if name.startswith(("ZOOP_AI_", "TYPESAFE_")) or name.endswith(("_PROXY", "_proxy")):
            monkeypatch.delenv(name)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    report = build_report("native-jev")
    assert report["configValid"] is True and report["liveEnvironmentReady"] is False
    assert report["liveGate"]["enabledFlag"] is False and report["liveGate"]["globalMaxCalls"] == 0
    assert {(s["model"], s["reasoningEffort"]) for s in report["stages"]} == {("gpt-6-luna", "high"), ("jev-1.14.0", None)}
    assert next(s for s in report["stages"] if s["kind"] == "semantic-verification")["provider"] == "typesafe-native"
    assert MARK not in json.dumps(report)

    status = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--status", "--audit-file", str(audit)],
                            capture_output=True, text=True)
    assert status.returncode == 0 and "setup-status: committed" in status.stdout and MARK not in status.stdout + status.stderr


def test_enter_skips_keys_keeps_existing_and_audit_appends(launch, work):
    env, audit = paths(work)
    env.write_text("ZOOP_AI_API_KEY='old-SYNTH'\n")
    _, code = full_run(launch, env, audit)
    assert code == 0
    assert env.read_text().startswith("ZOOP_AI_API_KEY='old-SYNTH'\n")  # 건너뜀 = 기존 줄 그대로
    assert "TYPESAFE_API_KEY" not in written(env) and written(env)["ZOOP_AI_LIVE_ENABLED"] == "0"
    first = audit.read_text()
    assert audit_records(audit)[-1]["skippedNames"] == ["TYPESAFE_API_KEY", "ZOOP_AI_API_KEY"]

    _, code = full_run(launch, env, audit)  # 두 번째 실행: 감사는 덮어쓰지 않고 이어 붙인다
    assert code == 0 and audit.read_text().startswith(first) and len(audit_records(audit)) == 4
    assert len({r["operationId"] for r in audit_records(audit)}) == 2


def test_rejected_secret_characters_are_not_stored_or_echoed(launch, work):
    env, audit = paths(work)
    session = launch(cli_args(env, audit))
    session.expect(YES)
    session.send("yes\n")
    session.expect("ZOOP_AI_API_KEY (")
    session.send(f"bad'quote-{MARK}\n")
    session.expect("허용되지 않는 문자")
    session.expect("ZOOP_AI_API_KEY (")  # 같은 key 를 다시 묻는다
    session.send("\n")
    session.expect("TYPESAFE_API_KEY (")
    session.send("\n")
    assert session.wait() == 0
    assert MARK not in session.out and MARK not in env.read_text() and MARK not in audit.read_text()
    assert "ZOOP_AI_API_KEY" not in written(env)


# ---- PTY: 취소는 아무것도 남기지 않는다 -----------------------------------------------------------------------
def _decline(s):
    s.expect(YES); s.send("n\n")


def _eof_consent(s):
    s.expect(YES); s.send(b"\x04")


def _ctrlc_consent(s):
    s.expect(YES); s.send(b"\x03")


def _eof_first_key(s):
    s.expect(YES); s.send("yes\n"); s.expect("ZOOP_AI_API_KEY ("); s.send(b"\x04")


def _ctrlc_second_key(s):
    s.expect(YES); s.send("yes\n"); s.expect("ZOOP_AI_API_KEY ("); s.send(f"{MARK}-typed\n")
    s.expect("TYPESAFE_API_KEY ("); s.send(b"\x03")


@pytest.mark.parametrize("existing", [None, UNRELATED])
@pytest.mark.parametrize("scenario", [_decline, _eof_consent, _ctrlc_consent, _eof_first_key, _ctrlc_second_key])
def test_cancel_paths_leave_env_and_audit_untouched(launch, work, scenario, existing):
    env, audit = paths(work)
    if existing is not None:
        env.write_text(existing)
    session = launch(cli_args(env, audit))
    scenario(session)
    assert session.wait() == 1, session.out
    assert MARK not in session.out
    assert (env.read_text() if existing is not None else env.exists()) == (existing if existing is not None else False)
    assert not audit.parent.exists()
    assert [p.name for p in work.iterdir()] == ([".env"] if existing is not None else [])


# ---- PTY: 거부 --------------------------------------------------------------------------------------------------
def _dup(work, env, audit):
    env.write_text("ZOOP_AI_API_KEY='a'\nexport ZOOP_AI_API_KEY='b'\n")
    return cli_args(env, audit), env


def _multiline(work, env, audit):
    env.write_text('FOO="open\nZOOP_AI_API_KEY=x"\n')
    return cli_args(env, audit), env


def _symlink_env(work, env, audit):
    target = work / "elsewhere.txt"
    target.write_text("untouched\n")
    env.symlink_to(target)
    return cli_args(env, audit), target


def _directory_env(work, env, audit):
    env.mkdir()
    return cli_args(env, audit), None


def _fifo_env(work, env, audit):
    os.mkfifo(env)
    return cli_args(env, audit), None


def _symlink_parent(work, env, audit):
    real = work / "real"
    real.mkdir()
    (work / "link").symlink_to(real)
    return cli_args(work / "link" / ".env", audit), None


def _group_writable_parent(work, env, audit):
    work.chmod(0o775)
    return cli_args(env, audit), None


def _audit_symlink(work, env, audit):
    audit.parent.mkdir()
    target = work / "audit-elsewhere"
    target.write_text("untouched\n")
    audit.symlink_to(target)
    return cli_args(env, audit), target


def _audit_parent_symlink(work, env, audit):
    real = work / "real-var"
    real.mkdir()
    audit.parent.symlink_to(real)
    return cli_args(env, audit), real


def _audit_is_env(work, env, audit):
    return cli_args(env, env), None


@pytest.mark.parametrize("build", [_dup, _multiline, _symlink_env, _directory_env, _fifo_env, _symlink_parent,
                                   _group_writable_parent, _audit_symlink, _audit_parent_symlink, _audit_is_env])
def test_unsafe_destinations_and_ambiguous_files_are_refused_before_any_prompt(launch, work, build):
    env, audit = paths(work)
    args, watched = build(work, env, audit)
    before = (watched.read_text() if watched is not None and watched.is_file() else None,
              sorted(p.name for p in watched.iterdir()) if watched is not None and watched.is_dir() else None)
    snapshot = {p: p.read_bytes() for p in work.iterdir() if p.is_file() and not p.is_symlink()}
    session = launch(args)
    assert session.wait() == 2, session.out
    assert YES not in session.out and "거부" in session.out
    after = (watched.read_text() if watched is not None and watched.is_file() else None,
             sorted(p.name for p in watched.iterdir()) if watched is not None and watched.is_dir() else None)
    assert before == after
    assert snapshot == {p: p.read_bytes() for p in work.iterdir() if p.is_file() and not p.is_symlink()}
    assert not list(work.rglob("*.tmp"))
    assert not [p for p in work.rglob("setup-audit.jsonl") if p.is_file() and not p.is_symlink()]


def test_non_tty_and_secret_arguments_are_refused(work):
    env, audit = paths(work)
    run = lambda *extra: subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), *cli_args(env, audit), *extra],
                                        stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert run().returncode == 2 and not env.exists() and not audit.parent.exists()
    result = run("--zoop-ai-api-key", f"{MARK}-argv")
    assert result.returncode == 2 and MARK not in result.stdout + result.stderr
    missing = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--env-file", str(env)], stdin=subprocess.DEVNULL,
                             capture_output=True, text=True)
    assert missing.returncode == 2 and not env.exists()  # 기본 감사 기록을 건드리지 않도록 --audit-file 필수


def test_concurrent_edit_during_prompts_is_refused_without_clobbering(launch, work):
    env, audit = paths(work)
    env.write_text("A=1\n")
    session = launch(cli_args(env, audit))
    session.expect(YES)
    session.send("yes\n")
    session.expect("ZOOP_AI_API_KEY (")
    env.write_text("A=1\nEDITED_BY_OTHER=1\n")  # 입력하는 사이 다른 편집기가 바꿈
    session.send(KEY_A + "\n")
    session.expect("TYPESAFE_API_KEY (")
    session.send("\n")
    assert session.wait() == 2 and "동시 수정" in session.out
    assert env.read_text() == "A=1\nEDITED_BY_OTHER=1\n" and not audit.parent.exists() and MARK not in session.out

    fresh, fresh_audit = work / "new.env", work / "var2" / "a.jsonl"
    session = launch(cli_args(fresh, fresh_audit))
    session.expect(YES)
    session.send("yes\n")
    session.expect("ZOOP_AI_API_KEY (")
    fresh.write_text("CREATED_BY_OTHER=1\n")  # 없던 파일이 생김
    session.send("\n")
    session.expect("TYPESAFE_API_KEY (")
    session.send("\n")
    assert session.wait() == 2 and fresh.read_text() == "CREATED_BY_OTHER=1\n" and not fresh_audit.parent.exists()


# ---- 직접 호출: 파서·병합·검증 -----------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "ZOOP_AI_API_KEY=a\nZOOP_AI_API_KEY=b\n",
    "export ZOOP_AI_VERIFY_MODEL=x\nZOOP_AI_VERIFY_MODEL=y\n",
    'FOO="unterminated\nZOOP_AI_API_KEY=x"\n',
    "FOO='open\n",
    "FOO=bar\\\nZOOP_AI_API_KEY=x\n",
    "ZOOP_AI_API_KEY\n",
    "export TYPESAFE_API_KEY\n",
    "A=1\r\nB=2\r\n",
    "A=\x00\n",
])
def test_ambiguous_dotenv_is_refused(text):
    with pytest.raises(mod.Refused):
        mod.parse_env(text)
    with pytest.raises(mod.Refused):
        mod.merge_env(text, {"ZOOP_AI_LIVE_ENABLED": "0"})


def test_merge_preserves_unrelated_lines_and_replaces_only_managed_ones():
    text = "A='x # y'\nB=\"p q\" # c\n# ZOOP_AI_API_KEY=commented\nexport ZOOP_AI_API_KEY='old'\n\nTAIL=1"
    merged = mod.merge_env(text, {"ZOOP_AI_API_KEY": "new", "ZOOP_AI_LIVE_ENABLED": "0"})
    assert merged.splitlines()[:6] == ["A='x # y'", 'B="p q" # c', "# ZOOP_AI_API_KEY=commented", "ZOOP_AI_API_KEY='new'", "", "TAIL=1"]
    assert merged.endswith("ZOOP_AI_LIVE_ENABLED='0'\n") and merged.count("ZOOP_AI_API_KEY=") == 2  # 주석 하나 + 실제 하나
    assert mod.merge_env("", {"ZOOP_AI_LIVE_ENABLED": "0"}).count("ZOOP_AI_LIVE_ENABLED") == 1


def test_merge_serialization_is_literal_for_the_shell_even_for_metacharacters(work):
    value = 'v-$HOME-${X}-"q";#&`id`-$(echo hi)'  # validate_secret 은 거부하지만 하위 병합 계층도 리터럴이어야 한다
    env = work / "meta.env"
    env.write_text(mod.merge_env("", {"ZOOP_AI_API_KEY": value}))
    out = subprocess.run(["/bin/sh", "-c", '. "$1"; printf "%s" "$ZOOP_AI_API_KEY"', "sh", str(env)],
                         capture_output=True, text=True, check=True).stdout
    assert out == value


@pytest.mark.parametrize("bad", ["a'b", "a\\b", "a b", "a\nb", "a\tb", "é-key", "x" * 513, "a\x00b", "a$b", "a${X}b", 'a"b', "a`b",
                                 "a;b", "a#b", "a&b", "a(b)", "a|b", "a*b"])
def test_secret_validation_rejects_characters_a_dotenv_consumer_could_interpret(bad):
    with pytest.raises(ValueError):
        mod.validate_secret(bad)


@pytest.mark.parametrize("bad", ["a'b", "a\\b", "a\nb", "a\rb"])
def test_merge_refuses_values_that_cannot_be_single_quoted_literally(bad):
    with pytest.raises(ValueError):
        mod.merge_env("", {"ZOOP_AI_API_KEY": bad})


def test_secret_validation_strips_surrounding_whitespace_and_empty_means_skip():
    assert mod.validate_secret("  abc-123 \n") == "abc-123" and mod.validate_secret("   ") == ""


def test_foreign_owner_destinations_are_refused(work, monkeypatch):
    env = work / ".env"
    env.write_text("A=1\n")
    mod.check_private_dir(work)
    monkeypatch.setattr(mod, "_euid", lambda: os.geteuid() + 1)
    with pytest.raises(mod.Refused):
        mod.check_private_dir(work)
    with pytest.raises(mod.Refused):
        mod._check_regular(os.lstat(env))


# ---- 직접 호출: 커밋·감사 ---------------------------------------------------------------------------------------
def test_commit_failure_after_planned_is_reported_and_leaves_original_without_temp_files(work, monkeypatch):
    env, audit = paths(work)
    env.write_text("A=1\n")

    def boom(*_a, **_k):
        raise OSError(errno.EIO, "synthetic replace failure")

    monkeypatch.setattr(mod.os, "replace", boom)
    with pytest.raises(mod.WriteFailed) as caught:
        mod.commit(env, audit, b"A=1\n", "A=1\nB='2'\n", record(env))
    assert caught.value.audit_recorded and env.read_text() == "A=1\n"
    assert {p.name for p in work.iterdir()} == {".env", "var"}
    assert [r["outcome"] for r in audit_records(audit)] == ["planned", "failed"]
    monkeypatch.undo()
    code, lines = mod.read_status(audit)
    assert code == 1 and lines[0] == "setup-status: failed"


def test_temp_file_failure_leaves_no_secret_bearing_temp(work, monkeypatch):
    env, audit = paths(work)
    real_temp = mod._write_temp

    def failing_temp(directory, text):  # fsync 는 임시 파일 쓰기 동안에만 실패시킨다(planned 감사 fsync 는 정상)
        with monkeypatch.context() as inner:
            inner.setattr(mod.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError(errno.EIO, "synthetic fsync failure")))
            return real_temp(directory, text)

    monkeypatch.setattr(mod, "_write_temp", failing_temp)
    with pytest.raises(mod.WriteFailed) as caught:
        mod.commit(env, audit, None, f"SECRET='{MARK}'\n", record(env))
    assert caught.value.audit_recorded and not env.exists()
    assert not any(p.name.endswith(".tmp") for p in work.iterdir())
    assert [r["outcome"] for r in audit_records(audit)] == ["planned", "failed"]


def test_missing_committed_record_is_reported_as_uncertain_never_silent(work, monkeypatch):
    env, audit = paths(work)
    real = mod.append_audit

    def flaky(path, rec):
        if rec["outcome"] == "committed":
            raise OSError(errno.ENOSPC, "synthetic")
        real(path, rec)

    monkeypatch.setattr(mod, "append_audit", flaky)
    with pytest.raises(mod.AuditUncertain):
        mod.commit(env, audit, None, "A='1'\n", record(env))
    assert env.read_text() == "A='1'\n"  # 롤백하지 않는다
    code, lines = mod.read_status(audit)
    assert code == 1 and lines[0] == "setup-status: uncertain"


def test_planned_audit_failure_blocks_the_write(work, monkeypatch):
    env, audit = paths(work)
    monkeypatch.setattr(mod, "append_audit", lambda *_a: (_ for _ in ()).throw(OSError(errno.EACCES, "synthetic")))
    with pytest.raises(mod.Refused) as caught:
        mod.commit(env, audit, None, "A='1'\n", record(env))
    assert caught.value.code == "audit_unavailable" and not env.exists()


def test_cli_exit_codes_for_write_failure_and_uncertain_audit(work, monkeypatch):
    env, audit = paths(work)
    monkeypatch.setattr(mod, "_confirm", lambda _p: True)
    monkeypatch.setattr(mod, "_ask_secret", lambda _n: "")
    monkeypatch.setattr(mod, "commit", lambda *_a: (_ for _ in ()).throw(mod.WriteFailed(True, "synthetic")))
    assert mod.run_setup(env, audit, False) == mod.EXIT_WRITE_FAILED
    monkeypatch.setattr(mod, "commit", lambda *_a: (_ for _ in ()).throw(mod.AuditUncertain()))
    assert mod.run_setup(env, audit, False) == mod.EXIT_AUDIT_UNCERTAIN


def test_concurrent_setup_holding_the_directory_lock_is_refused(work):
    env, audit = paths(work)
    fd = os.open(work, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(mod.Refused) as caught:
            mod.commit(env, audit, None, "A='1'\n", record(env))
        assert caught.value.code == "lock_busy" and not env.exists() and not audit.parent.exists()
    finally:
        os.close(fd)


def test_audit_append_refuses_symlink_foreign_file_and_hardlink(work, monkeypatch):
    _, audit = paths(work)
    audit.parent.mkdir(mode=0o700)
    target = work / "target"
    target.write_text("keep\n")
    audit.symlink_to(target)
    with pytest.raises(mod.Refused):
        mod.append_audit(audit, record(work / ".env", outcome="planned"))
    assert target.read_text() == "keep\n"
    audit.unlink()
    audit.write_text("")
    os.link(audit, work / "alias")
    with pytest.raises(mod.Refused):
        mod.append_audit(audit, record(work / ".env", outcome="planned"))


# ---- --status: 감사 기록만 읽고 임의 텍스트는 출력하지 않는다 --------------------------------------------------
def run_status(audit: Path):
    return subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--status", "--audit-file", str(audit)],
                          capture_output=True, text=True)


def test_status_none_and_untrusted_audit_content_is_never_echoed(work):
    _, audit = paths(work)
    result = run_status(audit)
    assert result.returncode == 1 and "setup-status: none" in result.stdout
    audit.parent.mkdir(mode=0o700)
    for bad in ("TOPSECRET-JUNK\n",
                json.dumps({**record(work / ".env", outcome="committed"), "note": "TOPSECRET-EXTRA"}) + "\n",
                json.dumps(record(work / ".env", outcome="committed", ) | {"variableNames": ["TOPSECRET_NAME"]}) + "\n",
                json.dumps(record(work / ".env", outcome="committed") | {"profile": {"llm": "TOPSECRET-model"}}) + "\n"):
        audit.write_text(bad)
        result = run_status(audit)
        assert result.returncode == 2 and "audit-invalid" in result.stdout and "TOPSECRET" not in result.stdout + result.stderr


def test_status_reports_the_last_operation_only_from_validated_fields(work):
    _, audit = paths(work)
    env = work / ".env"
    audit.parent.mkdir(mode=0o700)
    rows = [record(env, outcome="planned"), record(env, outcome="committed"),
            record(env, outcome="planned") | {"operationId": "cd" * 16}]
    audit.write_text("".join(json.dumps(r) + "\n" for r in rows))
    audit.chmod(0o600)
    result = run_status(audit)
    assert result.returncode == 1 and "setup-status: uncertain" in result.stdout and "committedOperations: 1" in result.stdout
    assert "cd" * 16 in result.stdout and "LIVE_ENABLED=0" in result.stdout


# ---- VERIFY = native Jev: 쓰이지 않는 Luna 검증 설정의 삭제 -------------------------------------------------------
STALE = "STALEVALUEMARK"


def test_stale_luna_verify_lines_are_deleted_announced_by_name_and_audited_while_everything_else_is_kept(launch, work):
    env, audit = paths(work)
    env.write_text(f"# keep\nZOOP_AI_VERIFY_MODEL='{STALE}-model'\nOTHER=1\nexport ZOOP_AI_VERIFY_REASONING_EFFORT={STALE}-effort\n"
                   "ZOOP_AI_API_KEY='old-SYNTH'\n")
    session, code = full_run(launch, env, audit)
    assert code == 0, session.out
    assert "삭제할 줄" in session.out and "ZOOP_AI_VERIFY_MODEL" in session.out and STALE not in session.out
    text = env.read_text()
    assert "ZOOP_AI_VERIFY_MODEL" not in text and "ZOOP_AI_VERIFY_REASONING_EFFORT" not in text and STALE not in text
    assert text.startswith("# keep\nOTHER=1\nZOOP_AI_API_KEY='old-SYNTH'\n")  # 건너뛴 key 와 관련 없는 줄은 그대로
    assert written(env)["ZOOP_AI_VERIFY_PROVIDER"] == "typesafe-native"
    records = audit_records(audit)
    assert [r["removedNames"] for r in records] == [["ZOOP_AI_VERIFY_MODEL", "ZOOP_AI_VERIFY_REASONING_EFFORT"]] * 2
    assert STALE not in audit.read_text()
    status = run_status(audit)
    assert status.returncode == 0 and "namesRemoved: ZOOP_AI_VERIFY_MODEL, ZOOP_AI_VERIFY_REASONING_EFFORT" in status.stdout
    assert "verify=typesafe-native" in status.stdout and STALE not in status.stdout + status.stderr


def test_merge_removes_only_named_managed_lines_and_refuses_anything_else():
    text = "A=1\nZOOP_AI_VERIFY_MODEL='x'\n# ZOOP_AI_VERIFY_REASONING_EFFORT=commented\nZOOP_AI_VERIFY_REASONING_EFFORT=y\nB=2\n"
    merged = mod.merge_env(text, {"ZOOP_AI_LIVE_ENABLED": "0"}, ["ZOOP_AI_VERIFY_MODEL", "ZOOP_AI_VERIFY_REASONING_EFFORT"])
    assert merged.splitlines()[:3] == ["A=1", "# ZOOP_AI_VERIFY_REASONING_EFFORT=commented", "B=2"]
    assert "ZOOP_AI_VERIFY_MODEL" not in mod.merge_env("A=1\n", {"ZOOP_AI_LIVE_ENABLED": "0"}, ["ZOOP_AI_VERIFY_MODEL"])
    with pytest.raises(ValueError):
        mod.merge_env(text, {}, ["A"])  # 관리 이름이 아니면 지우지 않는다
    with pytest.raises(ValueError):
        mod.merge_env(text, {"ZOOP_AI_VERIFY_MODEL": "v"}, ["ZOOP_AI_VERIFY_MODEL"])  # 쓰면서 동시에 지울 수 없다


def test_status_still_reads_records_of_the_earlier_profile_and_says_the_new_profile_is_not_applied(work):
    _, audit = paths(work)
    env = work / ".env"
    audit.parent.mkdir(mode=0o700)
    audit.write_text("".join(json.dumps(record(env, outcome=o, profile=mod.LEGACY_PROFILE)) + "\n" for o in ("planned", "committed")))
    audit.chmod(0o600)
    result = run_status(audit)
    assert result.returncode == 0 and "setup-status: committed" in result.stdout
    assert "preparation-only" in result.stdout and "verify=openai-compatible" in result.stdout and "이전 프로필" in result.stdout


# ---- 기본 대상 ----------------------------------------------------------------------------------------------------
def test_default_targets_are_the_worker_env_and_private_var_audit():
    worker = SCRIPT.parents[1]
    assert mod.DEFAULT_ENV == worker / ".env" and mod.DEFAULT_AUDIT == worker / "var" / "setup-audit.jsonl"
