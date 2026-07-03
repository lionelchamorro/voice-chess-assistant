"""In-memory session manager for board sockets and board state."""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter

from voice_chess_server.schemas.protocol import (
    AnnotationSetEvent,
    AnnotationSetPayload,
    BoardAnnotation,
    BoardHighlight,
    BoardNavigateCommand,
    BoardRequestLoadFenCommand,
    BoardRequestLoadPgnCommand,
    BoardRequestMoveCommand,
    BoardRequestResetCommand,
    BoardResetEvent,
    BoardStateEvent,
    BoardStatePayload,
    ConversationMessage,
    ConversationMessageEvent,
    ConversationMessagePayload,
    ConversationRequestDemoCommand,
    ConversationState,
    EventOrigin,
    HighlightSetEvent,
    HighlightSetPayload,
    MoveDescriptor,
    SessionErrorEvent,
    SessionErrorPayload,
    SessionReadyEvent,
    SessionReadyPayload,
    ToolCallEvent,
    ToolCallPayload,
    ToolCallTrace,
    VoiceChessClientCommand,
    VoiceStateEvent,
    VoiceStatePayload,
)
from voice_chess_server.services.board_state import BoardCommandError, BoardSessionState

log = structlog.get_logger()

COMMAND_ADAPTER = TypeAdapter(VoiceChessClientCommand)
MOVE_PROMPT_PATTERN = re.compile(r"\b([a-h][1-8])\s*(?:to|-)\s*([a-h][1-8])\b", re.IGNORECASE)
SQUARE_PATTERN = re.compile(r"[a-h][1-8]", re.IGNORECASE)

ManualMoveHook = Callable[[str, MoveDescriptor], Awaitable[None]]
BoardEventHook = Callable[[str, str, dict], Awaitable[None]]
TextPromptHook = Callable[[str, str], Awaitable[bool]]


