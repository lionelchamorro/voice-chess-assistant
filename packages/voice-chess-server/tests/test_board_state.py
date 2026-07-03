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


def test_apply_move_accepts_san() -> None:
    state = BoardSessionState(session_id="test-session")

    move, board_state = state.apply_move(san="Nf3")

    assert move.san == "Nf3"
    assert move.uci == "g1f3"
    assert board_state.turn == "black"


def test_apply_move_rejects_illegal_san() -> None:
    state = BoardSessionState(session_id="test-session")

    try:
        state.apply_move(san="Ke2")
    except BoardCommandError as exc:
        assert exc.code == "illegal_move"
    else:
        raise AssertionError("Expected BoardCommandError to be raised.")


def test_apply_move_defaults_promotion_to_queen() -> None:
    state = BoardSessionState(session_id="test-session")
    state.load_fen("8/P6k/8/8/8/8/8/7K w - - 0 1")

    move, _board_state = state.apply_move("a7", "a8")

    assert move.promotion == "queen"
    assert move.san == "a8=Q"


def test_step_review_walks_forward_and_returns_to_live() -> None:
    state = BoardSessionState(session_id="test-session")
    state.load_pgn("1. e4 c5 2. Nf3 d6", start_ply=0)

    first = state.step_review(1)
    assert first.view_mode == "review"
    assert first.review_ply == 1
    assert first.last_move is not None
    assert first.last_move.san == "e4"

    second = state.step_review(1)
    assert second.last_move is not None
    assert second.last_move.san == "c5"

    state.step_review(1)
    final = state.step_review(1)
    assert final.view_mode == "live"
    assert final.review_ply is None


def test_step_review_rejects_out_of_range() -> None:
    state = BoardSessionState(session_id="test-session")
    state.load_pgn("1. e4 c5", start_ply=0)

    try:
        state.step_review(-1)
    except BoardCommandError as exc:
        assert exc.code == "invalid_ply"
    else:
        raise AssertionError("Expected BoardCommandError to be raised.")


def test_variation_explores_without_touching_the_game() -> None:
    state = BoardSessionState(session_id="test-session")
    state.load_pgn("1. e4 c5 2. Nf3 d6", start_ply=2)
    review_fen = state.snapshot().fen

    move, board_state = state.play_variation_move(san="Nc3")

    assert move.san == "Nc3"
    assert board_state.variation == ["Nc3"]
    assert board_state.last_move is not None
    assert board_state.last_move.san == "Nc3"
    assert board_state.fen != review_fen
    # The recorded game is untouched.
    assert [descriptor.san for descriptor in board_state.move_history] == [
        "e4",
        "c5",
        "Nf3",
        "d6",
    ]

    second_move, second_state = state.play_variation_move(san="Nc6")
    assert second_move.san == "Nc6"
    assert second_state.variation == ["Nc3", "Nc6"]

    restored = state.end_variation()
    assert restored.fen == review_fen
    assert restored.variation == []


def test_variation_requires_review_mode() -> None:
    state = BoardSessionState(session_id="test-session")

    try:
        state.play_variation_move(san="e4")
    except BoardCommandError as exc:
        assert exc.code == "variation_requires_review"
    else:
        raise AssertionError("Expected BoardCommandError to be raised.")


def test_navigate_clears_active_variation() -> None:
    state = BoardSessionState(session_id="test-session")
    state.load_pgn("1. e4 c5 2. Nf3 d6", start_ply=2)
    state.play_variation_move(san="Nc3")

    board_state = state.navigate("review", 1)

    assert board_state.variation == []
    assert board_state.review_ply == 1


def test_review_last_move_tracks_the_reviewed_ply() -> None:
    state = BoardSessionState(session_id="test-session")
    state.load_pgn("1. e4 c5 2. Nf3 d6")

    reviewed = state.navigate("review", 2)
    assert reviewed.last_move is not None
    assert reviewed.last_move.san == "c5"

    start = state.navigate("review", 0)
    assert start.last_move is None
