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
    "요약·감성·시세는 `unavailable`, 인증·계좌·관심종목·AI 예시 답변은 BFF mock이며 `metadata`로 출처를 표시한다."
)


def create_app(settings: Settings | None = None, *, services: AdminServices | None = None) -> FastAPI:
    """``services`` lets tests replace the ledger, Neo4j, sandbox and process launcher."""
    settings = settings or Settings.from_env()
    admin = services or build_admin_services(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        scheduler = BriefingScheduler(admin.briefings) if settings.briefing_scheduler else None
        if scheduler:
            scheduler.start()
        try:
            yield
        finally:
            if scheduler:
                scheduler.stop()

    app = FastAPI(title="Zoop BFF", version="0.1.0", description=DESCRIPTION, lifespan=lifespan)
    app.state.zoop = AppState(settings, admin.provider, admin, AccountStore(admin.db, admin.clock))
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