class SessionManager:
    """Manage board sessions and connected WebSocket clients."""

    def __init__(self) -> None:
        self._sessions: dict[str, BoardSessionState] = {}
        self._clients: dict[str, set[WebSocket]] = defaultdict(set)
        self._conversation_state: dict[str, ConversationState] = {}
        self._conversation_messages: dict[str, list[ConversationMessage]] = defaultdict(list)
        self._tool_calls: dict[str, list[ToolCallTrace]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._manual_move_hook: ManualMoveHook | None = None
        self._board_event_hook: BoardEventHook | None = None
        self._text_prompt_hook: TextPromptHook | None = None

    def set_manual_move_hook(self, hook: ManualMoveHook | None) -> None:
        """Register a callback invoked when the user moves a piece by hand.

        Lets the running voice pipeline learn about manual moves it did not
        make itself, so the assistant can react to them mid-conversation.
        """

        self._manual_move_hook = hook

    def set_board_event_hook(self, hook: BoardEventHook | None) -> None:
        """Register a callback for user board actions beyond single moves.

        Fired when the user loads a FEN/PGN or resets the board from the UI,
        so the running voice pipeline learns about position changes it did
        not make itself.
        """

        self._board_event_hook = hook

    def set_text_prompt_hook(self, hook: TextPromptHook | None) -> None:
        """Register a callback that routes typed prompts to the live coach.

        The hook returns True when an active voice pipeline consumed the
        prompt; otherwise the deterministic demo simulator handles it (used
        by e2e tests and credential-less sessions).
        """

        self._text_prompt_hook = hook

    async def _fire_board_event(self, session_id: str, kind: str, payload: dict) -> None:
        if self._board_event_hook is None:
            return
        try:
            await self._board_event_hook(session_id, kind, payload)
        except Exception:  # noqa: BLE001 - a hook failure must not break the board flow
            log.exception("board_event_hook_failed", session_id=session_id, kind=kind)

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept and initialize a WebSocket client."""

        await websocket.accept()
        async with self._lock:
            self._clients[session_id].add(websocket)
            state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
            conversation_state = self._conversation_state.setdefault(session_id, "idle")

        try:
            await websocket.send_json(
                self._ready_event(session_id).model_dump(by_alias=True, mode="json")
            )
            await websocket.send_json(
                self._state_event(session_id, state.snapshot(), origin="session-init").model_dump(
                    by_alias=True,
                    mode="json",
                )
            )
            await websocket.send_json(
                self._voice_state_event(session_id, conversation_state).model_dump(
                    by_alias=True,
                    mode="json",
                )
            )
            for message in self._conversation_messages.get(session_id, []):
                await websocket.send_json(
                    self._conversation_message_event(session_id, message).model_dump(
                        by_alias=True,
                        mode="json",
                    )
                )
            for tool_call in self._tool_calls.get(session_id, []):
                await websocket.send_json(
                    self._tool_call_event(session_id, tool_call).model_dump(
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
                if command.payload.source == "user" and self._manual_move_hook is not None:
                    try:
                        await self._manual_move_hook(session_id, descriptor)
                    except Exception:
                        log.exception("manual_move_hook_failed", session_id=session_id)
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
                await self._fire_board_event(session_id, "reset", {})
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
                await self._fire_board_event(session_id, "load_fen", {"fen": command.payload.fen})
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
                await self._fire_board_event(
                    session_id,
                    "load_pgn",
                    {"pgn": command.payload.pgn, "start_ply": command.payload.start_ply},
                )
                return

            if isinstance(command, ConversationRequestDemoCommand):
                prompt = command.payload.prompt.strip()
                if prompt and self._text_prompt_hook is not None:
                    try:
                        delivered = await self._text_prompt_hook(session_id, prompt)
                    except Exception:  # noqa: BLE001 - fall back to the simulator
                        log.exception("text_prompt_hook_failed", session_id=session_id)
                        delivered = False
                    if delivered:
                        # The live coach took the prompt; reflect it in the
                        # transcript (typed text never crosses the STT path).
                        await self.add_conversation_message(session_id, "user", prompt)
                        return
                await self.run_demo_prompt(session_id, command.payload.prompt)
                return
        except BoardCommandError as exc:
            log.info("board_command_rejected", session_id=session_id, code=exc.code)
            await self.broadcast_error(
                session_id, code=exc.code, message=exc.message, recoverable=True
            )

    def get_board_state(self, session_id: str):
        """Return the current canonical board state for a session."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        return state.snapshot()

    async def agent_apply_move(
        self,
        session_id: str,
        from_square: str | None = None,
        to_square: str | None = None,
        promotion: str | None = None,
        san: str | None = None,
    ) -> dict:
        """Apply a move on behalf of the agent and broadcast the result."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        descriptor, board_state = state.apply_move(
            from_square=from_square,
            to_square=to_square,
            promotion=promotion,
            san=san,
        )
        return await self._broadcast_move_applied(session_id, descriptor, board_state)

    async def agent_review_step(self, session_id: str, offset: int) -> dict:
        """Step the reviewed game by `offset` plies on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        board_state = state.step_review(offset)
        event = self._state_event(session_id, board_state, origin="agent-tool").model_dump(
            by_alias=True,
            mode="json",
        )
        await self.broadcast(session_id, event)
        return event["payload"]

    async def agent_go_to_ply(self, session_id: str, ply: int) -> dict:
        """Jump the review to a specific ply on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        board_state = state.navigate("review", ply)
        event = self._state_event(session_id, board_state, origin="agent-tool").model_dump(
            by_alias=True,
            mode="json",
        )
        await self.broadcast(session_id, event)
        return event["payload"]

    async def agent_go_live(self, session_id: str) -> dict:
        """Return the board to the live position on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        board_state = state.navigate("live", None)
        event = self._state_event(session_id, board_state, origin="agent-tool").model_dump(
            by_alias=True,
            mode="json",
        )
        await self.broadcast(session_id, event)
        return event["payload"]

    async def agent_play_variation_move(
        self,
        session_id: str,
        from_square: str | None = None,
        to_square: str | None = None,
        promotion: str | None = None,
        san: str | None = None,
    ) -> dict:
        """Play a hypothetical sideline move on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        descriptor, board_state = state.play_variation_move(
            from_square=from_square,
            to_square=to_square,
            promotion=promotion,
            san=san,
        )
        return await self._broadcast_move_applied(session_id, descriptor, board_state)

    async def agent_end_variation(self, session_id: str) -> dict:
        """Drop the current sideline on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        board_state = state.end_variation()
        event = self._state_event(session_id, board_state, origin="agent-tool").model_dump(
            by_alias=True,
            mode="json",
        )
        await self.broadcast(session_id, event)
        return event["payload"]

    async def _broadcast_move_applied(self, session_id: str, descriptor, board_state) -> dict:
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

    async def agent_undo_move(self, session_id: str) -> dict:
        """Undo the latest move on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        move, board_state = state.undo_move()
        payload = {
            "protocolVersion": "1.0.0",
            "direction": "event",
            "type": "board.move_applied",
            "messageId": self._message_id("undo"),
            "sessionId": session_id,
            "timestamp": self._timestamp(),
            "payload": {
                "origin": "agent-tool",
                "move": move.model_dump(by_alias=True, mode="json"),
                "board": board_state.model_dump(by_alias=True, mode="json"),
            },
        }
        await self.broadcast(session_id, payload)
        return payload["payload"]

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

    async def agent_clear_highlights(self, session_id: str) -> dict:
        """Clear board highlights on behalf of the agent."""

        state = self._sessions.setdefault(session_id, BoardSessionState(session_id=session_id))
        state.clear_highlights()
        event = HighlightSetEvent(
            messageId=self._message_id("highlight"),
            sessionId=session_id,
            timestamp=self._timestamp(),
            payload=HighlightSetPayload(highlights=[]),
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

    async def set_conversation_state(self, session_id: str, state: ConversationState) -> None:
        """Broadcast and persist conversation state."""

        self._conversation_state[session_id] = state
        event = self._voice_state_event(session_id, state).model_dump(by_alias=True, mode="json")
        await self.broadcast(session_id, event)

    async def add_conversation_message(
        self, session_id: str, role: str, content: str
    ) -> ConversationMessage:
        """Persist and broadcast a conversation message."""

        message = ConversationMessage(
            id=self._message_id(role),
            role=role,
            content=content,
            createdAt=self._timestamp(),
        )
        self._conversation_messages[session_id].append(message)
        await self.broadcast(
            session_id,
            self._conversation_message_event(session_id, message).model_dump(
                by_alias=True, mode="json"
            ),
        )
        return message

    async def trace_tool_call(
        self,
        session_id: str,
        tool_name: str,
        status: str,
        summary: str,
        arguments: dict | None = None,
    ) -> ToolCallTrace:
        """Persist and broadcast a tool call trace."""

        tool_call = ToolCallTrace(
            id=self._message_id("tool"),
            toolName=tool_name,
            status=status,
            summary=summary,
            arguments=arguments,
            createdAt=self._timestamp(),
        )
        self._tool_calls[session_id].append(tool_call)
        await self.broadcast(
            session_id,
            self._tool_call_event(session_id, tool_call).model_dump(by_alias=True, mode="json"),
        )
        return tool_call

    async def run_demo_prompt(self, session_id: str, prompt: str) -> None:
        """Simulate a deterministic voicebot turn for the demo and E2E tests."""

        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise BoardCommandError("empty_prompt", "A demo prompt is required.")

        await self.set_conversation_state(session_id, "listening")
        await self.add_conversation_message(session_id, "user", normalized_prompt)
        await self.set_conversation_state(session_id, "thinking")

        lower_prompt = normalized_prompt.lower()
        assistant_reply = (
            "I can inspect the position, make a move, reset the board, or manage highlights."
        )

        if "undo" in lower_prompt or "take back" in lower_prompt:
            await self.trace_tool_call(
                session_id, "undo_move", "started", "Undoing the latest move."
            )
            result = await self.agent_undo_move(session_id)
            await self.trace_tool_call(
                session_id, "undo_move", "completed", "Latest move reverted."
            )
            assistant_reply = f"I undid the last move. It is now {result['board']['turn']} to move."
        elif "clear highlight" in lower_prompt:
            await self.trace_tool_call(
                session_id,
                "clear_highlights",
                "started",
                "Clearing board highlights.",
            )
            await self.agent_clear_highlights(session_id)
            await self.trace_tool_call(
                session_id,
                "clear_highlights",
                "completed",
                "Board highlights cleared.",
            )
            assistant_reply = "I cleared the current highlights from the board."
        elif match := MOVE_PROMPT_PATTERN.search(lower_prompt):
            from_square, to_square = match.groups()
            arguments = {"from_square": from_square, "to_square": to_square}
            await self.trace_tool_call(
                session_id, "make_move", "started", "Applying a move.", arguments
            )
            result = await self.agent_apply_move(
                session_id, from_square=from_square, to_square=to_square
            )
            await self.trace_tool_call(
                session_id,
                "make_move",
                "completed",
                f"Applied {result['move']['san']}.",
                arguments,
            )
            assistant_reply = f"I played {result['move']['san']} and updated the live board."
        elif "reset" in lower_prompt:
            await self.trace_tool_call(session_id, "reset_board", "started", "Resetting the board.")
            await self.agent_reset(session_id)
            await self.trace_tool_call(
                session_id, "reset_board", "completed", "Board reset to the initial position."
            )
            assistant_reply = "I reset the board to the starting position."
        elif "highlight" in lower_prompt:
            squares = SQUARE_PATTERN.findall(lower_prompt)
            squares = [square.lower() for square in squares]
            if not squares:
                squares = ["e4"]
            await self.trace_tool_call(
                session_id,
                "set_highlight",
                "started",
                "Highlighting target squares.",
                {"squares": squares},
            )
            await self.agent_set_highlights(
                session_id,
                [
                    BoardHighlight(
                        id="demo-highlight", squares=squares, color="green", label="focus"
                    )
                ],
            )
            await self.trace_tool_call(
                session_id,
                "set_highlight",
                "completed",
                f"Highlighted {', '.join(squares)}.",
                {"squares": squares},
            )
            assistant_reply = f"I highlighted {', '.join(squares)} on the board."
        else:
            await self.trace_tool_call(
                session_id,
                "get_board_state",
                "started",
                "Inspecting the current board state.",
            )
            snapshot = self.get_board_state(session_id)
            await self.trace_tool_call(
                session_id,
                "get_board_state",
                "completed",
                f"Fetched the live board with {len(snapshot.move_history)} moves.",
            )
            assistant_reply = (
                f"The position is ready. It is {snapshot.turn} to move and the board has "
                f"{len(snapshot.move_history)} moves in its history."
            )

        await self.set_conversation_state(session_id, "speaking")
        await self.add_conversation_message(session_id, "assistant", assistant_reply)

    async def broadcast(self, session_id: str, payload: dict) -> None:
        """Broadcast payload to all clients in a session."""

        clients = list(self._clients.get(session_id, set()))
        stale_clients: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_json(payload)
            except (WebSocketDisconnect, RuntimeError) as exc:
                log.info(
                    "board_broadcast_dropped_stale_client",
                    session_id=session_id,
                    reason=str(exc),
                )
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
                    "conversationDemo": True,
                }
            ),
        )

    def _voice_state_event(self, session_id: str, state: ConversationState) -> VoiceStateEvent:
        return VoiceStateEvent(
            messageId=self._message_id("voice-state"),
            sessionId=session_id,
            timestamp=self._timestamp(),
            payload=VoiceStatePayload(state=state),
        )

    def _conversation_message_event(
        self,
        session_id: str,
        message: ConversationMessage,
    ) -> ConversationMessageEvent:
        return ConversationMessageEvent(
            messageId=self._message_id("conversation"),
            sessionId=session_id,
            timestamp=self._timestamp(),
            payload=ConversationMessagePayload(message=message),
        )

    def _tool_call_event(self, session_id: str, tool_call: ToolCallTrace) -> ToolCallEvent:
        return ToolCallEvent(
            messageId=self._message_id("tool-call"),
            sessionId=session_id,
            timestamp=self._timestamp(),
            payload=ToolCallPayload(toolCall=tool_call),
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
