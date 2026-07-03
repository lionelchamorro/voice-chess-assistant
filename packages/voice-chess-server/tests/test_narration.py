from voice_chess_server.core.config import Settings
from voice_chess_server.services.narration import (
    ActionCue,
    ChoreographyState,
    StreamMarkerParser,
    move_arguments,
    parse_action_spec,
)
from voice_chess_server.services.orchestrator import BotOrchestrator
from voice_chess_server.services.session_manager import SessionManager


def test_parser_strips_marker_and_anchors_at_clean_offset() -> None:
    parser = StreamMarkerParser()

    clean, cues = parser.feed("White grabs the center [[move e2e4]] right away.")

    assert clean == "White grabs the center  right away."
    assert len(cues) == 1
    assert cues[0].spec == "move e2e4"
    assert cues[0].anchor == len("White grabs the center ")


def test_parser_handles_marker_split_across_chunks() -> None:
    parser = StreamMarkerParser()

    clean_parts = []
    cues = []
    for chunk in ["The knight ", "jumps [[mo", "ve g1f", "3]] and hits e5."]:
        clean, chunk_cues = parser.feed(chunk)
        clean_parts.append(clean)
        cues.extend(chunk_cues)

    assert "".join(clean_parts) == "The knight jumps  and hits e5."
    assert [cue.spec for cue in cues] == ["move g1f3"]
    assert cues[0].anchor == len("The knight jumps ")


def test_parser_holds_back_single_trailing_bracket() -> None:
    parser = StreamMarkerParser()

    clean, cues = parser.feed("array[")
    assert clean == "array"
    assert cues == []

    clean, cues = parser.feed("0] is fine")
    assert clean == "[0] is fine"
    assert cues == []


def test_parser_treats_runaway_marker_as_literal_text() -> None:
    parser = StreamMarkerParser()

    long_text = "[[" + "x" * 250
    clean, cues = parser.feed(long_text)

    assert clean == long_text
    assert cues == []


def test_parser_flush_drops_unterminated_marker() -> None:
    parser = StreamMarkerParser()

    clean, cues = parser.feed("Final words [[move e2")
    assert clean == "Final words "
    assert cues == []

    assert parser.flush() == ""


def test_parser_multiple_markers_in_one_chunk() -> None:
    parser = StreamMarkerParser()

    clean, cues = parser.feed("First [[reset]] then [[move e2e4]] done.")

    assert clean == "First  then  done."
    assert [cue.spec for cue in cues] == ["reset", "move e2e4"]
    assert cues[0].anchor == len("First ")
    assert cues[1].anchor == len("First  then ")


def test_choreography_fires_cue_when_anchor_word_is_spoken() -> None:
    state = ChoreographyState()
    state.on_generation_start()
    state.on_playout_start()
    # Anchor just past the first word: fires exactly on the second word.
    state.register(ActionCue(anchor=8, spec="move e2e4", sequence=1))

    assert state.on_word_spoken("White") == []  # spoken: 6
    fired = state.on_word_spoken("grabs")  # spoken: 12 >= 8
    assert [cue.spec for cue in fired] == ["move e2e4"]
    assert state.pending_count == 0


def test_choreography_fires_in_order_and_drains_on_bot_stop() -> None:
    state = ChoreographyState()
    state.on_generation_start()
    state.on_playout_start()
    state.register(ActionCue(anchor=5, spec="reset", sequence=1))
    state.register(ActionCue(anchor=100, spec="move e2e4", sequence=1))

    fired = state.on_word_spoken("Hello")
    assert [cue.spec for cue in fired] == ["reset"]

    drained = state.drain()
    assert [cue.spec for cue in drained] == ["move e2e4"]
    assert state.pending_count == 0


def test_choreography_does_not_fire_future_completion_cues() -> None:
    state = ChoreographyState()
    state.on_generation_start()  # completion 1 generating
    state.on_playout_start()  # completion 1 playing
    state.on_generation_start()  # completion 2 already generating
    state.register(ActionCue(anchor=0, spec="move e7e5", sequence=2))

    # Words of completion 1 still playing must not trigger completion 2 cues.
    assert state.on_word_spoken("still") == []
    assert state.drain() == []

    state.on_playout_start()  # completion 2 reaches the playout edge
    fired = state.on_word_spoken("now")
    assert [cue.spec for cue in fired] == ["move e7e5"]


def test_choreography_clear_on_interruption() -> None:
    state = ChoreographyState()
    state.on_generation_start()
    state.on_playout_start()
    state.register(ActionCue(anchor=50, spec="move e2e4", sequence=1))

    state.clear()

    assert state.on_word_spoken("anything") == []
    assert state.drain() == []


def test_parse_action_spec_and_move_arguments() -> None:
    action = parse_action_spec("move e2e4")
    assert action is not None
    assert action.verb == "move"

    uci = move_arguments("e7e8q")
    assert uci["from_square"] == "e7"
    assert uci["to_square"] == "e8"
    assert uci["promotion"] == "queen"

    san = move_arguments("Nf3")
    assert san["san"] == "Nf3"
    assert san["from_square"] is None

    assert parse_action_spec("   ") is None


