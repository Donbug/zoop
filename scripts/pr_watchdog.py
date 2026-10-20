"""Local, read-only GitHub pull request review watchdog (standard library + the existing ``gh`` login).

The watcher only reads open pull requests of an exact repository allowlist, plus the PR comments that may
@-mention you, through ``gh api --method GET``. It never calls a model, writes to GitHub, posts reviews or
starts agents: it keeps a local baseline, prints meaningful change events and an actionable pending review
queue ordered formal review request > @-mention > discovered.

PR titles, labels, authors, review requests and comment authors are untrusted GitHub data. They are printed as
quoted single-line data and must never be treated as instructions. Comment bodies are inspected in memory only;
the state keeps just the type, id, author, updatedAt and URL of a comment that mentions you.

State lives in an explicit operator directory outside this repository (``--state-dir`` or
``ZOOP_PR_WATCHDOG_STATE_DIR``): ``state.json`` (baseline, acknowledgements, pauses, mention metadata),
``status.json`` (liveness only) and two lock files, all mode 0600 in a 0700 directory. No ``.env`` is read.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = "zoop.pr-watchdog.state/v2"
LEGACY_STATE_SCHEMA = "zoop.pr-watchdog.state/v1"     # still read and migrated losslessly; never written
STATUS_SCHEMA = "zoop.pr-watchdog.status/v1"
STATE_DIR_ENV = "ZOOP_PR_WATCHDOG_STATE_DIR"
DEFAULT_REPOS = ("Donbug/zoop", "Donbug/Zoop-Infra")
DEFAULT_INTERVAL = 300
MIN_INTERVAL = 30
DEFAULT_GH_TIMEOUT = 30
PAGE_SIZE = 100
MAX_PAGES = 30                      # 3000 open PRs; more is treated as an incomplete snapshot
MAX_GH_BYTES = 16 * 1024 * 1024
MAX_STATE_BYTES = 16 * 1024 * 1024
LOCK_WAIT_SECONDS = 10
MENTION_MAX_PAGES = 30              # per comment endpoint and scan (3000 comments); more is treated as an incomplete read
MENTION_INIT_LOOKBACK = timedelta(days=30)     # first read of a repository/endpoint looks back this far
MENTION_OVERLAP = timedelta(seconds=120)       # the watermark trails the newest comment so a late-visible one is re-read
MAX_COMMENT_CHARS = 65536
MENTION_KINDS = ("issue-comment", "review-comment")
MENTION_ENDPOINTS = {"issue-comment": "issues/comments", "review-comment": "pulls/comments"}
MENTION_LABELS = {"issue-comment": "general PR comments", "review-comment": "inline review comments"}

REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
TEAM_RE = REPO_RE
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
REF_RE = re.compile(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]{0,8})")
HEX40_RE = re.compile(r"[0-9a-f]{40}")
HEAD_PREFIX_RE = re.compile(r"[0-9a-f]{7,40}")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")
TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
COMMENT_TARGET_RE = re.compile(r"https?://[^/\s]+/repos/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/(issues|pulls)/([1-9][0-9]{0,8})")
FENCE_OPEN_RE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
QUOTE_RE = re.compile(r" {0,3}>")
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)

EXIT_OK, EXIT_FATAL, EXIT_USAGE, EXIT_INCOMPLETE = 0, 1, 2, 3


class StateError(Exception):
    """Persisted state or its directory is corrupt or unsafe; never overwritten."""


class UserError(Exception):
    """A local operation was refused."""


class GhError(Exception):
    """A GitHub read failed or returned unusable data; the prior baseline stays untouched."""


class Interrupted(Exception):
    """SIGINT/SIGTERM arrived while work was in flight."""


class StopFlag:
    """Lock-free stop request, safe to set from a signal handler (threading.Event can self-deadlock there)."""

    def __init__(self) -> None:
        self._flag = False

    def set(self) -> None:
        self._flag = True

    def is_set(self) -> bool:
        return self._flag

    def wait(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while not self._flag:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.2, remaining))
        return True


# --------------------------------------------------------------------------- text helpers

def clean(value: object, limit: int) -> str:
    """Single-line, control-character-free, bounded text for untrusted data."""
    text = " ".join(CONTROL_RE.sub(" ", str(value)).split())
    return text[:limit]


def quote(value: object, limit: int = 200) -> str:
    return json.dumps(clean(value, limit), ensure_ascii=False)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- GitHub reads

class GhClient:
    """Read-only ``gh api --method GET`` runner with a hard timeout and cooperative cancellation."""

    def __init__(self, gh_path: str, timeout: int, stop: "StopFlag"):
        self.gh_path, self.timeout, self.stop = gh_path, timeout, stop

    def get_json(self, endpoint: str) -> object:
        argv = [self.gh_path, "api", "--method", "GET", endpoint]
        env = {**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1",
               "GH_NO_UPDATE_NOTIFIER": "1", "GH_SPINNER_DISABLED": "1"}
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=env)
        except OSError as error:
            raise GhError(f"cannot start gh: {clean(error, 120)}") from None
        deadline = time.monotonic() + self.timeout
        while True:
            if self.stop.is_set():
                self._kill(process)
                raise Interrupted()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill(process)
                raise GhError(f"gh timed out after {self.timeout}s")
            try:
                out, err = process.communicate(timeout=min(0.5, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if self.stop.is_set():
            raise Interrupted()
        if process.returncode != 0:
            raise GhError(f"gh exited {process.returncode}: {clean(err.decode('utf-8', 'replace'), 200)}")
        if len(out) > MAX_GH_BYTES:
            raise GhError("gh output exceeded the size bound")
        try:
            return json.loads(out)
        except ValueError:
            raise GhError("gh returned invalid JSON") from None

    @staticmethod
    def _kill(process: subprocess.Popen) -> None:
        process.kill()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def lookup_login(client) -> str:
    data = client.get_json("user")
    login = data.get("login") if isinstance(data, dict) else None
    if not isinstance(login, str) or not LOGIN_RE.fullmatch(login):
        raise GhError("could not read the authenticated gh login")
    return login          # only the login is kept; no other profile metadata is retained


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected string")
    return value


def normalize_pr(repo: str, raw: object) -> dict:
    """Validate one REST pull request object into the compact record kept in state."""
    try:
        number = raw["number"]                                       # type: ignore[index]
        if type(number) is not int or number < 1:
            raise ValueError("number")
        head, base = raw["head"], raw["base"]                        # type: ignore[index]
        head_sha, base_sha = _text(head["sha"]), _text(base["sha"])
        if not (HEX40_RE.fullmatch(head_sha) and HEX40_RE.fullmatch(base_sha)):
            raise ValueError("sha")
        draft = raw.get("draft", False)                              # type: ignore[union-attr]
        if not isinstance(draft, bool):
            raise ValueError("draft")
        user = raw.get("user")                                       # type: ignore[union-attr]
        author = _text(user["login"]) if isinstance(user, dict) else "ghost"
        owner = repo.split("/", 1)[0]
        requested = {"user:" + clean(_text(item["login"]), 100)
                     for item in raw.get("requested_reviewers") or []}     # type: ignore[union-attr]
        requested |= {f"team:{owner}/" + clean(_text(item["slug"]), 100)
                      for item in raw.get("requested_teams") or []}        # type: ignore[union-attr]
        labels = {clean(_text(item["name"]), 60) for item in raw.get("labels") or []}  # type: ignore[union-attr]
        head_ref = head.get("ref")
        return {
            "number": number,
            "title": clean(_text(raw["title"]), 200),                # type: ignore[index]
            "url": f"https://github.com/{repo}/pull/{number}",
            "author": clean(author, 100),
            "headRef": clean(head_ref, 200) if isinstance(head_ref, str) else "",
            "head": head_sha,
            "baseRef": clean(_text(base["ref"]), 200),
            "baseSha": base_sha,
            "draft": draft,
            "requested": sorted(requested),
            "labels": sorted(labels)[:30],
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        raise GhError(f"{repo}: malformed pull request entry in the GitHub response") from None


def fetch_open_prs(client, repo: str) -> list[dict]:
    """Complete open-PR snapshot for one repository, or GhError. Never a partial list."""
    found: dict[int, dict] = {}
    for page in range(1, MAX_PAGES + 1):
        data = client.get_json(f"repos/{repo}/pulls?state=open&per_page={PAGE_SIZE}&page={page}")
        if not isinstance(data, list):
            raise GhError(f"{repo}: unexpected GitHub response shape (not a pull request list)")
        for raw in data:
            pr = normalize_pr(repo, raw)
            found.setdefault(pr["number"], pr)
        if len(data) < PAGE_SIZE:
            return [found[number] for number in sorted(found)]
    raise GhError(f"{repo}: more than {MAX_PAGES * PAGE_SIZE} open pull requests; snapshot refused as incomplete")


# --------------------------------------------------------------------------- mention detection

MENTION_SUFFIX = " mentions"


def mention_key(repo: str) -> str:
    """Error/status name of a repository's comment reads (a space never occurs in an OWNER/NAME)."""
    return repo + MENTION_SUFFIX


