#!/usr/bin/env python3
"""Zoop AI worker 로컬 설정 도구 (사람이 터미널에서 직접 실행; stdlib 전용).

    python3 ai/worker/scripts/setup_ai_env.py            # 대화형 설정
    python3 ai/worker/scripts/setup_ai_env.py --status   # 감사 기록만 읽어 완료 여부 보고

하는 일: ai/worker/.env 에 고정 프로필(문서 요약·감성·briefing-outlook = gpt-6-luna / reasoning high, VERIFY = native TypeSafe Jev
jev-1.14.0, live 꺼짐)과, 사용자가 숨김 입력한 ZOOP_AI_API_KEY / TYPESAFE_API_KEY 를 기록한다. VERIFY 가 Jev 이므로 쓰이지 않는
ZOOP_AI_VERIFY_MODEL / ZOOP_AI_VERIFY_REASONING_EFFORT 줄은(있으면) 삭제한다. 하지 않는 일: 네트워크 요청, 모델·계정 호출,
프로세스 실행, 키 검증, 지출 승인. 값은 인수·로그·감사 기록·출력 어디에도 남기지 않는다. 기존 .env 는 이 도구가 관리하는 이름의
줄만 바꾸거나 지우고 나머지는 그대로 보존한다(쉘로 source 하지 않고 줄 단위 리터럴 파서만 사용).
"""
from __future__ import annotations

import argparse
import fcntl
import getpass
import json
import os
import re
import secrets
import signal
import stat
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV = WORKER_DIR / ".env"
DEFAULT_AUDIT = WORKER_DIR / "var" / "setup-audit.jsonl"

# ---- 고정 프로필 (비밀 아님) -------------------------------------------------------------------------------------
LLM_MODEL = "gpt-6-luna"
LLM_EFFORT = "high"
JEV_MODEL = "jev-1.14.0"
VERIFY_PROVIDER = "typesafe-native"
# VERIFY 는 Jev 가 맡는다. gpt-6-luna 용 VERIFY model/effort 는 쓰이지 않고, 남아 있으면 worker 가 거부하므로(오해 방지) 이 도구가 지운다.
LLM_STAGES = ("DOCUMENT_SUMMARY", "DOCUMENT_SENTIMENT", "BRIEFING_OUTLOOK")
RETIRED_SETTINGS = ("ZOOP_AI_VERIFY_MODEL", "ZOOP_AI_VERIFY_REASONING_EFFORT")
PUBLIC_SETTINGS = (
    ("ZOOP_AI_LIVE_ENABLED", "0"),
    ("ZOOP_AI_GLOBAL_MAX_CALLS", "0"),
    ("ZOOP_AI_PROVIDER", "openai-compatible"),
    ("ZOOP_AI_BASE_URL", "https://api.openai.com/v1"),
    ("ZOOP_AI_VERIFY_PROVIDER", VERIFY_PROVIDER),
    *((f"ZOOP_AI_{s}_MODEL", LLM_MODEL) for s in LLM_STAGES),
    *((f"ZOOP_AI_{s}_REASONING_EFFORT", LLM_EFFORT) for s in LLM_STAGES),
    ("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1"),
    ("TYPESAFE_VALIDATION_MODEL", JEV_MODEL),
)
SECRET_PROMPTS = (
    ("ZOOP_AI_API_KEY", "OpenAI 호환 LLM(gpt-6-luna) key"),
    ("TYPESAFE_API_KEY", "TypeSafe Jev key (S1 VERIFY native 호출용, 지출 승인 아님)"),
)
SECRET_NAMES = tuple(n for n, _ in SECRET_PROMPTS)
MANAGED = frozenset(n for n, _ in PUBLIC_SETTINGS) | frozenset(SECRET_NAMES) | frozenset(RETIRED_SETTINGS)
PROFILE = {"llm": LLM_MODEL, "reasoningEffort": LLM_EFFORT, "verify": VERIFY_PROVIDER, "jevModel": JEV_MODEL,
           "jevMode": "native-verify", "liveEnabled": 0, "globalMaxCalls": 0}
