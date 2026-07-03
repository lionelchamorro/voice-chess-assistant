from voice_chess_server.schemas.protocol import (
    BoardRequestMoveCommand,
    MoveDescriptor,
    MoveRequestPayload,
)
from voice_chess_server.services.session_manager import SessionManager


class _DeadSocket:
    """A stand-in for a WebSocket whose connection already dropped."""

    async def send_json(self, payload: dict) -> None:
        raise RuntimeError('Cannot call "send" once a close message has been sent.')


class _RecordingSocket:
    def __init__(self) -> None:
        self.received: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.received.append(payload)


async def test_broadcast_drops_dead_socket_without_raising() -> None:
    manager = SessionManager()
    dead = _DeadSocket()
    alive = _RecordingSocket()
    manager._clients["session-1"].add(dead)  # type: ignore[arg-type]
    manager._clients["session-1"].add(alive)  # type: ignore[arg-type]

    await manager.broadcast("session-1", {"type": "board.state"})

    assert alive.received == [{"type": "board.state"}]
    assert dead not in manager._clients["session-1"]
    assert alive in manager._clients["session-1"]


async def test_manual_move_hook_fires_for_user_sourced_moves() -> None:
    manager = SessionManager()
    calls: list[tuple[str, MoveDescriptor]] = []

    async def hook(session_id: str, move: MoveDescriptor) -> None:
        calls.append((session_id, move))

    manager.set_manual_move_hook(hook)

    command = BoardRequestMoveCommand(
        messageId="cmd-1",
        sessionId="session-1",
        timestamp="2026-01-01T00:00:00Z",
        payload=MoveRequestPayload(source="user", move={"from": "e2", "to": "e4"}),
    )
    await manager.handle_command("session-1", command)

    assert len(calls) == 1
    session_id, move = calls[0]
    assert session_id == "session-1"
    assert move.san == "e4"


async def test_manual_move_hook_does_not_fire_without_registration() -> None:
    manager = SessionManager()

    command = BoardRequestMoveCommand(
        messageId="cmd-1",
        sessionId="session-1",
        timestamp="2026-01-01T00:00:00Z",
        payload=MoveRequestPayload(source="user", move={"from": "e2", "to": "e4"}),
    )
    # Should not raise even though no hook is registered.
    await manager.handle_command("session-1", command)


async def test_load_pgn_command_fires_board_event_hook() -> None:
    from voice_chess_server.schemas.protocol import BoardRequestLoadPgnCommand, LoadPgnPayload

    manager = SessionManager()
    events: list[tuple[str, str, dict]] = []

    async def hook(session_id: str, kind: str, payload: dict) -> None:
        events.append((session_id, kind, payload))

    manager.set_board_event_hook(hook)

    command = BoardRequestLoadPgnCommand(
        messageId="cmd-1",
        sessionId="session-1",
        timestamp="2026-01-01T00:00:00Z",
        payload=LoadPgnPayload(source="user", pgn="1. e4 c5", startPly=0),
    )
    await manager.handle_command("session-1", command)

    assert events == [("session-1", "load_pgn", {"pgn": "1. e4 c5", "start_ply": 0})]


async def test_typed_prompt_goes_to_live_coach_when_hook_accepts() -> None:
    from voice_chess_server.schemas.protocol import (
        ConversationRequestDemoCommand,
        ConversationRequestDemoPayload,
    )

    manager = SessionManager()
    delivered: list[str] = []

    async def hook(session_id: str, prompt: str) -> bool:
        delivered.append(prompt)
        return True

    manager.set_text_prompt_hook(hook)

    command = ConversationRequestDemoCommand(
        messageId="cmd-1",
        sessionId="session-1",
        timestamp="2026-01-01T00:00:00Z",
        payload=ConversationRequestDemoPayload(source="user", prompt="repasemos mi partida"),
    )
    await manager.handle_command("session-1", command)

    assert delivered == ["repasemos mi partida"]
    messages = manager._conversation_messages["session-1"]
    # The user's prompt lands in the transcript; no canned simulator reply.
    assert [m.role for m in messages] == ["user"]


async def test_typed_prompt_falls_back_to_simulator_without_live_coach() -> None:
    from voice_chess_server.schemas.protocol import (
        ConversationRequestDemoCommand,
        ConversationRequestDemoPayload,
    )

    manager = SessionManager()

    async def hook(session_id: str, prompt: str) -> bool:
        return False  # no active pipeline

    manager.set_text_prompt_hook(hook)

    command = ConversationRequestDemoCommand(
        messageId="cmd-1",
        sessionId="session-1",
        timestamp="2026-01-01T00:00:00Z",
        payload=ConversationRequestDemoPayload(source="user", prompt="Play e2 to e4"),
    )
    await manager.handle_command("session-1", command)

    messages = manager._conversation_messages["session-1"]
    roles = [m.role for m in messages]
    assert roles.count("assistant") == 1  # simulator replied as before