def preserved_note(name: str) -> str:
    return "previous mention state preserved" if name.endswith(MENTION_SUFFIX) else "previous baseline preserved"


@dataclass
class CommentRead:
    """One complete endpoint read: identity-only comment records and the newest ``updated_at`` seen."""
    comments: list[dict]
    newest: str | None


def mention_pattern(login: str) -> "re.Pattern[str]":
    """``@login`` on an exact, case-insensitive username boundary.

    Not matched: an e-mail address (``a@login.com``), a longer name that merely starts with it (``@loginx``,
    ``@login-bot``), an ``@login/team`` mention, a domain-like ``@login.com`` or an escaped ``\\@login``.
    Trailing sentence punctuation and non-ASCII text (``@login님``) still match.
    """
    return re.compile(rf"(?<![A-Za-z0-9_.+%/@\\-])@{re.escape(login)}(?![A-Za-z0-9_@-]|[./][A-Za-z0-9])",
                      re.ASCII | re.IGNORECASE)


def visible_text(body: str) -> str:
    """Comment text without fenced code, block quotes and inline code, where a mention is only an example or a quotation.

    Deterministic and line based; indented code blocks and lazy block-quote continuation lines are not recognised.
    """
    kept: list[str] = []
    fence = ""
    for line in body[:MAX_COMMENT_CHARS].replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if fence:
            marker = line.strip()
            if marker and set(marker) == {fence[0]} and len(marker) >= len(fence):
                fence = ""
            continue
        opening = FENCE_OPEN_RE.fullmatch(line)
        if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            fence = opening.group(1)
            continue
        if QUOTE_RE.match(line):
            continue
        kept.append(line)
    paragraphs = re.split(r"\n[ \t]*\n", "\n".join(kept))      # a code span never crosses a paragraph
    return "\n\n".join(INLINE_CODE_RE.sub(" ", paragraph) for paragraph in paragraphs)


def mentions_login(body: str, pattern: "re.Pattern[str]") -> bool:
    return pattern.search(visible_text(body)) is not None


def comment_url(repo: str, number: int, kind: str, comment_id: int) -> str:
    anchor = "issuecomment-" if kind == "issue-comment" else "discussion_r"
    return f"https://github.com/{repo}/pull/{number}#{anchor}{comment_id}"


def trailing_watermark(updated: str) -> str:
    """Resume point for the next ``since`` read: the newest ``updated_at`` seen, minus the overlap."""
    return iso(parse_iso(updated) - MENTION_OVERLAP)


def normalize_comment(repo: str, kind: str, raw: object, pattern: "re.Pattern[str]", login: str) -> dict:
    """Reduce one REST comment to its identity plus a mention flag; the body is inspected here and never returned."""
    target_field, segment = ("issue_url", "issues") if kind == "issue-comment" else ("pull_request_url", "pulls")
    try:
        comment_id = raw["id"]                                       # type: ignore[index]
        if type(comment_id) is not int or comment_id < 1:
            raise ValueError("id")
        updated = _text(raw["updated_at"])                           # type: ignore[index]
        if not TIMESTAMP_RE.fullmatch(updated):
            raise ValueError("updated_at")
        trailing_watermark(updated)                                  # impossible or out-of-range dates are malformed
        target = COMMENT_TARGET_RE.fullmatch(_text(raw[target_field]))    # type: ignore[index]
        if not target or target.group(1).casefold() != repo.casefold() or target.group(2) != segment:
            raise ValueError("target")
        user = raw.get("user")                                       # type: ignore[union-attr]
        author = _text(user["login"]) if isinstance(user, dict) else "ghost"
        body = raw.get("body")                                       # type: ignore[union-attr]
        if body is not None and not isinstance(body, str):
            raise ValueError("body")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise GhError(f"{repo}: malformed comment entry in the GitHub response") from None
    mention = bool(body) and author.casefold() != login.casefold() and mentions_login(body, pattern)
    return {"type": kind, "id": comment_id, "number": int(target.group(3)), "author": clean(author, 100),
            "updatedAt": updated, "mention": mention}


