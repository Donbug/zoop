"""Per-app state and request dependencies (session cookie -> principal)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request

from .accounts import SESSION_COOKIE, AccountStore, Principal, UserState
from .admin_auth import ADMIN_COOKIE, AdminAccount
from .admin_services import AdminServices
from .chat_jobs import ChatService
from .insights import Insights, build_insights
from .config import Settings
from .dataset import Dataset
from .errors import ApiError
from .market_data import MarketData
from .sources import DataProvider


@dataclass
class AppState:
    settings: Settings
    provider: DataProvider
    admin: AdminServices
    accounts: AccountStore
    market: MarketData
    chats: ChatService = field(init=False)
    insights: Insights = field(init=False)

    def __post_init__(self) -> None:
        self.chats = ChatService(self.admin.db, self.admin.clock, self.provider, self.accounts, self.admin.usage)
        self.insights = build_insights(self.admin, self.accounts)

    def dataset(self, round_id: str | None = None) -> Dataset:
        """The graph users read: the active one, or the state a published briefing round was built from."""
        return self.provider.get() if round_id is None else self.admin.briefing_graphs.dataset(round_id)


def app_state(request: Request) -> AppState:
    return request.app.state.zoop


State = Annotated[AppState, Depends(app_state)]


def optional_principal(request: Request, state: State) -> Principal | None:
    return state.accounts.principal(request.cookies.get(SESSION_COOKIE))


OptionalPrincipal = Annotated[Principal | None, Depends(optional_principal)]


def require_session(principal: OptionalPrincipal) -> Principal:
    if principal is None:
        raise ApiError(401, "unauthenticated", "로그인 또는 비회원 세션이 필요합니다.")
    return principal


def require_member(principal: OptionalPrincipal) -> UserState:
    """Personal APIs: no session -> 401, guest session -> 403."""
    if principal is None:
        raise ApiError(401, "unauthenticated", "로그인이 필요합니다.")
    if principal.user is None:
        raise ApiError(403, "guest_forbidden", "비회원은 개인 데이터에 접근할 수 없습니다. 로그인해 주세요.")
    return principal.user


Session = Annotated[Principal, Depends(require_session)]
Member = Annotated[UserState, Depends(require_member)]


def require_admin(request: Request, state: State) -> AdminAccount:
    """Admin APIs: no admin session -> 401; a member/guest cookie alone is not enough -> 403."""
    try:
        return state.admin.auth.require(request.cookies.get(ADMIN_COOKIE))
    except ApiError as exc:
        if exc.code == "admin_auth_required" and state.accounts.principal(request.cookies.get(SESSION_COOKIE)):
            raise ApiError(403, "admin_forbidden", "회원 계정으로는 관리자 기능을 사용할 수 없습니다.") from exc
        raise


Admin = Annotated[AdminAccount, Depends(require_admin)]
