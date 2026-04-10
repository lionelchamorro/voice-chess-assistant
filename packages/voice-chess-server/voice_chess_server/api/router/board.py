"""Board WebSocket routes."""

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
import structlog

from voice_chess_server.api.dependencies import get_session_manager
from voice_chess_server.services.session_manager import SessionManager

log = structlog.get_logger()
router = APIRouter(tags=["board"])


@router.websocket("/ws/sessions/{session_id}/board")
async def board_socket(
    websocket: WebSocket,
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
) -> None:
    """Synchronize canonical board state with connected clients."""

    await session_manager.connect(session_id, websocket)
    try:
        while True:
            payload = await websocket.receive_json()
            await session_manager.handle_raw_command(session_id, payload)
    except WebSocketDisconnect:
        log.info("board_socket_disconnected", session_id=session_id)
    finally:
        await session_manager.disconnect(session_id, websocket)