def fetch_comments(client, repo: str, kind: str, since: str, pattern: "re.Pattern[str]", login: str) -> CommentRead:
    """Every comment of one kind updated since ``since``, or GhError. Never a partial read.

    Ordered by creation so concurrent edits cannot shift items between pages; ``since`` filters on ``updated_at``.
    """
    base = f"repos/{repo}/{MENTION_ENDPOINTS[kind]}?sort=created&direction=asc&since={since}&per_page={PAGE_SIZE}"
    found: dict[int, dict] = {}
    for page in range(1, MENTION_MAX_PAGES + 1):
        data = client.get_json(f"{base}&page={page}")
        if not isinstance(data, list):
            raise GhError(f"{repo}: unexpected GitHub response shape (not a {kind} list)")
        for raw in data:
            comment = normalize_comment(repo, kind, raw, pattern, login)
            found.setdefault(comment["id"], comment)
        if len(data) < PAGE_SIZE:
            comments = sorted(found.values(), key=lambda item: (item["updatedAt"], item["id"]))
            return CommentRead(comments, max((item["updatedAt"] for item in comments), default=None))
    raise GhError(f"{repo}: more than {MENTION_MAX_PAGES * PAGE_SIZE} {kind}s updated since {since}; read refused as incomplete")


def read_mentions(client, repo: str, login: str, marks: dict, now: datetime) -> dict:
    """Both comment endpoints of one repository; a failed endpoint keeps its error text instead of data."""
    pattern = mention_pattern(login)
    reads: dict = {}
    for kind in MENTION_KINDS:
        since = marks.get(kind) or iso(now - MENTION_INIT_LOOKBACK)
        try:
            reads[kind] = fetch_comments(client, repo, kind, since, pattern, login)
        except GhError as error:
            reads[kind] = str(error)
    return reads


# --------------------------------------------------------------------------- state

def empty_state() -> dict:
    return {"schema": STATE_SCHEMA, "viewer": None, "prs": {}, "reviewed": {}, "paused": {},
            "mentions": {}, "mentionWatermarks": {}}


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise StateError(f"state file is invalid ({message}); refusing to use or overwrite it")


def _is_int(value: object, minimum: int) -> bool:
    return type(value) is int and value >= minimum


def _str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


STATE_KEYS = {"schema", "viewer", "prs", "reviewed", "paused", "mentions", "mentionWatermarks"}
LEGACY_STATE_KEYS = STATE_KEYS - {"mentions", "mentionWatermarks"}


def validate_state(data: object, *, legacy: bool = False) -> None:
    """Strict structural check; ``legacy`` accepts exactly the v1 layout (read, then migrated by ``migrate_state``)."""
    _need(isinstance(data, dict) and data.get("schema") == (LEGACY_STATE_SCHEMA if legacy else STATE_SCHEMA), "unsupported schema")
    assert isinstance(data, dict)
    _need(set(data) == (LEGACY_STATE_KEYS if legacy else STATE_KEYS), "unexpected top-level keys")
    _need(data["viewer"] is None or isinstance(data["viewer"], str), "viewer")
    for field_name in ("prs", "reviewed", "paused"):
        _need(isinstance(data[field_name], dict), field_name)
    for key, rec in data["prs"].items():
        _need(isinstance(rec, dict), f"prs[{key}]")
        text_fields = ("repo", "title", "url", "author", "headRef", "baseRef", "firstSeenAt")
        _need(all(isinstance(rec.get(name), str) for name in text_fields), f"prs[{key}] text fields")
        _need(REPO_RE.fullmatch(rec["repo"]) is not None and _is_int(rec.get("number"), 1)
              and key == f"{rec['repo']}#{rec['number']}", f"prs[{key}] identity")
        _need(all(isinstance(rec.get(name), str) and HEX40_RE.fullmatch(rec[name]) for name in ("head", "baseSha")),
              f"prs[{key}] sha")
        _need(isinstance(rec.get("draft"), bool) and isinstance(rec.get("explicit"), bool), f"prs[{key}] flags")
        _need(_str_list(rec.get("requested")) and _str_list(rec.get("labels")), f"prs[{key}] lists")
        _need(_is_int(rec.get("explicitSeq"), 0), f"prs[{key}] explicitSeq")
    for key, rec in data["reviewed"].items():
        _need(REF_RE.fullmatch(key) is not None and isinstance(rec, dict), f"reviewed[{key}]")
        _need(isinstance(rec.get("head"), str) and HEX40_RE.fullmatch(rec["head"]) is not None
              and isinstance(rec.get("baseSha"), str) and HEX40_RE.fullmatch(rec["baseSha"]) is not None
              and isinstance(rec.get("baseRef"), str) and isinstance(rec.get("ackedAt"), str)
              and _is_int(rec.get("explicitSeq"), 0) and (legacy or _is_int(rec.get("mentionSeq"), 0)),
              f"reviewed[{key}] fields")
    for key, rec in data["paused"].items():
        _need(REF_RE.fullmatch(key) is not None and isinstance(rec, dict)
              and isinstance(rec.get("since"), str) and isinstance(rec.get("reason"), str), f"paused[{key}]")
    if legacy:
        return
    for key, bucket in data["mentions"].items():
        _need(REF_RE.fullmatch(key) is not None and isinstance(bucket, dict) and set(bucket) == {"seq", "comments"}
              and _is_int(bucket["seq"], 0) and isinstance(bucket["comments"], dict), f"mentions[{key}]")
        for name, item in bucket["comments"].items():
            _need(isinstance(item, dict) and item.get("type") in MENTION_KINDS and _is_int(item.get("id"), 1)
                  and name == f"{item['type']}:{item['id']}"
                  and all(isinstance(item.get(field_name), str) for field_name in ("author", "updatedAt", "url"))
                  and TIMESTAMP_RE.fullmatch(item["updatedAt"]) is not None and _is_int(item.get("gen"), 0),
                  f"mentions[{key}][{name}]")
    for repo, marks in data["mentionWatermarks"].items():
        _need(REPO_RE.fullmatch(repo) is not None and isinstance(marks, dict)
              and all(kind in MENTION_KINDS and isinstance(value, str) and TIMESTAMP_RE.fullmatch(value) is not None
                      for kind, value in marks.items()), f"mentionWatermarks[{repo}]")


