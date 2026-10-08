"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .accounts import AccountStore
from .admin_services import AdminServices, BriefingScheduler, build_admin_services
from .config import Settings
from .deps import AppState
from .errors import install_error_handlers
from .market_data import MarketData, build_market_data
from .routers import (
    admin_ai,
    admin_auth,
    admin_briefings,
    admin_dashboard,
    admin_feedback,
    admin_insights,
    admin_jobs,
    admin_members,
    admin_pipeline,
    auth,
    briefings,
    chat,
    feedback,
    market,
    me,
    system,
    telemetry,
)

DESCRIPTION = (
    "줍(Zoop) 프로토타입 BFF. InvestMate PoC의 승인 이슈(inspect())를 요구사항명세서 v0.2 §8 경로로 제공한다. "
    "사용자에게 보이는 그래프는 활성 게시 버전과 관리자 검수 기록이다(`/api/admin/*`은 관리자 전용). "
    "문서 요약·기업별 판정은 S1 worker의 인용·별도 의미 검증과 앱 수입을 마친 저장값만 제공한다. 기업·시장 요약은 `unavailable`이며 회차 판정은 기존 불변 저장값만 읽는다. 일반 GET은 모델을 호출하지 않는다. 시세는 설정한 공급자(토스증권 Open API 또는 무키 공개 출처)의 값을 출처·기준 시각과 함께 주고 "
    "없으면 사유와 함께 `unavailable`, 인증·계좌·관심종목·AI 예시 답변은 BFF mock이며 `metadata`로 출처를 표시한다."
)


def create_app(
    settings: Settings | None = None,
    *,
    services: AdminServices | None = None,
    quotes: MarketData | None = None,
) -> FastAPI:
    """``services`` lets tests replace the ledger, Neo4j, sandbox and process launcher; ``quotes`` the quote providers."""
    settings = settings or Settings.from_env()
    admin = services or build_admin_services(settings)
    quotes = quotes or build_market_data(
        settings.quote_provider,
        toss_client_id=settings.toss_client_id,
        toss_client_secret=settings.toss_client_secret,
        toss_base_url=settings.toss_base_url,
        yahoo_base_url=settings.yahoo_base_url,
        timeout=settings.quote_timeout_seconds,
        metrics_enabled=settings.metrics_enabled,
        naver_urls=settings.naver_urls,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        scheduler = BriefingScheduler(admin.briefings) if settings.briefing_scheduler else None
        if scheduler:
            scheduler.start()
        try:
            yield
        finally:
            app.state.zoop.chats.close()
            if scheduler:
                scheduler.stop()

    app = FastAPI(title="Zoop BFF", version="0.1.0", description=DESCRIPTION, lifespan=lifespan)
    app.state.zoop = AppState(settings, admin.provider, admin, AccountStore(admin.db, admin.clock), quotes)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Content-Type"],
        )
    install_error_handlers(app)
    for module in (
        system,
        auth,
        me,
        market,
        briefings,
        chat,
        admin_auth,
        admin_dashboard,
        admin_pipeline,
        admin_jobs,
        admin_ai,
        admin_briefings,
        telemetry,
        feedback,
        admin_insights,
        admin_feedback,
        admin_members,
    ):
        app.include_router(module.router)
    return app
