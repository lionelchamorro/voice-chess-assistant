"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Callable

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import structlog

from voice_chess_server.api.router import board, health, signaling
from voice_chess_server.core.config import Settings, get_settings
from voice_chess_server.core.logging import configure_logging
from voice_chess_server.services.orchestrator import BotOrchestrator
from voice_chess_server.services.session_manager import SessionManager
from voice_chess_server.services.signaling import IceServerConfig, SmallWebRTCSignalingService

log = structlog.get_logger()
OrchestratorFactory = Callable[[Settings, SessionManager], BotOrchestrator]


def lifespan_factory(
    settings: Settings,
    orchestrator_factory: OrchestratorFactory | None,
):
    """Initialize and tear down runtime services."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level, settings.log_file)

        app.state.settings = settings
        app.state.session_manager = SessionManager()
        app.state.bot_orchestrator = (
            orchestrator_factory(settings, app.state.session_manager)
            if orchestrator_factory is not None
            else BotOrchestrator(
                settings=settings,
                session_manager=app.state.session_manager,
            )
        )
        app.state.signaling_service = SmallWebRTCSignalingService(
            ice_servers=tuple(IceServerConfig(urls=url) for url in settings.stun_urls)
        )
        # Warm the per-connection audio models in the background so the first
        # "Join voice" doesn't pay the cold-load cost.
        app.state.voice_warmup_task = asyncio.create_task(app.state.bot_orchestrator.warmup())

        yield

        if not app.state.voice_warmup_task.done():
            app.state.voice_warmup_task.cancel()
        await app.state.signaling_service.shutdown()

    return lifespan


def create_app(
    settings: Settings | None = None,
    orchestrator_factory: OrchestratorFactory | None = None,
) -> FastAPI:
    """Create the FastAPI application."""

    resolved_settings = settings or get_settings()
    app = FastAPI(
        title=resolved_settings.app_name,
        lifespan=lifespan_factory(resolved_settings, orchestrator_factory),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_timing_header(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Process-Time"] = f"{time.perf_counter() - started:.6f}"
        return response

    app.include_router(health.router)
    app.include_router(signaling.router)
    app.include_router(board.router)
    return app


def run() -> None:
    """Run a local development server."""

    settings = get_settings()
    uvicorn.run(
        "voice_chess_server.main:create_app", factory=True, host=settings.host, port=settings.port
    )