def migrate_state(data: object) -> dict:
    """Current-schema state from parsed JSON. A v1 file is migrated losslessly: every known v1 field is kept and
    the mention fields start empty, so acknowledgements and pauses survive the upgrade."""
    if isinstance(data, dict) and data.get("schema") == LEGACY_STATE_SCHEMA:
        validate_state(data, legacy=True)
        migrated = copy.deepcopy(data)
        migrated["schema"] = STATE_SCHEMA
        migrated["mentions"], migrated["mentionWatermarks"] = {}, {}
        for rec in migrated["reviewed"].values():
            rec["mentionSeq"] = 0
        data = migrated
    validate_state(data)
    return data                                     # type: ignore[return-value]


def atomic_write(path: Path, text: str) -> None:
    """Temp file in the same directory, fsync, rename; the target is never partially written."""
    temp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        temp.unlink()
    except FileNotFoundError:
        pass
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise
    try:
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        pass


class Store:
    """Owner-only state directory holding the baseline, local overrides and liveness record."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.state_path = directory / "state.json"
        self.status_path = directory / "status.json"
        self.lock_path = directory / "state.lock"
        self.watch_lock_path = directory / "watch.lock"
        self.legacy_backup_path = directory / "state.v1.bak"

    @classmethod
    def open(cls, argument: str, *, create: bool) -> "Store":
        directory = Path(os.path.expanduser(argument)).resolve()
        if directory == REPO_ROOT or REPO_ROOT in directory.parents:
            raise StateError(f"state directory must be outside the repository ({REPO_ROOT}): operator state is never tracked")
        if not directory.exists():
            if not create:
                return cls(directory)
            directory.mkdir(parents=True, mode=0o700)
            os.chmod(directory, 0o700)
        info = directory.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise StateError(f"state directory {directory} must be a directory owned by you and not group/world writable")
        return cls(directory)

    def exists(self) -> bool:
        return self.directory.is_dir()

    @contextmanager
    def locked(self) -> Iterator[None]:
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            deadline = time.monotonic() + LOCK_WAIT_SECONDS
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise StateError("state lock is busy; another pr_watchdog command is writing") from None
                    time.sleep(0.05)
            yield
        finally:
            os.close(descriptor)       # closing releases the advisory lock

    def acquire_watch_lock(self) -> int | None:
        descriptor = os.open(self.watch_lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            return None
        return descriptor

    def watcher_running(self) -> bool:
        try:
            descriptor = os.open(self.watch_lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return False
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            os.close(descriptor)
        return False

    def load(self) -> dict:
        try:
            descriptor = os.open(self.state_path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return empty_state()
        except OSError as error:
            raise StateError(f"cannot open state file safely: {clean(error, 120)}") from None
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise StateError(f"state file {self.state_path} must be a regular file owned by you with mode 0600")
            if info.st_size > MAX_STATE_BYTES:
                raise StateError("state file exceeds the size bound; refusing to use or overwrite it")
            raw = stream.read()
        try:
            data = json.loads(raw)
        except ValueError:
            raise StateError("state file is not valid JSON; refusing to use or overwrite it") from None
        return migrate_state(data)

    def save(self, state: dict) -> None:
        validate_state(state)
        self._keep_legacy_copy()
        atomic_write(self.state_path, json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    def _keep_legacy_copy(self) -> None:
        """Before the first v2 write, keep the exact v1 bytes once (never overwritten) so an older watchdog can be restored."""
        try:
            descriptor = os.open(self.state_path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return
        with os.fdopen(descriptor, "rb") as stream:
            raw = stream.read(MAX_STATE_BYTES + 1)
        try:
            legacy = json.loads(raw).get("schema") == LEGACY_STATE_SCHEMA
        except (ValueError, AttributeError):
            return
        if legacy and not self.legacy_backup_path.exists():
            atomic_write(self.legacy_backup_path, raw.decode("utf-8"))

    def read_status(self) -> dict:
        """Liveness record is advisory: unreadable content is ignored and later rewritten."""
        try:
            descriptor = os.open(self.status_path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                data = json.loads(stream.read(MAX_STATE_BYTES))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) and data.get("schema") == STATUS_SCHEMA else {}

    def write_status(self, document: dict) -> None:
        atomic_write(self.status_path, json.dumps(document, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- change detection

@dataclass(frozen=True)
class Config:
    repos: tuple[str, ...]
    self_login: str | None
    teams: tuple[str, ...]
    interval: int


def is_explicit(requested: list[str], viewer: str, teams: tuple[str, ...]) -> bool:
    wanted = {f"user:{viewer}".casefold()} | {f"team:{team}".casefold() for team in teams}
    return any(item.casefold() in wanted for item in requested)


def _event(kind: str, rec: dict, **extra: object) -> dict:
    keys = ("repo", "number", "author", "title", "head", "baseRef", "baseSha", "draft", "explicit")
    return {"kind": kind, "key": f"{rec['repo']}#{rec['number']}", **{name: rec[name] for name in keys}, **extra}


def apply_snapshot(state: dict, repo: str, prs: list[dict], viewer: str, teams: tuple[str, ...], now: str) -> list[dict]:
    """Merge one complete, valid repository snapshot into ``state`` and return the change events."""
    events: list[dict] = []
    existing = {key: rec for key, rec in state["prs"].items() if rec["repo"] == repo}
    seen: set[str] = set()
    for pr in prs:
        key = f"{repo}#{pr['number']}"
        seen.add(key)
        explicit = is_explicit(pr["requested"], viewer, teams)
        old = existing.get(key)
        rec = {**pr, "repo": repo, "explicit": explicit}
        if old is None:
            rec["explicitSeq"] = 1 if explicit else 0
            rec["firstSeenAt"] = now
            events.append(_event("new-pr", rec, requested=rec["requested"]))
        else:
            rec["firstSeenAt"] = old["firstSeenAt"]
            rec["explicitSeq"] = old["explicitSeq"] + (1 if explicit and not old["explicit"] else 0)
            if old["head"] != rec["head"]:
                events.append(_event("new-head", rec, previousHead=old["head"]))
            if (old["baseRef"], old["baseSha"]) != (rec["baseRef"], rec["baseSha"]):
                events.append(_event("base-changed", rec, previousBase=f"{old['baseRef']}@{old['baseSha'][:10]}"))
            added = sorted(set(rec["requested"]) - set(old["requested"]))
            if added:
                events.append(_event("review-requested", rec, added=added))
            if old["draft"] and not rec["draft"]:
                events.append(_event("ready-for-review", rec))
            elif rec["draft"] and not old["draft"]:
                events.append(_event("converted-to-draft", rec))
        state["prs"][key] = rec
    for key, old in existing.items():
        if key not in seen:                      # only reachable from a complete, valid snapshot
            del state["prs"][key]
            state["mentions"].pop(key, None)
            events.append(_event("closed", old))
    return events


def apply_mentions(state: dict, repo: str, kind: str, read: CommentRead) -> list[dict]:
    """Merge one complete comment read into the tracked mentions and return the new/edited-mention events.

    A comment edited to drop the mention (or authored by you) is forgotten silently: no event. A new or edited mention
    whose ``updatedAt`` is not after the PR's acknowledgement is historical: it is tracked so a later edit is noticed,
    but it is already handled and gets generation 0. Any other change takes the next per-PR generation, which is what
    re-queues an acknowledged head. A comment seen again unchanged is a no-op. Deleted comments cannot be observed by
    the incremental ``since`` read; their record stays until the PR closes or is acknowledged.
    """
    events: list[dict] = []
    for comment in read.comments:
        key = f"{repo}#{comment['number']}"
        pr = state["prs"].get(key)
        if pr is None:
            continue                                  # an issue, or a pull request that is not open
        name = f"{kind}:{comment['id']}"
        bucket = state["mentions"].get(key)
        known = bucket["comments"].get(name) if bucket else None
        if not comment["mention"]:
            if known:
                del bucket["comments"][name]
                if not bucket["comments"]:
                    del state["mentions"][key]
            continue
        if known and known["updatedAt"] >= comment["updatedAt"]:          # unchanged, or an older read racing a newer one
            continue
        reviewed = state["reviewed"].get(key)
        if bucket is None:
            bucket = state["mentions"][key] = {"seq": 0, "comments": {}}
        if reviewed and comment["updatedAt"] <= reviewed["ackedAt"]:
            generation = 0
        else:
            generation = bucket["seq"] = max(bucket["seq"], reviewed["mentionSeq"] if reviewed else 0) + 1
        record = {"type": kind, "id": comment["id"], "author": comment["author"], "updatedAt": comment["updatedAt"],
                  "url": comment_url(repo, comment["number"], kind, comment["id"]), "gen": generation}
        bucket["comments"][name] = record
        if generation:
            events.append(_event("mention", pr, mention=record))
    if read.newest is not None:
        candidate = trailing_watermark(read.newest)
        marks = state["mentionWatermarks"].setdefault(repo, {})
        if candidate > marks.get(kind, ""):
            marks[kind] = candidate
    return events


def unhandled_mentions(state: dict, key: str) -> list[dict]:
    """Mention comments newer than this PR's acknowledged mention generation (all of them if it was never acknowledged)."""
    bucket = state["mentions"].get(key)
    if not bucket:
        return []
    acknowledged = state["reviewed"].get(key, {}).get("mentionSeq", 0)
    return sorted((item for item in bucket["comments"].values() if item["gen"] > acknowledged),
                  key=lambda item: (item["updatedAt"], item["id"]))


