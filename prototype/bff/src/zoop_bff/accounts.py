"""Member accounts, member/guest sessions, settings and the virtual-account connection (SQLite).

Everything lives in the state database (``statedb``), so members, settings, connections, tutorial
completion and open sessions survive a BFF restart. Passwords are stored only as scrypt hashes and
session tokens only as SHA-256 digests. A member whose ``status`` is ``blocked`` cannot log in, and
every open session of that member is refused (and deleted) on its next request.

Guests get a session without a member; their tutorial completion lives on that session only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Collection, Literal

from .audit import Clock
from .dataset import HoldingRec
from .errors import ApiError
from .social import SocialAuth, SocialIdentity
from .statedb import StateDb, utc_iso

SESSION_COOKIE = "zoop_session"
DEMO_EMAIL = "demo@zoop.local"
DEMO_PASSWORD = "zoop-demo"  # development only; stored hashed
MEMBER_SESSION_SECONDS = 14 * 24 * 60 * 60
GUEST_SESSION_SECONDS = 24 * 60 * 60
_ACTIVE_WRITE_INTERVAL = timedelta(seconds=60)

# Required terms (requirement 3). Only titles exist: the bodies are not written yet.
TERMS: tuple[tuple[str, str, bool], ...] = (
    ("service", "서비스 이용약관", True),
    ("privacy", "개인정보 수집·이용 동의", True),
)
REQUIRED_TERMS = frozenset(t[0] for t in TERMS if t[2])
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN = 8
DISPLAY_NAME_MAX = 20

MemberStatus = Literal["active", "blocked"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---- password hashing (scrypt, standard library)

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str | None) -> bool:
    try:
        scheme, n, r, p, salt, digest = (stored or "").split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        candidate = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(candidate, expected)
    except (ValueError, TypeError):
        return False


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---- records


@dataclass
class Connection:
    """A connected virtual account. Holdings are frozen at connect time: publishing or rolling back a
    graph version must not change (or invalidate) what a member already connected. ``connected_at``
    is the as-of time of the stored quantities and average prices (requirement 63)."""

    id: str
    mock_portfolio_id: str
    label: str
    connected_at: str
    holdings: tuple[HoldingRec, ...] = ()


@dataclass
class UserState:
    id: str
    email: str
    display_name: str
    mode: Literal["assets", "watchlist"] = "watchlist"
    watchlist_ids: list[str] = field(default_factory=list)
    tutorial_completed: bool = False
    completed: bool = False
    version: int = 1
    connection: Connection | None = None
    investor: bool | None = None
    status: MemberStatus = "active"
    created_at: str = ""
    signup_method: str = "email"
    last_active_at: str | None = None


@dataclass(frozen=True)
class Principal:
    kind: Literal["member", "guest"]
    principal_id: str
    user: UserState | None
    # Guests only: tutorial completion is kept on the guest session itself (requirement 5).
    guest_tutorial_completed: bool = False



def blocked_error() -> ApiError:
    return ApiError(
        401, "member_blocked", "이용이 제한된 계정입니다. 자세한 내용은 운영팀에 문의해 주세요."
    )


class AccountStore:
    def __init__(
        self,
        db: StateDb,
        clock: Clock,
        *,
        member_session_seconds: float = MEMBER_SESSION_SECONDS,
        guest_session_seconds: float = GUEST_SESSION_SECONDS,
    ) -> None:
        self._db = db
        self._clock = clock
        self.member_ttl = timedelta(seconds=member_session_seconds)
        self.guest_ttl = timedelta(seconds=guest_session_seconds)
        self._seed_demo()
        # A hash for unknown e-mails so a miss costs the same as a wrong password.
        self._dummy = hash_password("not-a-real-password")
        self.social = SocialAuth(db, clock)

    def _now(self) -> datetime:
        return self._clock.now()

    # -- members
    def _seed_demo(self) -> None:
        if self._db.one("SELECT 1 FROM members WHERE email = ?", (DEMO_EMAIL,)) is None:
            self._insert_member(
                "user-demo", DEMO_EMAIL, "데모 사용자", hash_password(DEMO_PASSWORD), "email", list(REQUIRED_TERMS)
            )

    def _insert_member(
        self, member_id: str, email: str, name: str, password_hash: str | None, method: str, terms: list[str]
    ) -> None:
        now = utc_iso(self._now())
        self._db.execute(
            "INSERT INTO members(id,email,display_name,password_hash,signup_method,status,created_at,terms) "
            "VALUES (?,?,?,?,?,'active',?,?)",
            (member_id, email, name, password_hash, method, now, json.dumps({"ids": sorted(terms), "at": now})),
        )

    def _load(self, row) -> UserState:
        conn_row = self._db.one("SELECT * FROM member_connections WHERE member_id = ?", (row["id"],))
        connection = None
        if conn_row is not None:
            connection = Connection(
                conn_row["id"],
                conn_row["mock_portfolio_id"],
                conn_row["label"],
                conn_row["connected_at"],
                tuple(HoldingRec(**h) for h in json.loads(conn_row["holdings"])),
            )
        return UserState(
            id=row["id"],
            email=row["email"],
            display_name=row["display_name"],
            mode=row["mode"],
            watchlist_ids=json.loads(row["watchlist"]),
            tutorial_completed=bool(row["tutorial_completed"]),
            completed=bool(row["completed"]),
            version=row["version"],
            connection=connection,
            investor=None if row["investor"] is None else bool(row["investor"]),
            status=row["status"],
            created_at=row["created_at"],
            signup_method=row["signup_method"],
            last_active_at=row["last_active_at"],
        )

    def member(self, user_id: str) -> UserState | None:
        row = self._db.one("SELECT * FROM members WHERE id = ?", (user_id,))
        return None if row is None else self._load(row)

    def members(self) -> list[UserState]:
        return [self._load(r) for r in self._db.query("SELECT * FROM members ORDER BY created_at, id")]

    def set_status(self, user_id: str, status: MemberStatus) -> bool:
        """Idempotent: False when the member already has ``status``. A blocked member's sessions stay stored
        so every open tab keeps getting ``member_blocked`` (401) until it logs out; unblocking deletes them, so
        an old cookie never comes back to life."""
        with self._db.transaction() as conn:
            row = conn.execute("SELECT status FROM members WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise ApiError(404, "member_not_found", "회원을 찾을 수 없습니다.")
            if row["status"] == status:
                return False
            conn.execute("UPDATE members SET status = ? WHERE id = ?", (status, user_id))
            if status == "active":
                conn.execute("DELETE FROM member_sessions WHERE member_id = ?", (user_id,))
            return True

    def session_counts(self) -> dict[str, int]:
        """Cumulative successful logins per member (persistent)."""
        return {r["id"]: r["login_count"] for r in self._db.query("SELECT id, login_count FROM members")}

    # -- sign-up / login
    def signup(self, email: str, password: str, display_name: str, agreements: Collection[str]) -> str:
        """Server-side validation of every field at once (422 with ``details.fields``); duplicate e-mail 409."""
        email_n = email.strip().lower()
        name = display_name.strip()
        fields: dict[str, str] = {}
        if not email_n:
            fields["email"] = "이메일을 입력해 주세요."
        elif not _EMAIL.match(email_n) or len(email_n) > 254:
            fields["email"] = "이메일 형식이 올바르지 않아요. 예: name@example.com"
        if not password:
            fields["password"] = "비밀번호를 입력해 주세요."
        elif len(password) < PASSWORD_MIN or len(password) > 128 or not (
            re.search(r"[A-Za-z]", password) and re.search(r"\d", password)
        ):
            fields["password"] = f"비밀번호는 영문과 숫자를 섞어 {PASSWORD_MIN}자 이상으로 입력해 주세요."
        if not name:
            fields["displayName"] = "표시 이름을 입력해 주세요."
        elif len(name) > DISPLAY_NAME_MAX:
            fields["displayName"] = f"표시 이름은 {DISPLAY_NAME_MAX}자 이하로 입력해 주세요."
        missing = sorted(REQUIRED_TERMS - set(agreements))
        if missing:
            fields["agreements"] = "필수 약관에 모두 동의해 주세요."
        # Duplicate e-mail is reported together with the other fields (one round trip shows every problem).
        taken = "email" not in fields and self._db.one("SELECT 1 FROM members WHERE email = ?", (email_n,)) is not None
        if taken:
            fields["email"] = "이미 가입된 이메일이에요. 로그인해 주세요."
        if taken and len(fields) == 1:
            raise ApiError(409, "email_taken", "이미 가입된 이메일입니다.", {"fields": fields})
        if fields:
            raise ApiError(
                422,
                "signup_invalid",
                "가입 정보를 확인해 주세요.",
                {"fields": fields, "missingTerms": missing, "emailTaken": taken},
            )
        member_id = f"user-{secrets.token_hex(8)}"
        self._insert_member(member_id, email_n, name, hash_password(password), "email", list(agreements))
        return self._open_member(member_id)

    def login(self, email: str, password: str) -> str:
        fields: dict[str, str] = {}
        if not email.strip():
            fields["email"] = "이메일을 입력해 주세요."
        if not password:
            fields["password"] = "비밀번호를 입력해 주세요."
        if fields:
            raise ApiError(422, "login_invalid", "이메일과 비밀번호를 입력해 주세요.", {"fields": fields})
        row = self._db.one(
            "SELECT id, password_hash, status FROM members WHERE email = ?", (email.strip().lower(),)
        )
        ok = verify_password(password, row["password_hash"] if row and row["password_hash"] else self._dummy)
        if not ok or row is None or not row["password_hash"]:
            raise ApiError(401, "invalid_credentials", "이메일 또는 비밀번호가 올바르지 않습니다.")
        if row["status"] == "blocked":
            raise ApiError(403, "member_blocked", blocked_error().message)
        return self._open_member(row["id"])

    def social_login(self, identity: SocialIdentity) -> tuple[str, bool]:
        """(token, created). A known (provider, subject) logs in; a new one creates a member. An e-mail
        already used by another member is not linked automatically (409)."""
        row = self._db.one(
            "SELECT m.id, m.status FROM member_identities i JOIN members m ON m.id = i.member_id "
            "WHERE i.provider = ? AND i.subject = ?",
            (identity.provider, identity.subject),
        )
        if row is not None:
            if row["status"] == "blocked":
                raise ApiError(403, "member_blocked", blocked_error().message)
            return self._open_member(row["id"]), False
        email = identity.email.strip().lower()
        if self._db.one("SELECT 1 FROM members WHERE email = ?", (email,)) is not None:
            raise ApiError(409, "social_email_in_use", "이미 다른 방법으로 가입된 이메일입니다.")
        member_id = f"user-{secrets.token_hex(8)}"
        with self._db.transaction() as conn:
            self._insert_member(
                member_id,
                email,
                identity.display_name.strip()[:DISPLAY_NAME_MAX] or email.split("@")[0],
                None,
                f"social:{identity.provider}",
                list(REQUIRED_TERMS),  # the provider consent screen stands in for the terms step
            )
            conn.execute(
                "INSERT INTO member_identities(provider,subject,member_id,created_at) VALUES (?,?,?,?)",
                (identity.provider, identity.subject, member_id, utc_iso(self._now())),
            )
        return self._open_member(member_id), True

    # -- sessions
    def guest(self) -> str:
        return self._open("guest", f"guest-{secrets.token_hex(6)}", None, self.guest_ttl)

    def _open_member(self, member_id: str) -> str:
        self._db.execute("UPDATE members SET login_count = login_count + 1 WHERE id = ?", (member_id,))
        return self._open("member", member_id, member_id, self.member_ttl)

    def _open(self, kind: str, principal_id: str, member_id: str | None, ttl: timedelta) -> str:
        token = secrets.token_urlsafe(32)
        now = self._now()
        self._db.execute(
            "INSERT INTO member_sessions(token_hash,kind,principal_id,member_id,created_at,expires_at) VALUES (?,?,?,?,?,?)",
            (_token_key(token), kind, principal_id, member_id, utc_iso(now), utc_iso(now + ttl)),
        )
        return token

    def logout(self, token: str | None) -> None:
        if token:
            self._db.execute("DELETE FROM member_sessions WHERE token_hash = ?", (_token_key(token),))

    def principal(self, token: str | None) -> Principal | None:
        """The session's principal, or None when there is no live session. A blocked member's session is
        deleted and refused with ``member_blocked`` (401)."""
        if not token:
            return None
        key = _token_key(token)
        row = self._db.one("SELECT * FROM member_sessions WHERE token_hash = ?", (key,))
        if row is None:
            return None
        now = self._now()
        if datetime.fromisoformat(row["expires_at"]) <= now:
            self._db.execute("DELETE FROM member_sessions WHERE token_hash = ?", (key,))
            return None
        if row["kind"] == "guest":
            return Principal("guest", row["principal_id"], None, bool(row["tutorial_completed"]))
        member = self._db.one("SELECT * FROM members WHERE id = ?", (row["member_id"],))
        if member is None:
            self._db.execute("DELETE FROM member_sessions WHERE token_hash = ?", (key,))
            return None
        if member["status"] == "blocked":
            raise blocked_error()
        last = member["last_active_at"]
        if last is None or now - datetime.fromisoformat(last) >= _ACTIVE_WRITE_INTERVAL:
            self._db.execute("UPDATE members SET last_active_at = ? WHERE id = ?", (utc_iso(now), member["id"]))
        user = self._load(member)
        return Principal("member", user.id, user)

    def summary(self) -> dict[str, int]:
        """Registered members and the live (unexpired) sessions."""
        now = utc_iso(self._now())
        registered = self._db.one("SELECT COUNT(*) AS n FROM members")["n"]
        counts = {
            r["kind"]: r["n"]
            for r in self._db.query(
                "SELECT kind, COUNT(*) AS n FROM member_sessions WHERE expires_at > ? GROUP BY kind", (now,)
            )
        }
        return {
            "registered": registered,
            "member_sessions": counts.get("member", 0),
            "guest_sessions": counts.get("guest", 0),
        }

    # -- tutorial (members and guests)
    def set_tutorial(self, token: str, principal: Principal, completed: bool) -> None:
        if principal.user is None:
            self._db.execute(
                "UPDATE member_sessions SET tutorial_completed = ? WHERE token_hash = ?",
                (int(completed), _token_key(token)),
            )
            return
        user = principal.user
        if user.tutorial_completed == completed:
            return  # repeated request: no change, no version bump
        self._db.execute(
            "UPDATE members SET tutorial_completed = ?, version = version + 1 WHERE id = ?",
            (int(completed), user.id),
        )
        user.tutorial_completed = completed
        user.version += 1

    # -- settings
    def update_settings(
        self,
        user: UserState,
        *,
        version: int,
        mode: str | None,
        watchlist_ids: list[str] | None,
        tutorial_completed: bool | None,
        completed: bool | None,
        known_companies: Collection[str],
        investor: bool | None = None,
    ) -> UserState:
        """No watchlist limit. A request that would change nothing is answered with the stored settings
        even when its ``version`` is stale (a resent request never changes state twice, requirement 53);
        any other stale request is a 409."""
        ids = list(user.watchlist_ids if watchlist_ids is None else watchlist_ids)
        new = {
            "mode": user.mode if mode is None else mode,
            "watchlist": ids,
            "tutorial_completed": user.tutorial_completed if tutorial_completed is None else tutorial_completed,
            "completed": user.completed if completed is None else completed,
            "investor": user.investor if investor is None else investor,
        }
        unchanged = (
            new["mode"] == user.mode
            and ids == user.watchlist_ids
            and new["tutorial_completed"] == user.tutorial_completed
            and new["completed"] == user.completed
            and new["investor"] == user.investor
        )
        if unchanged:
            return user
        if version != user.version:
            raise ApiError(
                409,
                "version_conflict",
                "설정이 다른 곳에서 변경되었습니다. 최신 설정을 다시 불러오세요.",
                {"currentVersion": user.version, "receivedVersion": version},
            )
        if len(set(ids)) != len(ids):
            raise ApiError(422, "duplicate_watchlist_id", "관심 종목이 중복되었습니다.")
        unknown = [c for c in ids if c not in known_companies]
        if unknown:
            raise ApiError(
                422, "unknown_company", "알 수 없는 기업 ID가 포함되어 있습니다.", {"companyIds": unknown}
            )
        cursor = self._db.execute(
            "UPDATE members SET mode=?, watchlist=?, tutorial_completed=?, completed=?, investor=?, version=version+1 "
            "WHERE id=? AND version=?",
            (
                new["mode"],
                json.dumps(ids, ensure_ascii=False),
                int(new["tutorial_completed"]),
                int(new["completed"]),
                None if new["investor"] is None else int(new["investor"]),
                user.id,
                version,
            ),
        )
        if cursor.rowcount != 1:  # another request won the race since this one was loaded
            current = self.member(user.id)
            raise ApiError(
                409,
                "version_conflict",
                "설정이 다른 곳에서 변경되었습니다. 최신 설정을 다시 불러오세요.",
                {"currentVersion": current.version if current else None, "receivedVersion": version},
            )
        user.mode = new["mode"]  # type: ignore[assignment]
        user.watchlist_ids = ids
        user.tutorial_completed = new["tutorial_completed"]
        user.completed = new["completed"]
        user.investor = new["investor"]
        user.version += 1
        return user

    # -- portfolio connection
    def connect(
        self, user: UserState, portfolio_id: str, label: str, holdings: tuple[HoldingRec, ...]
    ) -> tuple[Connection, bool]:
        """(connection, created). Connecting the already connected profile again returns that connection
        (a retried request does not fail); a different profile while connected is 409."""
        existing = user.connection
        if existing is not None:
            if existing.mock_portfolio_id == portfolio_id:
                return existing, False
            raise ApiError(
                409,
                "already_connected",
                "이미 가상 계좌가 연결되어 있습니다. 먼저 연결을 해제하세요.",
                {"connectionId": existing.id},
            )
        connection = Connection(f"conn-{secrets.token_hex(4)}", portfolio_id, label, utc_iso(self._now()), tuple(holdings))
        try:
            self._db.execute(
                "INSERT INTO member_connections(member_id,id,mock_portfolio_id,label,connected_at,holdings) VALUES (?,?,?,?,?,?)",
                (
                    user.id,
                    connection.id,
                    portfolio_id,
                    label,
                    connection.connected_at,
                    json.dumps(
                        [{"company_id": h.company_id, "quantity": h.quantity, "avg_price": h.avg_price} for h in holdings],
                        ensure_ascii=False,
                    ),
                ),
            )
        except Exception as exc:  # sqlite3.IntegrityError: a concurrent request connected first
            current = self.member(user.id)
            if current and current.connection:
                return self.connect(current, portfolio_id, label, holdings)
            raise exc
        user.connection = connection
        return connection, True

    def disconnect(self, user: UserState, connection_id: str) -> None:
        if user.connection is None or user.connection.id != connection_id:
            raise ApiError(404, "connection_not_found", "연결을 찾을 수 없습니다.")
        self._db.execute("DELETE FROM member_connections WHERE member_id = ?", (user.id,))
        user.connection = None
