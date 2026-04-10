"""FastAPI dependencies."""

from starlette.requests import HTTPConnection

from voice_chess_server.core.config import Settings, get_settings
from voice_chess_server.services.orchestrator import BotOrchestrator
from voice_chess_server.services.session_manager import SessionManager
from voice_chess_server.services.signaling import SmallWebRTCSignalingService


def get_runtime_settings() -> Settings:
    """Return runtime settings."""

    return get_settings()


def get_session_manager(connection: HTTPConnection) -> SessionManager:
    """Return app session manager."""

    return connection.app.state.session_manager


def get_signaling_service(connection: HTTPConnection) -> SmallWebRTCSignalingService:
    """Return app signaling service."""

    return connection.app.state.signaling_service


def get_bot_orchestrator(connection: HTTPConnection) -> BotOrchestrator:
    """Return app bot orchestrator."""

    return connection.app.state.bot_orchestrator