PRIORITY_RANK = {"explicit": 0, "mention": 1, "ready": 2}


def pending_queue(state: dict, repos: tuple[str, ...], viewer: str | None) -> list[dict]:
    """Open, non-own, unpaused PRs with an unhandled review trigger, ordered formal request > mention > discovered.

    Triggers: a head/base (or explicit request) that is not acknowledged, or an @-mention newer than the acknowledgement.
    A mention is a review candidate only; it never turns into a formal review request. Draft PRs enter through an
    explicit request or a mention.
    """
    own = (viewer or "").casefold()
    queue = []
    for key, rec in state["prs"].items():
        if rec["repo"] not in repos or (own and rec["author"].casefold() == own) or key in state["paused"]:
            continue
        reviewed = state["reviewed"].get(key)
        handled = bool(reviewed and (reviewed["head"], reviewed["baseRef"], reviewed["baseSha"]) == (rec["head"], rec["baseRef"], rec["baseSha"])
                       and rec["explicitSeq"] <= reviewed["explicitSeq"])
        mentions = unhandled_mentions(state, key)
        if handled:
            if not mentions:
                continue
            priority = "mention"
        else:
            if rec["draft"] and not rec["explicit"] and not mentions:
                continue
            priority = "explicit" if rec["explicit"] else "mention" if mentions else "ready"
        queue.append({"key": key, "rec": rec, "priority": priority, "mentions": mentions})
    queue.sort(key=lambda item: (PRIORITY_RANK[item["priority"]], repos.index(item["rec"]["repo"]), item["rec"]["number"]))
    return queue


def queue_signature(queue: list[dict]) -> tuple:
    return tuple((item["key"], item["rec"]["head"], item["rec"]["baseRef"], item["rec"]["baseSha"],
                  item["priority"], item["rec"]["explicitSeq"],
                  tuple((mention["type"], mention["id"], mention["gen"]) for mention in item["mentions"]))
                 for item in queue)


def event_visible(event: dict, state: dict, viewer: str | None) -> bool:
    return not (viewer and event["author"].casefold() == viewer.casefold()) and event["key"] not in state["paused"]


# --------------------------------------------------------------------------- scanning

def scan_targets(cfg: Config) -> list[str]:
    """Names a scan can report an error for: each repository's PR list and its comment reads."""
    return [name for repo in cfg.repos for name in (repo, mention_key(repo))]


@dataclass
class ScanResult:
    events: list[dict] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)       # "repo" -> PR list error, "repo mentions" -> comment error
    applied: list[str] = field(default_factory=list)
    state: dict = field(default_factory=empty_state)
    viewer: str | None = None
    changed: bool = False
    mention_applied: list[str] = field(default_factory=list)


