from voice_chess_server.schemas.protocol import BoardHighlight
from voice_chess_server.services.board_state import BoardCommandError, BoardSessionState


def test_apply_move_updates_live_state() -> None:
    state = BoardSessionState(session_id="test-session")

    move, board_state = state.apply_move("e2", "e4")

    assert move.san == "e4"
    assert board_state.turn == "black"
    assert board_state.last_move is not None
    assert board_state.last_move.uci == "e2e4"
    assert board_state.highlights == []


def test_load_pgn_and_navigate_review_mode() -> None:
    state = BoardSessionState(session_id="test-session")

    live_state = state.load_pgn("1. e4 c5 2. Nf3 d6")
    review_state = state.navigate("review", 2)

    assert live_state.move_history[-1].san == "d6"
    assert review_state.view_mode == "review"
    assert review_state.review_ply == 2
    assert review_state.move_history[-1].san == "d6"


def test_move_in_review_mode_is_rejected() -> None:
    state = BoardSessionState(session_id="test-session")
    state.load_pgn("1. e4 c5 2. Nf3 d6")
    state.navigate("review", 1)

    try:
        state.apply_move("d2", "d4")
    except BoardCommandError as exc:
        assert exc.code == "review_mode_locked"
    else:
        raise AssertionError("Expected BoardCommandError to be raised.")


def test_undo_move_restores_previous_turn() -> None:
    state = BoardSessionState(session_id="test-session")
    state.apply_move("e2", "e4")

    move, board_state = state.undo_move()

    assert move.san == "e4"
    assert board_state.turn == "white"
    assert board_state.move_history == []


def test_clear_highlights_removes_all_markers() -> None:
    state = BoardSessionState(session_id="test-session")
    state.set_highlights(
        [BoardHighlight(id="highlight-1", squares=["e4"], color="green", label="focus")]
    )

    board_state = state.clear_highlights()

    assert board_state.highlights == []
