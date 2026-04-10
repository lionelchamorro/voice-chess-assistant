"""In-memory session manager for board sockets and board state."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter
import structlog

from voice_chess_server.schemas.protocol import (
    AnnotationSetEvent,
    AnnotationSetPayload,
    BoardAnnotation,
    BoardNavigateCommand,
    BoardHighlight,
    BoardRequestLoadFenCommand,
    BoardRequestLoadPgnCommand,
    BoardRequestMoveCommand,
    BoardRequestResetCommand,
    BoardResetEvent,
    BoardStateEvent,
    BoardStatePayload,
    EventOrigin,
    HighlightSetEvent,
    HighlightSetPayload,
    SessionErrorEvent,
    SessionErrorPayload,
    SessionReadyEvent,
    SessionReadyPayload,
    VoiceChessClientCommand,
)
from voice_chess_server.services.board_state import BoardCommandError, BoardSessionState

log = structlog.get_logger()

COMMAND_ADAPTER = TypeAdapter(VoiceChessClientCommand)


class SessionManager:
    """Manage board sessions and connected WebSocket clients."""

    def __init__(self) -> None:
        self._sessions: dict[str, BoardSessionState] = {}
        self._clients: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept and initialize a WebSocket client."""

        await websocket.accept()
        async with self._lock:
            self._clients[session_id].add(websocket)
            state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))

        try:
            await websocket.send_json(self._ready_event(session_id).model_dump(by_alias=True, mode="json"))
            await websocket.send_json(
                self._state_event(session_id, state.snapshot(), origin="session-init").model_dump(
                    by_alias=True,
                    mode="json",
                )
            )
        except WebSocketDisconnect:
            await self.disconnect(session_id, websocket)

    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        """Remove a disconnected client."""

        async with self._lock:
            clients = self._clients.get(session_id)
            if clients is None:
                return
            clients.discard(websocket)
            if not clients:
                self._clients.pop(session_id, None)

    async def handle_raw_command(self, session_id: str, payload: dict) -> None:
        """Parse and execute a raw incoming command payload."""

        command = COMMAND_ADAPTER.validate_python(payload)
        await self.handle_command(session_id, command)

    async def handle_command(self, session_id: str, command: VoiceChessClientCommand) -> None:
        """Apply a command and broadcast the resulting event(s)."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        try:
            if isinstance(command, BoardRequestMoveCommand):
                move = command.payload.move
                descriptor, board_state = state.apply_move(
                    from_square=str(move["from"]),
                    to_square=str(move["to"]),
                    promotion=move.get("promotion"),
                )
                await self.broadcast(
                    session_id,
                    {
                        "protocolVersion": "1.0.0",
                        "direction": "event",
                        "type": "board.move_applied",
                        "messageId": self._message_id("move"),
                        "sessionId": session_id,
                        "timestamp": self._timestamp(),
                        "payload": {
                            "origin": "user-command",
                            "move": descriptor.model_dump(by_alias=True, mode="json"),
                            "board": board_state.model_dump(by_alias=True, mode="json"),
                        },
                    },
                )
                return

            if isinstance(command, BoardNavigateCommand):
                board_state = state.navigate(
                    mode=command.payload.mode,
                    ply=command.payload.ply,
                )
                await self.broadcast(
                    session_id,
                    self._state_event(session_id, board_state, origin="user-command").model_dump(
                        by_alias=True,
                        mode="json",
                    ),
                )
                return

            if isinstance(command, BoardRequestResetCommand):
                board_state = state.reset()
                event = BoardResetEvent(
                    messageId=self._message_id("reset"),
                    sessionId=session_id,
                    timestamp=self._timestamp(),
                    payload={"origin": "user-command", "board": board_state},
                )
                await self.broadcast(session_id, event.model_dump(by_alias=True, mode="json"))
                return

            if isinstance(command, BoardRequestLoadFenCommand):
                board_state = state.load_fen(command.payload.fen)
                await self.broadcast(
                    session_id,
                    self._state_event(session_id, board_state, origin="user-command").model_dump(
                        by_alias=True,
                        mode="json",
                    ),
                )
                return

            if isinstance(command, BoardRequestLoadPgnCommand):
                board_state = state.load_pgn(
                    command.payload.pgn,
                    start_ply=command.payload.start_ply,
                )
                await self.broadcast(
                    session_id,
                    self._state_event(session_id, board_state, origin="user-command").model_dump(
                        by_alias=True,
                        mode="json",
                    ),
                )
        except BoardCommandError as exc:
            log.info("board_command_rejected", session_id=session_id, code=exc.code)
            await self.broadcast_error(session_id, code=exc.code, message=exc.message, recoverable=True)

    def get_board_state(self, session_id: str):
        """Return the current canonical board state for a session."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        return state.snapshot()

    async def agent_apply_move(
        self,
        session_id: str,
        from_square: str,
        to_square: str,
        promotion: str | None = None,
    ) -> dict:
        """Apply a move on behalf of the agent and broadcast the result."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        descriptor, board_state = state.apply_move(
            from_square=from_square,
            to_square=to_square,
            promotion=promotion,
        )
        payload = {
            "protocolVersion": "1.0.0",
            "direction": "event",
            "type": "board.move_applied",
            "messageId": self._message_id("move"),
            "sessionId": session_id,
            "timestamp": self._timestamp(),
            "payload": {
                "origin": "agent-tool",
                "move": descriptor.model_dump(by_alias=True, mode="json"),
                "board": board_state.model_dump(by_alias=True, mode="json"),
            },
        }
        await self.broadcast(session_id, payload)
        return payload["payload"]

    async def agent_load_fen(self, session_id: str, fen: str) -> dict:
        """Load a FEN position on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        board_state = state.load_fen(fen)
        event = self._state_event(session_id, board_state, origin="agent-tool").model_dump(
            by_alias=True,
            mode="json",
        )
        await self.broadcast(session_id, event)
        return event["payload"]

    async def agent_load_pgn(self, session_id: str, pgn: str, start_ply: int | None = None) -> dict:
        """Load PGN on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        board_state = state.load_pgn(pgn, start_ply=start_ply)
        event = self._state_event(session_id, board_state, origin="agent-tool").model_dump(
            by_alias=True,
            mode="json",
        )
        await self.broadcast(session_id, event)
        return event["payload"]

    async def agent_reset(self, session_id: str) -> dict:
        """Reset the board on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        board_state = state.reset()
        event = BoardResetEvent(
            messageId=self._message_id("reset"),
            sessionId=session_id,
            timestamp=self._timestamp(),
            payload={"origin": "agent-tool", "board": board_state},
        ).model_dump(by_alias=True, mode="json")
        await self.broadcast(session_id, event)
        return event["payload"]

    async def agent_set_highlights(
        self,
        session_id: str,
        highlights: list[BoardHighlight],
    ) -> dict:
        """Replace board highlights on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        state.set_highlights(highlights)
        event = HighlightSetEvent(
            messageId=self._message_id("highlight"),
            sessionId=session_id,
            timestamp=self._timestamp(),
            payload=HighlightSetPayload(highlights=highlights),
        ).model_dump(by_alias=True, mode="json")
        await self.broadcast(session_id, event)
        return event["payload"]

    async def agent_set_annotations(
        self,
        session_id: str,
        annotations: list[BoardAnnotation],
    ) -> dict:
        """Replace board annotations on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        state.set_annotations(annotations)
        event = AnnotationSetEvent(
            messageId=self._message_id("annotation"),
            sessionId=session_id,
            timestamp=self._timestamp(),
            payload=AnnotationSetPayload(annotations=annotations),
        ).model_dump(by_alias=True, mode="json")
        await self.broadcast(session_id, event)
        return event["payload"]

    async def broadcast_highlights(
        self,
        session_id: str,
        highlights: list[BoardHighlight],
    ) -> None:
        """Broadcast highlight updates from the agent/backend."""

        await self.agent_set_highlights(session_id, highlights)

    async def broadcast(self, session_id: str, payload: dict) -> None:
        """Broadcast payload to all clients in a session."""

        clients = list(self._clients.get(session_id, set()))
        stale_clients: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_json(payload)
            except WebSocketDisconnect:
                stale_clients.append(client)

        for client in stale_clients:
            await self.disconnect(session_id, client)

    async def broadcast_error(
        self,
        session_id: str,
        code: str,
        message: str,
        recoverable: bool,
    ) -> None:
        """Broadcast a typed session error event."""

        event = SessionErrorEvent(
            messageId=self._message_id("error"),
            sessionId=session_id,
            timestamp=self._timestamp(),
            payload=SessionErrorPayload(code=code, message=message, recoverable=recoverable),
        )
        await self.broadcast(session_id, event.model_dump(by_alias=True, mode="json"))

    def _ready_event(self, session_id: str) -> SessionReadyEvent:
        return SessionReadyEvent(
            messageId=self._message_id("ready"),
            sessionId=session_id,
            timestamp=self._timestamp(),
            payload=SessionReadyPayload(
                capabilities={
                    "manualMoves": True,
                    "pgnNavigation": True,
                    "boardAnnotations": True,
                    "boardHighlights": True,
                }
            ),
        )

    def _state_event(
        self,
        session_id: str,
        board_state,
        origin: EventOrigin,
    ) -> BoardStateEvent:
        return BoardStateEvent(
            messageId=self._message_id("state"),
            sessionId=session_id,
            timestamp=self._timestamp(),
            payload=BoardStatePayload(origin=origin, board=board_state),
        )

    def _message_id(self, prefix: str) -> str:
        return f"{prefix}_{datetime.now(tz=UTC).timestamp():.6f}"

    def _timestamp(self) -> str:
        return datetime.now(tz=UTC).isoformat()
