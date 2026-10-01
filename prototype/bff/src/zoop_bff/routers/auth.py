from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from ..accounts import SESSION_COOKIE, TERMS, Principal
from ..deps import OptionalPrincipal, Session, State
from ..errors import ApiError
from ..schemas import (
    LoginRequest,
    MockIdpConsent,
    MockIdpRedirect,
    SessionResponse,
    SetupState,
    SignupRequest,
    SocialProviderOut,
    SocialProvidersResponse,
    TermOut,
    TermsResponse,
    TutorialUpdate,
    UserInfo,
)
from ..social import STATE_COOKIE, MockProvider
from ..views import mock_meta
from . import ERROR_RESPONSES

router = APIRouter(prefix="/api/auth", tags=["auth"], responses=ERROR_RESPONSES)
GENERATED_BY = "bff-mock-auth"
SOCIAL_PREFIX = "/api/auth/social"


def session_response(principal: Principal | None) -> SessionResponse:
    metadata = mock_meta(GENERATED_BY)
    if principal is None:
        return SessionResponse(authenticated=False, kind="anonymous", metadata=metadata)
    user = principal.user
    if user is None:
        return SessionResponse(
            authenticated=True,
            kind="guest",
            setup=SetupState(completed=False, tutorial_completed=principal.guest_tutorial_completed),
            metadata=metadata,
        )
    return SessionResponse(
        authenticated=True,
        kind="member",
        user=UserInfo(id=user.id, email=user.email, display_name=user.display_name),
        setup=SetupState(completed=user.completed, tutorial_completed=user.tutorial_completed),
        metadata=metadata,
    )


def _drop_previous(state: State, request: Request) -> None:
    try:
        state.accounts.logout(request.cookies.get(SESSION_COOKIE))  # never leave the old session live
    except ApiError:
        pass


def _set_session_cookie(state: State, response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=state.settings.cookie_secure,
        path="/",
        max_age=int(state.accounts.member_ttl.total_seconds()),
    )


def _open_session(state: State, request: Request, response: Response, token: str) -> SessionResponse:
    _drop_previous(state, request)
    _set_session_cookie(state, response, token)
    return session_response(state.accounts.principal(token))


@router.get("/session", response_model=SessionResponse)
def get_session(principal: OptionalPrincipal) -> SessionResponse:
    """200 with ``authenticated=false`` / ``kind="anonymous"`` when there is no live session. A blocked
    member's session answers 401 ``member_blocked`` (every request) until the client logs out."""
    return session_response(principal)


@router.get("/terms", response_model=TermsResponse)
def get_terms() -> TermsResponse:
    """Terms shown at sign-up. Only titles exist; ``bodyAvailable`` is false until the text is written."""
    return TermsResponse(
        items=[TermOut(id=i, title=t, required=r, body_available=False) for i, t, r in TERMS]
    )


@router.post("/signup", response_model=SessionResponse, status_code=201)
def signup(body: SignupRequest, request: Request, response: Response, state: State) -> SessionResponse:
    """E-mail sign-up. Invalid fields 422 ``signup_invalid`` (``details.fields``), duplicate e-mail 409
    ``email_taken``. Success logs the new member in (next screen: initial setup)."""
    token = state.accounts.signup(body.email, body.password, body.display_name, body.agreements)
    return _open_session(state, request, response, token)


@router.post("/login", response_model=SessionResponse)
def login(body: LoginRequest, request: Request, response: Response, state: State) -> SessionResponse:
    """Missing fields 422 ``login_invalid``, wrong credentials 401, blocked member 403 ``member_blocked``."""
    token = state.accounts.login(body.email, body.password)
    return _open_session(state, request, response, token)


@router.post("/guest", response_model=SessionResponse)
def guest(request: Request, response: Response, state: State) -> SessionResponse:
    """Guest session: market data is readable, every personal API answers 403."""
    token = state.accounts.guest()
    return _open_session(state, request, response, token)