# 이전 도구가 남긴 감사 기록(Jev 는 준비 전용, VERIFY = gpt-6-luna)도 유효한 기록으로 읽는다. 새 기록은 항상 PROFILE 이다.
LEGACY_PROFILE = {"llm": LLM_MODEL, "reasoningEffort": LLM_EFFORT, "jevModel": JEV_MODEL, "jevMode": "preparation-only",
                  "liveEnabled": 0, "globalMaxCalls": 0}

MAX_ENV_BYTES = 1 << 20
MAX_AUDIT_BYTES = 4 << 20
MAX_SECRET_LEN = 512
# key 는 어떤 dotenv/쉘 소비자(보간 `${}`·`$()`·백틱 포함)에서도 리터럴로 읽히도록 보수적인 문자만 허용한다.
SECRET_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~+/=:")

EXIT_OK, EXIT_CANCELLED, EXIT_REFUSED, EXIT_WRITE_FAILED, EXIT_AUDIT_UNCERTAIN = 0, 1, 2, 3, 4

MESSAGES = {
    "not_tty": "실제 터미널(TTY)에서만 실행할 수 있습니다. 입력을 파이프·리다이렉트로 넘기지 마세요.",
    "echo_unavailable": "이 터미널에서는 입력 숨김(echo off)을 보장할 수 없어 중단합니다.",
    "unsafe_path": "대상 경로가 안전하지 않습니다(심볼릭 링크·일반 파일 아님·소유자/권한 문제). 아무것도 쓰지 않았습니다.",
    "missing_dir": "대상 디렉터리가 없습니다. 아무것도 쓰지 않았습니다.",
    "unreadable_env": "기존 .env 를 안전하게 읽을 수 없습니다(크기·인코딩·읽기 오류). 아무것도 쓰지 않았습니다.",
    "env_ambiguous": "기존 .env 에 이 도구가 안전하게 다룰 수 없는 줄이 있습니다(관리 이름 중복·여러 줄 값·줄 이음·CR·NUL). "
                     "파일을 직접 정리한 뒤 다시 실행하세요. 아무것도 쓰지 않았습니다.",
    "audit_unsafe": "감사 기록 경로가 안전하지 않습니다. 아무것도 쓰지 않았습니다.",
    "audit_unavailable": "감사 기록을 쓸 수 없어 .env 를 바꾸지 않았습니다.",
    "lock_busy": "같은 디렉터리에서 다른 setup 이 실행 중입니다. 아무것도 쓰지 않았습니다.",
    "concurrent_change": "입력하는 동안 .env 가 바뀌었습니다(동시 수정). 아무것도 쓰지 않았습니다. 다시 실행하세요.",
    "too_many_rejects": "허용되지 않는 입력이 반복되어 중단합니다. 아무것도 쓰지 않았습니다.",
}