async def test_execute_narrated_action_moves_the_board() -> None:
    settings = Settings(deepgram_api_key="x", openai_api_key="x", elevenlabs_api_key="x")
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    await orchestrator.execute_narrated_action("s1", "move e2e4")
    await orchestrator.execute_narrated_action("s1", "move Nf6")

    snapshot = session_manager.get_board_state("s1")
    assert [move.san for move in snapshot.move_history] == ["e4", "Nf6"]
    traces = session_manager._tool_calls["s1"]
    assert traces[-1].tool_name == "narrate:move"


async def test_execute_narrated_action_review_and_variation_flow() -> None:
    settings = Settings(deepgram_api_key="x", openai_api_key="x", elevenlabs_api_key="x")
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    await session_manager.agent_load_pgn("s1", pgn="1. e4 c5 2. Nf3 d6", start_ply=0)
    await orchestrator.execute_narrated_action("s1", "next")
    await orchestrator.execute_narrated_action("s1", "next")
    await orchestrator.execute_narrated_action("s1", "var Nc3")
    snapshot = session_manager.get_board_state("s1")
    assert snapshot.variation == ["Nc3"]

    await orchestrator.execute_narrated_action("s1", "endvar")
    snapshot = session_manager.get_board_state("s1")
    assert snapshot.variation == []
    assert snapshot.review_ply == 2


async def test_execute_narrated_action_survives_illegal_moves_and_unknown_verbs() -> None:
    settings = Settings(deepgram_api_key="x", openai_api_key="x", elevenlabs_api_key="x")
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    # Illegal move: traced as rejected, does not raise.
    await orchestrator.execute_narrated_action("s1", "move e2e5")
    traces = session_manager._tool_calls["s1"]
    assert "Rejected" in traces[-1].summary

    # Unknown verb: silently ignored.
    await orchestrator.execute_narrated_action("s1", "teleport a1h8")

    snapshot = session_manager.get_board_state("s1")
    assert snapshot.move_history == []


async def test_execute_narrated_action_highlight_and_clear() -> None:
    settings = Settings(deepgram_api_key="x", openai_api_key="x", elevenlabs_api_key="x")
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    await orchestrator.execute_narrated_action("s1", "highlight e4 f7")
    snapshot = session_manager.get_board_state("s1")
    assert snapshot.highlights[0].squares == ["e4", "f7"]

    await orchestrator.execute_narrated_action("s1", "clear")
    snapshot = session_manager.get_board_state("s1")
    assert snapshot.highlights == []


def test_strip_markers_removes_leaked_markers_from_speech() -> None:
    from voice_chess_server.services.narration import strip_markers

    assert (
        strip_markers("Las blancas abren con peón cuatro [[move e2e4]]")
        == "Las blancas abren con peón cuatro "
    )
    assert strip_markers("[[reset]][[move e2e4]]") == ""
    assert strip_markers("sin marcas") == "sin marcas"


async def test_execute_narrated_action_goto_jumps_review() -> None:
    settings = Settings(deepgram_api_key="x", openai_api_key="x", elevenlabs_api_key="x")
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    # Game loaded live (final position) — the coach jumps to the start.
    await session_manager.agent_load_pgn("s1", pgn="1. e4 c5 2. Nf3 d6")
    await orchestrator.execute_narrated_action("s1", "goto 0")

    snapshot = session_manager.get_board_state("s1")
    assert snapshot.view_mode == "review"
    assert snapshot.review_ply == 0

    await orchestrator.execute_narrated_action("s1", "next")
    snapshot = session_manager.get_board_state("s1")
    assert snapshot.review_ply == 1
    assert snapshot.last_move is not None
    assert snapshot.last_move.san == "e4"

    # Malformed ply: ignored without raising.
    await orchestrator.execute_narrated_action("s1", "goto abc")


def test_parser_strips_the_exact_leaked_hybrid_marker() -> None:
    # Real leak observed in a session: tool name + embedded say inside the
    # marker, longer than the old 64-char runaway limit.
    leaked = (
        "2.. e5: respuesta simétrica, lucha por el centro [[show_next_move "
        'say:"2.. e5: respuesta simétrica, lucha por el centro."]]'
    )
    parser = StreamMarkerParser()

    clean, cues = parser.feed(leaked)

    assert "[[" not in clean and "]]" not in clean
    assert clean == "2.. e5: respuesta simétrica, lucha por el centro "
    assert len(cues) == 1

    action = parse_action_spec(cues[0].spec)
    assert action is not None
    assert action.verb == "next"
    assert action.args == []


def test_parse_action_spec_normalizes_tool_name_aliases() -> None:
    for raw, expected in [
        ("show_next_move", "next"),
        ("show_previous_move", "prev"),
        ("make_move e2e4", "move"),
        ("reset_board", "reset"),
        ("go_to_move 4", "goto"),
        ("play_variation_move Nc3", "var"),
        ("end_variation", "endvar"),
        ("clear_highlights", "clear"),
    ]:
        action = parse_action_spec(raw)
        assert action is not None
        assert action.verb == expected, raw


def test_parse_action_spec_drops_embedded_say_variants() -> None:
    for raw in [
        'next say:"la idea del centro"',
        "next say='la idea'",
        "move e2e4 say:rapido",
    ]:
        action = parse_action_spec(raw)
        assert action is not None
        assert all("say" not in arg for arg in action.args), raw
        assert "la" not in action.args, raw