@router.post("/logout", status_code=204, response_class=Response)
def logout(request: Request, state: State) -> Response:
    _drop_previous(state, request)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.put("/tutorial", response_model=SessionResponse)
def put_tutorial(body: TutorialUpdate, request: Request, principal: Session, state: State) -> SessionResponse:
    """Tutorial completed or skipped. Members: stored on the account. Guests: stored on the guest session
    only. Repeating the same value changes nothing."""
    token = request.cookies.get(SESSION_COOKIE) or ""
    state.accounts.set_tutorial(token, principal, body.completed)
    return session_response(state.accounts.principal(token))


# --------------------------------------------------------------------------- social login


@router.get("/social/providers", response_model=SocialProvidersResponse)
def social_providers(state: State) -> SocialProvidersResponse:
    return SocialProvidersResponse(
        items=[
            SocialProviderOut(id=p.id, label=p.label, development=p.development)
            for p in state.accounts.social.providers.values()
        ]
    )


def _callback_uri(provider: str) -> str:
    return f"{SOCIAL_PREFIX}/{provider}/callback"


@router.get("/social/{provider}/authorize", status_code=302, response_class=RedirectResponse)
def social_authorize(
    provider: str, state: State, return_to: str | None = Query(default=None, alias="returnTo")
) -> RedirectResponse:
    """Start the code flow: store a single-use ``state`` bound to this browser (cookie) and redirect to
    the provider's consent screen."""
    url, binding = state.accounts.social.start(provider, _callback_uri(provider), return_to)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        STATE_COOKIE,
        binding,
        httponly=True,
        samesite="lax",
        secure=state.settings.cookie_secure,
        path=SOCIAL_PREFIX,
        max_age=600,
    )
    return response


_SOCIAL_REASONS = {
    "social_cancelled": "cancelled",
    "social_state_invalid": "failed",
    "social_failed": "failed",
    "social_email_in_use": "email_in_use",
    "member_blocked": "blocked",
}


@router.get("/social/{provider}/callback", status_code=302, response_class=RedirectResponse)
def social_callback(
    provider: str,
    request: Request,
    state: State,
    state_param: str | None = Query(default=None, alias="state"),
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Verify ``state`` (single use, unexpired, same browser) and log in or create the member. Cancel or
    failure returns to ``/login?social=<reason>`` so the user can choose again."""
    try:
        identity, return_to = state.accounts.social.finish(
            provider, state_param, request.cookies.get(STATE_COOKIE), code, error, _callback_uri(provider)
        )
        token, created = state.accounts.social_login(identity)
    except ApiError as exc:
        response = RedirectResponse(
            "/login?" + urlencode({"social": _SOCIAL_REASONS.get(exc.code, "failed")}), status_code=302
        )
        response.delete_cookie(STATE_COOKIE, path=SOCIAL_PREFIX)
        return response
    _drop_previous(state, request)
    # A new member always starts at the initial setup; the web guard sends a set-up member onward.
    response = RedirectResponse("/onboarding" if created else return_to, status_code=302)
    _set_session_cookie(state, response, token)
    response.delete_cookie(STATE_COOKIE, path=SOCIAL_PREFIX)
    return response


@router.post("/social/mock/idp/consent", response_model=MockIdpRedirect)
def mock_idp_consent(body: MockIdpConsent, state: State) -> MockIdpRedirect:
    """Development mock provider only: the consent screen's [동의하고 계속]. Issues a single-use code and
    tells the screen where to send the browser (the BFF callback with ``code`` and ``state``)."""
    provider = state.accounts.social.provider("mock")
    if not isinstance(provider, MockProvider) or body.redirect_uri != _callback_uri("mock"):
        raise ApiError(400, "mock_idp_invalid", "허용되지 않은 redirect_uri입니다.")
    code = provider.consent(body.email, body.display_name, body.redirect_uri)
    return MockIdpRedirect(redirect_to=f"{body.redirect_uri}?{urlencode({'code': code, 'state': body.state})}")
