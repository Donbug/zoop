"""Social login (requirements 4, 70): authorization-code flow with ``state`` bound to the browser.

No real identity provider or client credential exists for this prototype, so the only provider is a
development mock (``mock``) whose consent screen is the web route ``/mock-idp``. The flow still has the
real shape: ``authorize`` (state stored + browser binding cookie) -> provider consent -> ``callback``
(state checked once, code exchanged for an identity) -> existing member logs in / new member is created.

Real provider integration point: implement :class:`SocialProvider` (``authorize_url`` builds the
provider's authorization URL; ``exchange`` swaps the code for a verified identity, e.g. by checking the
ID token signature and audience) and register it in :func:`default_providers`.
"""

from __future__ import annotations

import hmac
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

from .audit import Clock
from .errors import ApiError
from .statedb import StateDb, utc_iso


@dataclass(frozen=True)
class SocialIdentity:
    provider: str
    subject: str
    email: str
    display_name: str


STATE_COOKIE = "zoop_oauth"
STATE_TTL = timedelta(minutes=10)
CODE_TTL = timedelta(minutes=5)


class SocialProvider(Protocol):
    id: str
    label: str
    development: bool

    def authorize_url(self, state: str, redirect_uri: str) -> str: ...

    def exchange(self, code: str, redirect_uri: str) -> SocialIdentity: ...


@dataclass
class _Grant:
    identity: SocialIdentity
    redirect_uri: str
    expires: datetime


class MockProvider:
    """Development-only stand-in for an OAuth provider. Its "accounts" are whatever e-mail the user types
    on the consent screen; the subject is derived from that e-mail."""

    id = "mock"
    label = "개발용 모의 로그인"
    development = True

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._codes: dict[str, _Grant] = {}

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        return "/mock-idp?" + urlencode({"client_id": "zoop-dev", "state": state, "redirect_uri": redirect_uri})

    def consent(self, email: str, display_name: str, redirect_uri: str) -> str:
        """The consent screen's [동의] button: issue a single-use code for this identity."""
        email_n = email.strip().lower()
        if "@" not in email_n or len(email_n) > 254:
            raise ApiError(422, "mock_idp_invalid", "이메일 형식으로 입력해 주세요.", {"fields": {"email": "이메일 형식으로 입력해 주세요."}})
        code = secrets.token_urlsafe(24)
        identity = SocialIdentity("mock", f"mock|{email_n}", email_n, display_name.strip() or email_n.split("@")[0])
        with self._lock:
            self._codes[code] = _Grant(identity, redirect_uri, self._clock.now() + CODE_TTL)
        return code

    def exchange(self, code: str, redirect_uri: str) -> SocialIdentity:
        with self._lock:
            grant = self._codes.pop(code, None)
        if grant is None or grant.expires <= self._clock.now() or grant.redirect_uri != redirect_uri:
            raise ApiError(400, "social_failed", "소셜 인증을 확인하지 못했습니다.")
        return grant.identity


def default_providers(clock: Clock) -> dict[str, SocialProvider]:
    return {"mock": MockProvider(clock)}


def safe_return_to(value: str | None) -> str:
    """Only same-origin paths; anything else falls back to the app root."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value[:500]


class SocialAuth:
    def __init__(self, db: StateDb, clock: Clock, providers: dict[str, SocialProvider] | None = None) -> None:
        self._db = db
        self._clock = clock
        self.providers = providers if providers is not None else default_providers(clock)

    def provider(self, provider_id: str) -> SocialProvider:
        provider = self.providers.get(provider_id)
        if provider is None:
            raise ApiError(404, "social_provider_not_found", "지원하지 않는 소셜 로그인입니다.")
        return provider

    def start(self, provider_id: str, redirect_uri: str, return_to: str | None) -> tuple[str, str]:
        """(authorization URL, browser binding for the state cookie)."""
        provider = self.provider(provider_id)
        state = secrets.token_urlsafe(24)
        binding = secrets.token_urlsafe(24)
        now = self._clock.now()
        self._db.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (utc_iso(now),))
        self._db.execute(
            "INSERT INTO oauth_states(state,provider,binding,return_to,created_at,expires_at) VALUES (?,?,?,?,?,?)",
            (state, provider_id, binding, safe_return_to(return_to), utc_iso(now), utc_iso(now + STATE_TTL)),
        )
        return provider.authorize_url(state, redirect_uri), binding

    def finish(
        self, provider_id: str, state: str | None, binding: str | None, code: str | None, error: str | None, redirect_uri: str
    ) -> tuple[SocialIdentity, str]:
        """(identity, return path). The state is consumed even when the user cancelled."""
        if not state:
            raise ApiError(400, "social_state_invalid", "로그인 요청을 확인하지 못했습니다.")
        with self._db.transaction() as conn:
            row = conn.execute("SELECT * FROM oauth_states WHERE state = ?", (state,)).fetchone()
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        valid = (
            row is not None
            and row["provider"] == provider_id
            and datetime.fromisoformat(row["expires_at"]) > self._clock.now()
            and binding is not None
            and hmac.compare_digest(row["binding"], binding)
        )
        if not valid:
            raise ApiError(400, "social_state_invalid", "로그인 요청을 확인하지 못했습니다.")
        if error:
            raise ApiError(400, "social_cancelled" if error == "access_denied" else "social_failed", "소셜 로그인이 취소되었습니다.")
        if not code:
            raise ApiError(400, "social_failed", "소셜 인증을 확인하지 못했습니다.")
        return self.provider(provider_id).exchange(code, redirect_uri), row["return_to"]
