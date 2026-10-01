"""Administrator accounts and sessions, separate from the member/guest session store.

The member cookie (``zoop_session``) and the admin cookie (``zoop_admin_session``) never share a
store: a member token is simply unknown here. Passwords are kept only as PBKDF2 hashes.
SSO is not implemented (no IdP exists in this prototype).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from .audit import Actor, AuditLog, Clock
from .errors import ApiError
from .statedb import StateDb, utc_iso

ADMIN_COOKIE = "zoop_admin_session"
DEMO_ADMIN_EMAIL = "admin@zoop.local"
DEMO_ADMIN_PASSWORD = "zoop-admin"  # development only; stored hashed
_PBKDF2_ROUNDS = 200_000
_MAX_EXPIRED_MEMORY = 1000


def hash_password(password: str, *, rounds: int = _PBKDF2_ROUNDS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return "pbkdf2_sha256${}${}${}".format(
        rounds, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt), int(rounds)
        )
        return hmac.compare_digest(candidate, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class AdminAccount:
    id: str
    email: str
    display_name: str
    role: Literal["admin"] = "admin"

    @property
    def actor(self) -> Actor:
        return Actor("admin", self.id, self.email)


@dataclass
class _Session:
    admin: AdminAccount
    created: datetime
    last_seen: datetime


@dataclass(frozen=True)
class SessionView:
    admin: AdminAccount
    expires_at: datetime
    idle_expires_at: datetime


class AdminAuth:
    def __init__(self, db: StateDb, clock: Clock, audit: AuditLog, idle: float, absolute: float):
        self._db = db
        self._clock = clock
        self._audit = audit
        self.idle = timedelta(seconds=idle)
        self.absolute = timedelta(seconds=absolute)
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}
        self._expired: OrderedDict[str, Literal["idle", "absolute"]] = OrderedDict()
        self._seed_demo()
        # A hash for unknown e-mails so a miss costs the same as a wrong password.
        self._dummy = hash_password("not-a-real-password")

    # -- accounts
    def _seed_demo(self) -> None:
        if self._db.one("SELECT 1 FROM admin_accounts LIMIT 1") is None:
            self._db.execute(
                "INSERT INTO admin_accounts(id,email,display_name,role,password_hash,created_at) VALUES (?,?,?,?,?,?)",
                (
                    "admin-demo",
                    DEMO_ADMIN_EMAIL,
                    "데모 관리자",
                    "admin",
                    hash_password(DEMO_ADMIN_PASSWORD),
                    utc_iso(self._clock.now()),
                ),
            )

    def _account(self, email: str) -> tuple[AdminAccount, str] | None:
        row = self._db.one(
            "SELECT id,email,display_name,role,password_hash FROM admin_accounts WHERE email = ?",
            (email.strip().lower(),),
        )
        if row is None:
            return None
        return AdminAccount(row["id"], row["email"], row["display_name"]), row["password_hash"]

    # -- sessions
    def login(self, email: str, password: str) -> tuple[str, SessionView]:
        found = self._account(email)
        ok = verify_password(password, found[1] if found else self._dummy) and found is not None
        if not ok or found is None:
            self._audit.record(
                Actor("admin", "unknown", email.strip().lower()[:200]),
                "auth.login_failed",
                "admin-session",
                outcome="denied",
            )
            raise ApiError(401, "invalid_credentials", "이메일 또는 비밀번호가 올바르지 않습니다.")
        account = found[0]
        token = secrets.token_urlsafe(32)
        now = self._clock.now()
        with self._lock:
            self._sessions[token] = _Session(account, now, now)
        self._audit.record(account.actor, "auth.login", "admin-session", account.id)
        return token, self._view(self._sessions[token])

    def discard(self, token: str | None) -> None:
        """Drop a session without an audit entry (it was replaced by a new login)."""
        with self._lock:
            self._sessions.pop(token or "", None)
            self._expired.pop(token or "", None)

    def logout(self, token: str | None) -> None:
        with self._lock:
            session = self._sessions.pop(token or "", None)
            self._expired.pop(token or "", None)
        if session is not None:
            self._audit.record(session.admin.actor, "auth.logout", "admin-session", session.admin.id)

    def _view(self, session: _Session) -> SessionView:
        return SessionView(
            session.admin, session.created + self.absolute, session.last_seen + self.idle
        )

    def _expiry(self, session: _Session, now: datetime) -> Literal["idle", "absolute"] | None:
        if now >= session.created + self.absolute:
            return "absolute"
        if now >= session.last_seen + self.idle:
            return "idle"
        return None

    def inspect(self, token: str | None, *, touch: bool) -> tuple[SessionView | None, str | None]:
        """(session, expired reason). ``touch`` extends the idle window of a live session."""
        if not token:
            return None, None
        now = self._clock.now()
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None, self._expired.get(token)
            reason = self._expiry(session, now)
            if reason is not None:
                del self._sessions[token]
                self._expired[token] = reason
                while len(self._expired) > _MAX_EXPIRED_MEMORY:
                    self._expired.popitem(last=False)
                return None, reason
            if touch:
                session.last_seen = now
            return self._view(session), None

    def require(self, token: str | None) -> AdminAccount:
        view, expired = self.inspect(token, touch=True)
        if view is not None:
            return view.admin
        if expired is not None:
            raise ApiError(
                401,
                "admin_session_expired",
                "관리자 로그인이 만료되었습니다. 다시 로그인해 주세요.",
                {"reason": expired},
            )
        raise ApiError(401, "admin_auth_required", "관리자 로그인이 필요합니다.")