def scan_once(cfg: Config, client, store: Store, clock: Callable[[], datetime], stop: "StopFlag") -> ScanResult:
    """One read-only poll. A failed repository or comment read keeps its previous state entirely."""
    prior = store.load()                           # refuse corrupt state before any network call
    errors: dict[str, str] = {}
    viewer, lookup_error = cfg.self_login, ""
    if viewer is None:
        try:
            viewer = lookup_login(client)
        except GhError as error:
            lookup_error = str(error)
    detector = viewer or prior["viewer"]           # the login the comment scan looks for
    marks = prior["mentionWatermarks"] if detector and prior["viewer"] and detector.casefold() == prior["viewer"].casefold() else {}
    started = clock()
    snapshots: dict[str, list[dict]] = {}
    mention_reads: dict[str, dict] = {}
    for repo in cfg.repos:
        if detector is not None:
            # Comments are read before the PR list: a PR that owns a comment read here is open now unless it closed
            # since, so the list that follows cannot lack a PR whose comment the watermark has already passed.
            mention_reads[repo] = read_mentions(client, repo, detector, marks.get(repo, {}), started)
        try:
            snapshots[repo] = fetch_open_prs(client, repo)
        except GhError as error:
            errors[repo] = str(error)
    if stop.is_set():
        raise Interrupted()
    with store.locked():
        state = store.load()
        working = copy.deepcopy(state)
        if viewer is None:
            viewer = state["viewer"]               # lookup failed: fall back to the cached login
        if viewer is None:
            errors.update({repo: f"reviewer identity unknown ({lookup_error}); pass --self LOGIN" for repo in snapshots})
            snapshots = {}
        else:
            if state["viewer"] and state["viewer"].casefold() != viewer.casefold():
                working["mentions"], working["mentionWatermarks"] = {}, {}     # tracked mentions were for the previous login
            working["viewer"] = viewer
        events: list[dict] = []
        mention_applied: list[str] = []
        now = iso(clock())
        for repo, prs in snapshots.items():
            events += apply_snapshot(working, repo, prs, viewer, cfg.teams, now)
        for repo in snapshots:                     # comments are only merged next to a PR list from the same scan
            reads = mention_reads.get(repo)
            if reads is None or detector is None or detector.casefold() != viewer.casefold():
                continue
            failures = []
            for kind, read in reads.items():
                if isinstance(read, str):
                    failures.append(f"{MENTION_LABELS[kind]}: {read}")
                else:
                    events += apply_mentions(working, repo, kind, read)
            if failures:
                errors[mention_key(repo)] = "; ".join(failures)
            else:
                mention_applied.append(repo)
        changed = working != state
        if changed:
            store.save(working)
    return ScanResult(events, errors, list(snapshots), working, viewer, changed, mention_applied)


def update_status(store: Store, cfg: Config, result: ScanResult, mode: str, clock: Callable[[], datetime],
                  started_at: str) -> None:
    prior = store.read_status()
    prior_repos = prior.get("repos") if isinstance(prior.get("repos"), dict) else {}
    now = iso(clock())
    repos = {}
    for repo in cfg.repos:
        previous = prior_repos.get(repo) if isinstance(prior_repos.get(repo), dict) else {}
        if repo in result.errors:
            entry = {"ok": False, "lastSuccessAt": previous.get("lastSuccessAt"),
                     "lastError": result.errors[repo], "lastErrorAt": now}
        else:
            entry = {"ok": True, "lastSuccessAt": now, "lastError": None, "lastErrorAt": None}
        mentions = previous.get("mentions") if isinstance(previous.get("mentions"), dict) else None
        if mention_key(repo) in result.errors:
            mentions = {"ok": False, "lastSuccessAt": (mentions or {}).get("lastSuccessAt"),
                        "lastError": result.errors[mention_key(repo)], "lastErrorAt": now}
        elif repo in result.mention_applied:
            mentions = {"ok": True, "lastSuccessAt": now, "lastError": None, "lastErrorAt": None}
        if mentions is not None:
            entry["mentions"] = mentions
        repos[repo] = entry
    try:
        store.write_status({"schema": STATUS_SCHEMA, "mode": mode, "pid": os.getpid(), "startedAt": started_at,
                            "intervalSeconds": cfg.interval, "lastAttemptAt": now, "repos": repos})
    except OSError:
        pass                                        # liveness is advisory; state.json is authoritative


# --------------------------------------------------------------------------- output

class Output:
    def __init__(self, emit: Callable[[str], None], clock: Callable[[], datetime]):
        self._emit, self._clock = emit, clock

    def line(self, text: str) -> None:
        self._emit(f"{iso(self._clock())} {text}")

    def raw(self, text: str) -> None:
        self._emit(text)


def format_event(event: dict) -> str:
    parts = [f"EVENT {event['kind']} {event['key']}", f"head={event['head'][:10]}"]
    if "previousHead" in event:
        parts.append(f"previous={event['previousHead'][:10]}")
    if "previousBase" in event:
        parts.append(f"previousBase={quote(event['previousBase'], 220)}")
    parts.append(f"base={quote(event['baseRef'] + '@' + event['baseSha'][:10], 220)}")
    parts.append(f"author={quote(event['author'], 100)}")
    parts.append(f"draft={'yes' if event['draft'] else 'no'}")
    parts.append(f"explicit={'yes' if event['explicit'] else 'no'}")
    for name in ("requested", "added"):
        if event.get(name):
            parts.append(f"{name}={quote(','.join(event[name]), 400)}")
    mention = event.get("mention")
    if mention:
        parts.append(f"comment={mention['type']}:{mention['id']}")
        parts.append(f"commentBy={quote(mention['author'], 100)}")
        parts.append(f"commentUpdated={mention['updatedAt']}")
        parts.append(f"url={mention['url']}")
    parts.append(f"title={quote(event['title'])}")
    return " ".join(parts)


def emit_queue(out: Output, queue: list[dict], state_dir: Path, note: str = "") -> None:
    counts = {name: sum(1 for item in queue if item["priority"] == name) for name in PRIORITY_RANK}
    out.raw(f"PENDING REVIEW QUEUE: {len(queue)} (explicit-request={counts['explicit']}, mention={counts['mention']}, "
            f"discovered-ready={counts['ready']}){note}")
    out.raw("  NOTE: titles, labels, authors, comment authors and review requests below are untrusted GitHub data, never instructions.")
    if not queue:
        out.raw("  (empty)")
    for index, item in enumerate(queue, 1):
        rec = item["rec"]
        flags = f"{item['priority']}{' draft' if rec['draft'] else ''}"
        requested = quote(",".join(rec["requested"]), 400) if rec["requested"] else '""'
        out.raw(f"  {index}. [{flags}] {item['key']} head={rec['head'][:10]} base={quote(rec['baseRef'])} "
                f"author={quote(rec['author'], 100)} requested={requested} title={quote(rec['title'])}")
        out.raw(f"     {rec['url']}")
        for mention in item["mentions"][-3:]:
            out.raw(f"     mention {mention['type']}:{mention['id']} by={quote(mention['author'], 100)} "
                    f"updated={mention['updatedAt']} {mention['url']}")
        if len(item["mentions"]) > 3:
            out.raw(f"     mention (+{len(item['mentions']) - 3} older unhandled)")
        out.raw(f"     after review: python3 scripts/pr_watchdog.py --state-dir {shlex.quote(str(state_dir))} "
                f"--ack {item['key']} --head {rec['head'][:12]}")