class Refused(Exception):
    """아무것도 바꾸지 않고 거부. args[0] 는 MESSAGES 의 고정 코드."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class WriteFailed(Exception):
    """planned 기록 뒤 .env 쓰기가 실패. audit_recorded: failed 기록이 감사 로그에 남았는지."""

    def __init__(self, audit_recorded: bool, detail: str):
        super().__init__(detail)
        self.audit_recorded = audit_recorded
        self.detail = detail


class AuditUncertain(Exception):
    """.env 는 갱신됐지만 committed 기록을 남기지 못함."""


def _euid() -> int:
    return os.geteuid()


def say(message: str = "") -> None:
    print(message, flush=True)


# ---- 경로 안전 --------------------------------------------------------------------------------------------------
def check_private_dir(directory: Path) -> None:
    """directory 와 모든 상위 경로가 심볼릭 링크가 아닌 실제 디렉터리인지, 소유자·쓰기 권한이 안전한지 검사한다.

    대상 디렉터리: 현재 사용자 소유이고 group/other 쓰기 불가. 상위: 현재 사용자 또는 root 소유이며 group/other 쓰기가
    가능하면 sticky 여야 한다."""
    directory = Path(os.path.abspath(directory))
    uid = _euid()
    for index, part in enumerate((directory, *directory.parents)):
        try:
            st = os.lstat(part)
        except FileNotFoundError:
            raise Refused("missing_dir") from None
        except OSError:
            raise Refused("unsafe_path") from None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise Refused("unsafe_path")
        if index == 0:
            if st.st_uid != uid or st.st_mode & 0o022:
                raise Refused("unsafe_path")
        elif st.st_uid not in (uid, 0) or (st.st_mode & 0o022 and not st.st_mode & stat.S_ISVTX):
            raise Refused("unsafe_path")


def _check_regular(st: os.stat_result) -> None:
    if not stat.S_ISREG(st.st_mode) or st.st_uid != _euid():
        raise Refused("unsafe_path")


def _read_fd(fd: int, limit: int) -> bytes:
    chunks, total = [], 0
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise Refused("unreadable_env")
        chunks.append(chunk)


def read_env_snapshot(path: Path) -> bytes | None:
    """대상 .env 의 바이트(없으면 None). 상위 경로·파일 유형·소유자를 먼저 검증한다. 값은 해석하지 않는다."""
    check_private_dir(path.parent)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise Refused("unsafe_path") from None
    _check_regular(st)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        raise Refused("unsafe_path") from None
    try:
        fst = os.fstat(fd)
        _check_regular(fst)
        if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino):
            raise Refused("unsafe_path")
        try:
            return _read_fd(fd, MAX_ENV_BYTES)
        except OSError:
            raise Refused("unreadable_env") from None
    finally:
        os.close(fd)


# ---- 리터럴 dotenv 파서/병합 ------------------------------------------------------------------------------------
_ASSIGN = re.compile(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=(.*)$")
_BARE = re.compile(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*$")


def _value_open(rest: str) -> bool:
    """값이 닫히지 않은 따옴표나 줄 이음으로 끝나면 True (다음 줄로 이어질 수 있어 모호)."""
    state = ""
    i, n = 0, len(rest)
    while i < n:
        c = rest[i]
        if state == "'":
            if c == "'":
                state = ""
        elif state == '"':
            if c == "\\":
                i += 1
            elif c == '"':
                state = ""
        elif c == "\\":
            i += 1
            if i >= n:
                return True
        elif c in "'\"":
            state = c
        elif c == "#" and (i == 0 or rest[i - 1] in " \t"):
            break
        i += 1
    return bool(state)


def parse_env(text: str) -> tuple[list[str], dict[str, int]]:
    """(줄 목록, 관리 이름 → 줄 번호). 모호하면 Refused('env_ambiguous'). 쉘 실행·치환·값 해석은 없다."""
    if "\r" in text or "\x00" in text:
        raise Refused("env_ambiguous")
    lines = text.split("\n")
    index: dict[str, int] = {}
    for number, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ASSIGN.match(line)
        if match:
            name, rest = match.groups()
            if _value_open(rest.lstrip(" \t")):
                raise Refused("env_ambiguous")
            if name in MANAGED:
                if name in index:
                    raise Refused("env_ambiguous")
                index[name] = number
        else:
            bare = _BARE.match(line)
            if bare and bare.group(1) in MANAGED:
                raise Refused("env_ambiguous")
    return lines, index


def validate_secret(value: str) -> str:
    """앞뒤 공백을 제거한 값. 빈 문자열 = 건너뜀. 허용: 길이 ≤512, 영숫자와 `-_.~+/=:` 만."""
    value = value.strip()
    if len(value) > MAX_SECRET_LEN or not all(c in SECRET_CHARS for c in value):
        raise ValueError("secret_rejected")
    return value


def merge_env(text: str, updates: dict[str, str], removals: tuple[str, ...] | list[str] = ()) -> str:
    """관리 이름의 줄만 `NAME='value'` 로 바꾸거나 끝에 추가하고, removals 의 줄은 지우고, 나머지 줄은 그대로 둔다."""
    for name, value in updates.items():
        if name not in MANAGED or "'" in value or "\n" in value or "\r" in value or "\\" in value:
            raise ValueError("unsafe_update")
    if any(name not in MANAGED for name in removals) or set(updates) & set(removals):
        raise ValueError("unsafe_update")
    lines, index = parse_env(text)
    body = lines[:-1] if text.endswith("\n") else ([] if text == "" else lines)
    appended = []
    for name, value in updates.items():
        line = f"{name}='{value}'"
        if name in index:
            body[index[name]] = line
        else:
            appended.append(line)
    for number in sorted((index[name] for name in removals if name in index), reverse=True):
        del body[number]
    if appended:
        if body:
            body.append("")
        body.append("# zoop-ai setup (setup_ai_env.py): 아래 이름만 이 도구가 관리한다")
        body.extend(appended)
    merged = "\n".join(body) + "\n"
    new_lines, new_index = parse_env(merged)  # 자체 검사: 다시 파싱해도 모호하지 않고 모든 갱신 이름이 정확히 한 번, 삭제 이름은 없음
    if set(updates) - set(new_index) or set(removals) & set(new_index):
        raise ValueError("merge_invariant")
    return merged


# ---- 감사 기록 --------------------------------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ensure_private_dir(directory: Path) -> None:
    directory = Path(os.path.abspath(directory))
    if not os.path.lexists(directory):
        check_private_dir(directory.parent)
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            pass
        except OSError:
            raise Refused("audit_unsafe") from None
    check_private_dir(directory)


def audit_preflight(path: Path) -> None:
    """파일·디렉터리를 만들지 않고, 이미 있는 부분이 안전한지만 확인한다."""
    parent = Path(os.path.abspath(path)).parent
    try:
        probe = parent
        while not os.path.lexists(probe):
            probe = probe.parent
        check_private_dir(probe)
        if os.path.lexists(path):
            check_private_dir(parent)
            _check_regular(os.lstat(path))
    except Refused:
        raise Refused("audit_unsafe") from None
    except OSError:
        raise Refused("audit_unsafe") from None


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def append_audit(path: Path, record: dict) -> None:
    """검증된 private 디렉터리에 O_APPEND|O_NOFOLLOW 로 한 줄 추가하고 fsync 한다."""
    path = Path(os.path.abspath(path))
    try:
        _ensure_private_dir(path.parent)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except Refused:
        raise
    except OSError:
        raise Refused("audit_unsafe") from None
    try:
        st = os.fstat(fd)
        _check_regular(st)
        if st.st_nlink != 1:
            raise Refused("audit_unsafe")
        if st.st_mode & 0o777 != 0o600:
            os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        _write_all(fd, (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)


_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_OP = re.compile(r"^[0-9a-f]{32}$")
_KEYS = {"v", "ts", "operationId", "outcome", "target", "variableNames", "skippedNames", "profile"}


def _names(value: object, allowed: frozenset[str]) -> bool:
    return isinstance(value, list) and len(set(value)) == len(value) and all(isinstance(n, str) and n in allowed for n in value)


def _valid_record(rec: object) -> bool:
    if not isinstance(rec, dict):
        return False
    failed = rec.get("outcome") == "failed"
    removed = {"removedNames"} if "removedNames" in rec else set()  # 이전 기록에는 없다
    if set(rec) != _KEYS | removed | ({"reason"} if failed else set()):
        return False
    return (rec["v"] == 1 and isinstance(rec["ts"], str) and bool(_TS.match(rec["ts"]))
            and isinstance(rec["operationId"], str) and bool(_OP.match(rec["operationId"]))
            and rec["outcome"] in ("planned", "committed", "failed") and (not failed or rec["reason"] == "write_failed")
            and isinstance(rec["target"], str) and len(rec["target"]) <= 1024
            and _names(rec["variableNames"], MANAGED) and _names(rec["skippedNames"], frozenset(SECRET_NAMES))
            and (not removed or _names(rec["removedNames"], frozenset(RETIRED_SETTINGS)))
            and rec["profile"] in (PROFILE, LEGACY_PROFILE))


def _profile_line(profile: dict) -> str:
    return (f"profile: llm={profile['llm']} effort={profile['reasoningEffort']} verify={profile.get('verify', 'openai-compatible')} "
            f"jev={profile['jevModel']}({profile['jevMode']}) LIVE_ENABLED={profile['liveEnabled']} "
            f"GLOBAL_MAX_CALLS={profile['globalMaxCalls']}")


def read_status(path: Path) -> tuple[int, list[str]]:
    """감사 기록만 읽어 (종료 코드, 출력 줄)을 돌려준다. .env 는 열지 않으며 화이트리스트 필드만 보고한다."""
    path = Path(os.path.abspath(path))
    invalid = (EXIT_REFUSED, ["setup-status: audit-invalid", "감사 기록이 안전하지 않거나 형식이 올바르지 않습니다(내용은 출력하지 않음)."])
    if not os.path.lexists(path.parent) or not os.path.lexists(path):
        return EXIT_CANCELLED, ["setup-status: none", "감사 기록이 없습니다: 감사된 setup 작업의 증거가 없을 뿐, .env 의 상태에 대해서는 아무것도 말해 주지 않습니다."]
    try:
        check_private_dir(path.parent)
        st = os.lstat(path)
        _check_regular(st)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except (Refused, OSError):
        return invalid
    try:
        _check_regular(os.fstat(fd))
        fcntl.flock(fd, fcntl.LOCK_SH)
        data = _read_fd(fd, MAX_AUDIT_BYTES)
        text = data.decode("utf-8")
        records = [json.loads(line) for line in text.split("\n") if line]
    except (Refused, OSError, ValueError):
        return invalid
    finally:
        os.close(fd)
    if not records or not all(_valid_record(r) for r in records):
        return invalid
    last = records[-1]
    committed = sum(1 for r in records if r["outcome"] == "committed")
    state = {"committed": "committed", "failed": "failed", "planned": "uncertain"}[last["outcome"]]
    lines = [f"setup-status: {state}", f"operation: {last['operationId']}", f"time: {last['ts']}",
             f"committedOperations: {committed}",
             f"target: {'default' if last['target'] == str(DEFAULT_ENV) else 'non-default (override)'}",
             f"names: {', '.join(last['variableNames'])}",
             f"keysSkipped: {', '.join(last['skippedNames']) or '-'}",
             f"namesRemoved: {', '.join(last.get('removedNames', [])) or '-'}",
             _profile_line(last["profile"])]
    if last["profile"] == LEGACY_PROFILE:
        lines.append("마지막 작업은 이전 프로필(Jev 준비 전용, VERIFY=gpt-6-luna)을 기록했습니다. native VERIFY 프로필은 setup 을 다시 실행해야 .env 에 반영됩니다.")
    if state == "failed":
        lines.append("마지막 시도는 .env 쓰기에 실패했습니다. .env 가 바뀌지 않았을 수 있으나 값을 읽지 말고 config-check 로 확인하세요.")
    elif state == "uncertain":
        lines.append("마지막 작업이 planned 로만 남았습니다: 완료 여부가 불확실합니다(.env 가 갱신됐을 수 있음).")
    return (EXIT_OK if state == "committed" else EXIT_CANCELLED), lines


# ---- 커밋 -------------------------------------------------------------------------------------------------------
def _write_temp(directory: Path, text: str) -> Path:
    """0600 임시 파일을 만들고 쓴다. 중간에 실패하면 직접 지운 뒤 다시 던진다(secret 이 남지 않게)."""
    tmp = directory / f".env.setup-{secrets.token_hex(8)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        try:
            os.fchmod(fd, 0o600)
            _write_all(fd, text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return tmp


def ensure_distinct(env_path: Path, audit_path: Path) -> None:
    """재지정으로 .env 와 감사 기록이 같은 파일(경로 또는 inode)이 되는 것을 거부한다."""
    if Path(os.path.abspath(env_path)) == Path(os.path.abspath(audit_path)):
        raise Refused("audit_unsafe")
    try:
        a, b = os.lstat(env_path), os.lstat(audit_path)
    except OSError:
        return
    if (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino):
        raise Refused("audit_unsafe")


def _lock_dir(directory: Path) -> int:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise Refused("lock_busy") from None
    return fd


def commit(env_path: Path, audit_path: Path, snapshot: bytes | None, new_text: str, base_record: dict) -> None:
    """snapshot 이 그대로일 때만 .env 를 원자적으로 교체한다. planned → 쓰기 → committed 를 감사에 남긴다.

    Refused: 아무것도 바뀌지 않음. WriteFailed: planned 이후 쓰기 실패(롤백 없음). AuditUncertain: .env 갱신 완료,
    committed 기록 실패."""
    parent = Path(os.path.abspath(env_path)).parent
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)  # planned→committed 사이에는 Ctrl-C 로 끊기지 않게 한다
    dir_fd = None
    tmp: Path | None = None
    try:
        dir_fd = _lock_dir(parent)
        ensure_distinct(env_path, audit_path)
        if read_env_snapshot(env_path) != snapshot:
            raise Refused("concurrent_change")
        try:
            append_audit(audit_path, {**base_record, "outcome": "planned"})
        except (Refused, OSError):
            raise Refused("audit_unavailable") from None
        try:
            tmp = _write_temp(parent, new_text)
            if snapshot is None:
                os.link(tmp, env_path)  # 이미 있으면 실패: 동시 생성 덮어쓰기 방지
            else:
                os.replace(tmp, env_path)
                tmp = None
        except Exception as exc:  # noqa: BLE001 - 어떤 쓰기 실패든 failed 로 남기고 롤백 없이 보고
            detail = exc.strerror if isinstance(exc, OSError) and exc.strerror else type(exc).__name__
            try:
                append_audit(audit_path, {**base_record, "outcome": "failed", "reason": "write_failed"})
                recorded = True
            except (Refused, OSError):
                recorded = False
            raise WriteFailed(recorded, detail) from None
        try:
            fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass  # 교체는 이미 원자적으로 끝났다. 디렉터리 fsync 는 best-effort.
        try:
            append_audit(audit_path, {**base_record, "outcome": "committed"})
        except (Refused, OSError):
            raise AuditUncertain() from None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        if dir_fd is not None:
            os.close(dir_fd)
        signal.signal(signal.SIGINT, previous)


# ---- 대화형 실행 ------------------------------------------------------------------------------------------------
def _confirm(prompt: str) -> bool:
    return input(f"  {prompt} [yes/N]: ").strip().lower() in ("y", "yes")


def _ask_secret(name: str) -> str:
    for _ in range(3):
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                raw = getpass.getpass(f"  {name} (hidden input; Enter = skip): ")
            except getpass.GetPassWarning:
                raise Refused("echo_unavailable") from None
        try:
            return validate_secret(raw)
        except ValueError:
            say("  허용되지 않는 문자가 있거나 너무 깁니다(값은 표시하지 않음). 다시 입력하거나 Enter 로 건너뛰세요.")
        finally:
            raw = ""
    raise Refused("too_many_rejects")


def _commit_and_report(env_path: Path, audit_path: Path, snapshot: bytes | None, new_text: str, record: dict, skipped: list[str]) -> int:
    try:
        commit(env_path, audit_path, snapshot, new_text, record)
    except WriteFailed as exc:
        print(f"\n  .env 쓰기에 실패했습니다({exc.detail}). 롤백은 하지 않았고 임시 파일 정리를 시도했습니다. 정리 오류가 겹치면 대상 폴더에 0600 임시 파일이 남을 수 있습니다.", file=sys.stderr)
        print("  감사 기록에 failed 가 남았습니다." if exc.audit_recorded
              else "  ※ failed 기록도 남기지 못했습니다: 감사 기록에는 planned 만 있어 완료 여부가 불확실합니다.", file=sys.stderr)
        return EXIT_WRITE_FAILED
    except AuditUncertain:
        print("\n  .env 는 갱신됐지만 감사 기록의 committed 를 남기지 못했습니다: 감사 완료 여부가 불확실합니다.", file=sys.stderr)
        print(f"  값은 읽지 말고 --status 와 `zoop-ai config-check` 로 확인하세요. 대상: {env_path}", file=sys.stderr)
        return EXIT_AUDIT_UNCERTAIN
    say(f"\n  완료: {env_path} (0600) 를 갱신했습니다.")
    say(f"  쓴 이름: {', '.join(record['variableNames'])}")
    say(f"  건너뛴 key(기존 값 유지): {', '.join(skipped) or '없음'}")
    removed = record.get("removedNames", [])
    say(f"  삭제한 줄(이름만): {', '.join(removed) or '없음'}")
    say("  live 는 꺼진 상태입니다(LIVE_ENABLED=0, GLOBAL_MAX_CALLS=0). 이 설정은 호출·지출을 승인하지 않습니다.")
    say("  확인: python3 ai/worker/scripts/setup_ai_env.py --status")
    return EXIT_OK


def run_setup(env_path: Path, audit_path: Path, default_target: bool) -> int:
    say("Zoop AI worker 로컬 설정 — 사람이 직접 실행하는 도구입니다.")
    say("네트워크 요청·모델 호출·프로세스 실행·key 검증을 하지 않습니다. 입력한 key 는 화면·로그·감사 기록에 남지 않습니다.")
    say()
    say(f"  대상 .env : {env_path}" + ("" if default_target else "   (※ 기본 대상이 아님: 직접 지정됨)"))
    say(f"  감사 기록 : {audit_path}   (시각·작업 ID·대상·변수 이름·고정 프로필·결과만, 값 없음, 0600)")
    say()
    say("  기록할 고정 프로필 (비밀 아님)")
    say(f"    LLM  : {LLM_MODEL}, reasoning effort = {LLM_EFFORT}  (문서 요약·감성·briefing-outlook 세 단계)")
    say(f"    VERIFY: native TypeSafe Jev {JEV_MODEL} (고정 버전, 별칭 아님). ZOOP_AI_VERIFY_PROVIDER={VERIFY_PROVIDER},")
    say("           모델 이름은 TYPESAFE_VALIDATION_MODEL, reasoning effort 는 해당 없음. 문서 작업의 생성은 위 LLM, 검증만 Jev 가 맡는다.")
    say(f"           쓰이지 않는 {', '.join(RETIRED_SETTINGS)} 줄이 .env 에 있으면 삭제한다({LLM_MODEL} 이 VERIFY 를 맡는다는 오해 방지).")
    say("    live : ZOOP_AI_LIVE_ENABLED=0, ZOOP_AI_GLOBAL_MAX_CALLS=0 으로 강제한다(기존 값이 있어도 덮어씀).")
    say("           key 등록은 지출을 승인하지 않는다. live 와 호출 상한은 별도 승인 뒤에 사람이 따로 바꾼다.")
    say("    그 외: ZOOP_AI_PROVIDER=openai-compatible, ZOOP_AI_BASE_URL=https://api.openai.com/v1,")
    say("           TYPESAFE_BASE_URL=https://api.typesafe.ai/v1  (key 가 예상 밖 주소로 가지 않도록 고정)")
    say(f"  갱신하는 이름: {', '.join(n for n, _ in PUBLIC_SETTINGS)}")
    say(f"  입력 시 갱신하는 이름: {', '.join(SECRET_NAMES)}   (Enter 만 누르면 건너뛰고 기존 값은 그대로 둔다)")
    say("  관련 없는 기존 줄은 그대로 보존한다. 취소: Ctrl-C 또는 Ctrl-D — 그 전에는 아무것도 쓰지 않는다.")
    say()

    ensure_distinct(env_path, audit_path)
    audit_preflight(audit_path)
    snapshot = read_env_snapshot(env_path)
    text = snapshot.decode("utf-8") if snapshot is not None else ""
    _, present = parse_env(text)
    retired = sorted(name for name in RETIRED_SETTINGS if name in present)
    say(f"  기존 .env: {'있음(내용은 읽지만 출력하지 않음)' if snapshot is not None else '없음(새로 만듦, 0600)'}")
    if retired:
        say(f"  삭제할 줄(이름만 표시, 값은 읽어도 출력하지 않음): {', '.join(retired)}")
    if not _confirm(f"위 대상 {env_path} 에 기록하는 것에 동의합니까?"):
        say("  동의하지 않았습니다 — 아무것도 쓰지 않았습니다.")
        return EXIT_CANCELLED
    say()

    updates = dict(PUBLIC_SETTINGS)
    skipped = []
    for name, label in SECRET_PROMPTS:
        say(f"  {label}")
        value = _ask_secret(name)
        if value:
            updates[name] = value
        else:
            skipped.append(name)
        value = ""
    new_text = merge_env(text, updates, retired)
    record = {"v": 1, "ts": _now(), "operationId": secrets.token_hex(16), "target": str(env_path),
              "variableNames": sorted(updates), "skippedNames": sorted(skipped), "removedNames": retired, "profile": PROFILE}
    updates.clear()
    # 커밋이 시작된 뒤에는 Ctrl-C 가 "아무것도 쓰지 않았습니다" 보고를 만들 수 없게 SIGINT 를 무시한다.
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        return _commit_and_report(env_path, audit_path, snapshot, new_text, record, skipped)
    finally:
        signal.signal(signal.SIGINT, previous)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # argparse 는 잘못된 인수 값을 그대로 출력하므로 값은 숨긴다
        self.print_usage(sys.stderr)
        print("인수 오류: 알 수 없거나 잘못된 인수입니다(값은 표시하지 않음). key 는 인수로 받지 않고 숨김 프롬프트로만 입력합니다.", file=sys.stderr)
        raise SystemExit(EXIT_REFUSED)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        allow_abbrev=False,
        description="Zoop AI worker .env 설정 (사람이 터미널에서 실행). key 는 숨김 프롬프트로만 입력하며 인수로 받지 않는다.")
    parser.add_argument("--status", action="store_true", help="감사 기록만 읽어 마지막 setup 의 완료 여부를 보고한다(.env 는 열지 않음)")
    parser.add_argument("--env-file", type=Path, help="테스트/운영자용 대상 재지정. 지정하면 --audit-file 도 필요하다")
    parser.add_argument("--audit-file", type=Path, help="테스트/운영자용 감사 기록 경로 재지정")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if args.env_file is not None and args.audit_file is None and not args.status:
        print("거부: --env-file 을 지정하면 기본 감사 기록을 건드리지 않도록 --audit-file 도 함께 지정해야 합니다.", file=sys.stderr)
        return EXIT_REFUSED
    audit_path = Path(os.path.abspath(args.audit_file or DEFAULT_AUDIT))
    if args.status:
        code, lines = read_status(audit_path)
        say("\n".join(lines))
        return code
    env_path = Path(os.path.abspath(args.env_file or DEFAULT_ENV))
    os.umask(0o077)
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise Refused("not_tty")
        return run_setup(env_path, audit_path, args.env_file is None)
    except Refused as exc:
        print(f"\n  거부: {MESSAGES[exc.code]}", file=sys.stderr)
        return EXIT_REFUSED
    except (KeyboardInterrupt, EOFError):
        print("\n  중단됨 — 아무것도 쓰지 않았습니다.", file=sys.stderr)
        return EXIT_CANCELLED
    except UnicodeDecodeError:
        print(f"\n  거부: {MESSAGES['unreadable_env']}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