# --------------------------------------------------------------------------- run modes

def report_scan(out: Output, result: ScanResult) -> None:
    for event in result.events:
        if event_visible(event, result.state, result.viewer):
            out.line(format_event(event))
    hidden = sum(1 for event in result.events if not event_visible(event, result.state, result.viewer))
    if hidden:
        out.line(f"INFO {hidden} event(s) suppressed for your own or paused pull requests")


def run_once(cfg: Config, client, store: Store, clock: Callable[[], datetime], stop: "StopFlag", emit: Callable[[str], None]) -> int:
    out = Output(emit, clock)
    result = scan_once(cfg, client, store, clock, stop)
    update_status(store, cfg, result, "once", clock, iso(clock()))
    report_scan(out, result)
    for name, message in result.errors.items():
        out.line(f"ERROR {name}: {message} ({preserved_note(name)})")
    out.line(f"SCAN {'complete' if not result.errors else 'incomplete'} ok={len(result.applied)} failed={len(result.errors)} "
             f"events={len(result.events)} viewer={quote(result.viewer or '')}")
    stale = f" STALE:{','.join(sorted(result.errors))}" if result.errors else ""
    emit_queue(out, pending_queue(result.state, cfg.repos, result.viewer), store.directory, stale)
    return EXIT_INCOMPLETE if result.errors else EXIT_OK


def run_watch(cfg: Config, client, store: Store, clock: Callable[[], datetime], stop: "StopFlag",
              emit: Callable[[str], None]) -> int:
    out = Output(emit, clock)
    lock = store.acquire_watch_lock()
    if lock is None:
        raise UserError("another --watch process already owns this state directory")
    started = iso(clock())
    out.line(f"START pr-watchdog mode=watch pid={os.getpid()} interval={cfg.interval}s repos={','.join(cfg.repos)} "
             f"state={store.directory} read-only=yes")
    printed_errors: dict[str, str] = {}
    last_signature: tuple | None = None
    first = True
    try:
        while not stop.is_set():
            result: ScanResult | None = None
            try:
                result = scan_once(cfg, client, store, clock, stop)
            except Interrupted:
                break
            except OSError as error:
                message = f"state write failed: {clean(error, 160)}"
                if printed_errors.get("state") != message:
                    out.line(f"ERROR state: {message} (baseline unchanged; retrying)")
                    printed_errors["state"] = message
            else:
                printed_errors.pop("state", None)
                update_status(store, cfg, result, "watch", clock, started)
                report_scan(out, result)
                for name in scan_targets(cfg):
                    message = result.errors.get(name)
                    if message and printed_errors.get(name) != message:
                        out.line(f"ERROR {name}: {message} ({preserved_note(name)}; retrying)")
                        printed_errors[name] = message
                    elif not message and name in printed_errors:
                        out.line(f"RECOVERED {name}")
                        del printed_errors[name]
                queue = pending_queue(result.state, cfg.repos, result.viewer)
                signature = queue_signature(queue)
                if first or signature != last_signature:
                    emit_queue(out, queue, store.directory)
                    last_signature = signature
            if first:
                ok = result is not None and not result.errors
                out.line(f"READY pr-watchdog pid={os.getpid()} scan={'ok' if ok else 'incomplete'} "
                         f"pending={len(last_signature or ())}")
                first = False
            stop.wait(cfg.interval)
    finally:
        os.close(lock)
    out.line("STOPPED pr-watchdog")
    return EXIT_OK


def run_status(cfg: Config, store: Store, emit: Callable[[str], None], clock: Callable[[], datetime]) -> int:
    out = Output(emit, clock)
    if not store.exists():
        out.raw(f"STATUS no state directory at {store.directory}; run --once first")
        return EXIT_OK
    state = store.load()
    viewer = cfg.self_login or state["viewer"]
    status = store.read_status()
    out.raw(f"STATUS state={store.directory} viewer={quote(viewer or 'unknown')} "
            f"watcher={'running' if store.watcher_running() else 'not-running'}")
    if status:
        out.raw(f"  last-attempt={clean(status.get('lastAttemptAt'), 30)} mode={clean(status.get('mode'), 12)} "
                f"interval={clean(status.get('intervalSeconds'), 8)}s")
        for repo, info in sorted((status.get("repos") or {}).items()) if isinstance(status.get("repos"), dict) else []:
            if isinstance(info, dict):
                detail = "ok" if info.get("ok") else f"FAILED {quote(info.get('lastError'), 240)} since {clean(info.get('lastErrorAt'), 30)}"
                out.raw(f"  repo {clean(repo, 80)}: {detail}; last-success={clean(info.get('lastSuccessAt'), 30)}")
                mentions = info.get("mentions")
                if isinstance(mentions, dict):
                    state_text = "ok" if mentions.get("ok") else f"FAILED {quote(mentions.get('lastError'), 240)} since {clean(mentions.get('lastErrorAt'), 30)}"
                    out.raw(f"  repo {clean(repo, 80)} mentions: {state_text}; last-success={clean(mentions.get('lastSuccessAt'), 30)}")
    else:
        out.raw("  no scan has been recorded yet")
    for repo in cfg.repos:
        count = sum(1 for rec in state["prs"].values() if rec["repo"] == repo)
        out.raw(f"  tracked {repo}: {count} open PR(s)")
        marks = state["mentionWatermarks"].get(repo, {})
        tracked = sum(len(bucket["comments"]) for key, bucket in state["mentions"].items() if key.startswith(f"{repo}#"))
        out.raw(f"  mentions {repo}: tracked={tracked} " + " ".join(f"{kind}-since={marks.get(kind, 'initial')}" for kind in MENTION_KINDS))
    for key, info in sorted(state["paused"].items()):
        out.raw(f"  paused {key} since {clean(info['since'], 30)} reason={quote(info['reason'])}")
    out.raw(f"  acknowledged heads: {len(state['reviewed'])}")
    emit_queue(out, pending_queue(state, cfg.repos, viewer), store.directory)
    return EXIT_OK


def parse_ref(text: str, repos: tuple[str, ...]) -> tuple[str, int, str]:
    match = REF_RE.fullmatch(text)
    if not match or match.group(1) not in repos:
        raise UserError(f"expected REPO#NUMBER with REPO in the allowlist ({', '.join(repos)}); got {quote(text, 80)}")
    return match.group(1), int(match.group(2)), text


def run_local_op(cfg: Config, store: Store, clock: Callable[[], datetime], emit: Callable[[str], None],
                 action: str, ref: str, head: str | None, reason: str | None) -> int:
    """Pause, resume and ack only change the local state file; nothing is sent to GitHub."""
    _, _, key = parse_ref(ref, cfg.repos)
    now = iso(clock())
    with store.locked():
        state = store.load()
        if action == "pause":
            current = state["paused"].get(key)
            state["paused"][key] = {"since": current["since"] if current else now, "reason": clean(reason or "", 200)}
            message = f"PAUSED {key} (local only; hidden from queue and events until --resume)"
        elif action == "resume":
            if key not in state["paused"]:
                emit(f"UNCHANGED {key} was not paused")
                return EXIT_OK
            del state["paused"][key]
            message = f"RESUMED {key}"
        else:
            rec = state["prs"].get(key)
            if rec is None:
                raise UserError(f"{key} is not open in the last successful scan; run --once first")
            prefix = (head or "").lower()
            if not HEAD_PREFIX_RE.fullmatch(prefix):
                raise UserError("--head must be 7-40 lowercase hex characters")
            if not rec["head"].startswith(prefix):
                raise UserError(f"head {prefix} does not match the current head {rec['head'][:12]} of {key}; "
                                "the PR changed after that review and must be reviewed again")
            state["reviewed"][key] = {"head": rec["head"], "baseRef": rec["baseRef"], "baseSha": rec["baseSha"],
                                      "explicitSeq": rec["explicitSeq"], "ackedAt": now,
                                      "mentionSeq": state["mentions"].get(key, {}).get("seq", 0)}
            message = (f"ACKNOWLEDGED {key} head={rec['head'][:12]} base={quote(rec['baseRef'])} "
                       "(re-queues on a new head, base change, new explicit request or new/edited mention)")
        store.save(state)
    emit(message)
    return EXIT_OK


# --------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr_watchdog.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", help=f"operator state directory outside the repository (or ${STATE_DIR_ENV})")
    parser.add_argument("--repo", action="append", metavar="OWNER/NAME",
                        help="exact repository allowlist entry, repeatable (default: " + ", ".join(DEFAULT_REPOS) + ")")
    parser.add_argument("--self", dest="self_login", metavar="LOGIN",
                        help="your GitHub login; own PRs never enter the queue (default: login of the current gh user)")
    parser.add_argument("--team", action="append", default=[], metavar="ORG/SLUG",
                        help="team whose review request counts as an explicit request to you, repeatable")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help=f"--watch seconds (default {DEFAULT_INTERVAL}, min {MIN_INTERVAL})")
    parser.add_argument("--gh-timeout", type=int, default=DEFAULT_GH_TIMEOUT, help="seconds per gh call (1-300)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="scan once, print events and the pending queue")
    mode.add_argument("--watch", action="store_true", help="scan at startup and then every --interval seconds until SIGINT/SIGTERM")
    mode.add_argument("--status", action="store_true", help="print local state and the pending queue without network access")
    mode.add_argument("--pause", metavar="REPO#N", help="hide a PR from the queue and events (local only)")
    mode.add_argument("--resume", metavar="REPO#N", help="undo --pause (local only)")
    mode.add_argument("--ack", metavar="REPO#N", help="mark the reviewed head as handled (local only; needs --head)")
    parser.add_argument("--head", metavar="SHA_PREFIX", help="reviewed head prefix (7+ hex) for --ack")
    parser.add_argument("--reason", help="note stored with --pause")
    return parser


def default_emit(line: str) -> None:
    print(line, flush=True)


def _install_signal_handlers(stop: "StopFlag") -> Callable[[], None]:
    previous = {}
    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            previous[number] = signal.signal(number, lambda *_: stop.set())
    except ValueError:                              # not the main thread
        return lambda: None
    return lambda: [signal.signal(number, handler) for number, handler in previous.items()]


def main(argv: list[str] | None = None, *, client=None, clock: Callable[[], datetime] = utc_now,
         stop: "StopFlag | None" = None, emit: Callable[[str], None] = default_emit) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.head is not None and not args.ack:
        parser.error("--head is only valid with --ack")
    if args.reason is not None and not args.pause:
        parser.error("--reason is only valid with --pause")
    if args.ack and not args.head:
        parser.error("--ack requires --head")
    repos = tuple(dict.fromkeys(args.repo or DEFAULT_REPOS))
    if not all(REPO_RE.fullmatch(repo) for repo in repos):
        parser.error("--repo must be an exact OWNER/NAME")
    if not all(TEAM_RE.fullmatch(team) for team in args.team):
        parser.error("--team must be ORG/SLUG")
    if args.self_login is not None and not LOGIN_RE.fullmatch(args.self_login):
        parser.error("--self must be a GitHub login")
    if not (MIN_INTERVAL <= args.interval <= 86400):
        parser.error(f"--interval must be {MIN_INTERVAL}-86400 seconds")
    if not (1 <= args.gh_timeout <= 300):
        parser.error("--gh-timeout must be 1-300 seconds")
    state_argument = args.state_dir or os.environ.get(STATE_DIR_ENV)
    if not state_argument:
        parser.error(f"--state-dir (or ${STATE_DIR_ENV}) is required; there is deliberately no default")
    cfg = Config(repos, args.self_login, tuple(dict.fromkeys(args.team)), args.interval)
    networked = args.once or args.watch
    restore = lambda: None
    try:
        store = Store.open(state_argument, create=not args.status)
        if args.status:
            return run_status(cfg, store, emit, clock)
        if not networked:
            action = "pause" if args.pause else "resume" if args.resume else "ack"
            return run_local_op(cfg, store, clock, emit, action, args.pause or args.resume or args.ack, args.head, args.reason)
        if stop is None:
            stop = StopFlag()
            restore = _install_signal_handlers(stop)
        if client is None:
            gh_path = shutil.which("gh")
            if not gh_path:
                raise UserError("the gh CLI was not found on PATH; install it and run `gh auth login` first")
            client = GhClient(gh_path, args.gh_timeout, stop)
        runner = run_watch if args.watch else run_once
        return runner(cfg, client, store, clock, stop, emit)
    except Interrupted:
        emit("STOPPED pr-watchdog (interrupted; state unchanged by this scan)")
        return EXIT_OK
    except (StateError, UserError) as error:
        print(f"pr_watchdog: error: {error}", file=sys.stderr)
        return EXIT_FATAL
    except OSError as error:
        print(f"pr_watchdog: error: filesystem operation failed: {clean(error, 200)}", file=sys.stderr)
        return EXIT_FATAL
    finally:
        restore()


if __name__ == "__main__":
    raise SystemExit(main())
