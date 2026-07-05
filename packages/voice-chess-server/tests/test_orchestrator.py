import asyncio
import shutil

import chess
import pytest
from voice_chess_server.core.config import Settings
from voice_chess_server.services.board_state import BoardCommandError
from voice_chess_server.services.orchestrator import BotOrchestrator, SpeechPacer
from voice_chess_server.services.session_manager import SessionManager


class _FakeToolParams:
    def __init__(self, arguments: dict | None = None) -> None:
        self.arguments = arguments or {}
        self.results: list[dict] = []

    async def result_callback(self, result: dict) -> None:
        self.results.append(result)


def _make_orchestrator() -> tuple[BotOrchestrator, SessionManager]:
    settings = Settings(deepgram_api_key="x", openai_api_key="x", elevenlabs_api_key="x")
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)
    return orchestrator, session_manager


async def test_tool_handler_returns_result_on_success() -> None:
    orchestrator, session_manager = _make_orchestrator()

    async def action(_arguments: dict) -> dict:
        return {"ok": True}

    tool = orchestrator._tool_handler(
        "session-1",
        "noop_tool",
        started_summary="starting",
        action=action,
        completed_summary=lambda _args, _result: "done",
    )
    params = _FakeToolParams()
    await tool(params)

    assert params.results == [{"ok": True}]
    traces = session_manager._tool_calls["session-1"]
    assert [trace.status for trace in traces] == ["started", "completed"]
    assert traces[-1].summary == "done"


async def test_tool_handler_surfaces_board_command_error_without_hanging() -> None:
    orchestrator, session_manager = _make_orchestrator()

    async def action(_arguments: dict) -> dict:
        raise BoardCommandError("illegal_move", "The requested move is not legal.")

    tool = orchestrator._tool_handler(
        "session-1",
        "make_move",
        started_summary="starting",
        action=action,
        completed_summary=lambda _args, _result: "unused",
    )
    params = _FakeToolParams({"from_square": "e2", "to_square": "e5"})
    await tool(params)

    assert params.results == [
        {"error": {"code": "illegal_move", "message": "The requested move is not legal."}}
    ]
    traces = session_manager._tool_calls["session-1"]
    assert traces[-1].status == "completed"
    assert "Rejected" in traces[-1].summary


async def test_tool_handler_surfaces_missing_arguments_without_raising() -> None:
    orchestrator, session_manager = _make_orchestrator()

    async def action(arguments: dict) -> dict:
        return {"value": arguments["required_key"]}

    tool = orchestrator._tool_handler(
        "session-1",
        "needs_argument",
        started_summary="starting",
        action=action,
        completed_summary=lambda _args, _result: "unused",
    )
    params = _FakeToolParams({})
    await tool(params)

    assert params.results[0]["error"]["code"] == "invalid_arguments"


async def test_tool_handler_surfaces_unexpected_exception_as_internal_error() -> None:
    orchestrator, _session_manager = _make_orchestrator()

    async def action(_arguments: dict) -> dict:
        raise RuntimeError("boom")

    tool = orchestrator._tool_handler(
        "session-1",
        "flaky_tool",
        started_summary="starting",
        action=action,
        completed_summary=lambda _args, _result: "unused",
    )
    params = _FakeToolParams()
    await tool(params)  # must not raise

    assert params.results[0]["error"]["code"] == "internal_error"


async def test_notify_manual_move_is_a_noop_without_an_active_session() -> None:
    orchestrator, session_manager = _make_orchestrator()
    board_state = session_manager.get_board_state("session-1")
    # No pipeline is running for this session; this must not raise.
    from voice_chess_server.schemas.protocol import MoveDescriptor

    move = MoveDescriptor(
        ply=1,
        san="e4",
        uci="e2e4",
        **{
            "from": "e2",
            "to": "e4",
            "fenAfter": board_state.fen,
            "color": "white",
            "piece": "pawn",
        },
    )
    await orchestrator.notify_manual_move("session-1", move)


async def test_analyze_with_engine_reports_unavailable_when_no_binary_configured() -> None:
    settings = Settings(
        deepgram_api_key="x", openai_api_key="x", elevenlabs_api_key="x", stockfish_path=None
    )
    orchestrator = BotOrchestrator(settings=settings, session_manager=SessionManager())

    with pytest.raises(BoardCommandError) as exc_info:
        await orchestrator._analyze_with_engine(chess.Board())
    assert exc_info.value.code == "engine_unavailable"


async def test_analyze_with_engine_reports_unavailable_for_missing_binary() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        stockfish_path="/definitely/not/a/real/engine-binary",
    )
    orchestrator = BotOrchestrator(settings=settings, session_manager=SessionManager())

    with pytest.raises(BoardCommandError) as exc_info:
        await orchestrator._analyze_with_engine(chess.Board())
    assert exc_info.value.code == "engine_unavailable"


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="stockfish binary not installed")
async def test_analyze_with_engine_returns_a_legal_best_move() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        engine_analysis_depth=8,
    )
    orchestrator = BotOrchestrator(settings=settings, session_manager=SessionManager())

    board = chess.Board()
    result = await orchestrator._analyze_with_engine(board)

    assert result["bestMoveUci"] is not None
    assert chess.Move.from_uci(result["bestMoveUci"]) in board.legal_moves
    assert result["evaluation"] != "unknown"


async def test_speech_pacer_passes_through_when_turn_has_no_text() -> None:
    pacer = SpeechPacer()
    pacer.on_llm_response_start()

    # No spoken text this turn: the tool must not be delayed at all.
    await asyncio.wait_for(pacer.await_speech_lead(timeout=5.0, lead=5.0), timeout=0.1)


async def test_speech_pacer_releases_when_bot_starts_speaking() -> None:
    pacer = SpeechPacer()
    pacer.on_llm_response_start()
    pacer.on_llm_text()

    released = asyncio.Event()

    async def paced_action() -> None:
        await pacer.await_speech_lead(timeout=5.0, lead=0.0)
        released.set()

    task = asyncio.create_task(paced_action())
    await asyncio.sleep(0.05)
    assert not released.is_set()

    pacer.on_bot_started_speaking()
    await asyncio.wait_for(released.wait(), timeout=1.0)
    await task


async def test_speech_pacer_skips_wait_when_announcement_already_played() -> None:
    pacer = SpeechPacer()
    pacer.on_llm_response_start()
    pacer.on_llm_text()
    pacer.on_bot_started_speaking()
    pacer.on_bot_stopped_speaking()

    # Speech for this turn already finished; do not stall the mutation.
    await asyncio.wait_for(pacer.await_speech_lead(timeout=5.0, lead=5.0), timeout=0.1)


async def test_speech_pacer_times_out_when_speech_never_starts() -> None:
    pacer = SpeechPacer()
    pacer.on_llm_response_start()
    pacer.on_llm_text()

    await asyncio.wait_for(pacer.await_speech_lead(timeout=0.05, lead=5.0), timeout=1.0)


async def test_paced_tool_handler_waits_for_speech() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        speech_pacing_lead_seconds=0.0,
        speech_pacing_wait_timeout_seconds=5.0,
    )
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    pacer = SpeechPacer()
    pacer.on_llm_response_start()
    pacer.on_llm_text()
    orchestrator._speech_pacers["session-1"] = pacer

    action_ran = asyncio.Event()

    async def action(_arguments: dict) -> dict:
        action_ran.set()
        return {"ok": True}

    tool = orchestrator._tool_handler(
        "session-1",
        "make_move",
        started_summary="starting",
        action=action,
        completed_summary=lambda _args, _result: "done",
        pace_with_speech=True,
    )
    params = _FakeToolParams({"from_square": "e2", "to_square": "e4"})

    task = asyncio.create_task(tool(params))
    await asyncio.sleep(0.05)
    assert not action_ran.is_set(), "the board mutation must wait for the voice"

    pacer.on_bot_started_speaking()
    await asyncio.wait_for(action_ran.wait(), timeout=1.0)
    await task
    assert params.results == [{"ok": True}]


async def test_unpaced_tool_handler_ignores_pending_speech() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        speech_pacing_wait_timeout_seconds=5.0,
    )
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    pacer = SpeechPacer()
    pacer.on_llm_response_start()
    pacer.on_llm_text()
    orchestrator._speech_pacers["session-1"] = pacer

    async def action(_arguments: dict) -> dict:
        return {"ok": True}

    tool = orchestrator._tool_handler(
        "session-1",
        "get_board_state",
        started_summary="starting",
        action=action,
        completed_summary=lambda _args, _result: "done",
    )
    params = _FakeToolParams()

    # Read-only tools must not be gated on speech at all.
    await asyncio.wait_for(tool(params), timeout=0.5)
    assert params.results == [{"ok": True}]


class _FakeTask:
    def __init__(self) -> None:
        self.queued: list = []

    async def queue_frames(self, frames: list) -> None:
        self.queued.extend(frames)


class _FakeSpeakFrame:
    def __init__(self, text: str) -> None:
        self.text = text


async def test_paced_tool_speaks_the_say_argument_then_waits_for_audio() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        speech_pacing_lead_seconds=0.0,
        speech_pacing_wait_timeout_seconds=5.0,
    )
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    from voice_chess_server.services.orchestrator import _ActiveSession

    fake_task = _FakeTask()
    orchestrator._active_sessions["session-1"] = _ActiveSession(
        task=fake_task,
        llm_messages_append_frame_cls=type(None),
        tts_speak_frame_cls=_FakeSpeakFrame,
    )
    pacer = SpeechPacer()
    pacer.on_llm_response_start()  # tool-only completion: no streamed text
    orchestrator._speech_pacers["session-1"] = pacer

    action_ran = asyncio.Event()

    async def action(_arguments: dict) -> dict:
        action_ran.set()
        return {"ok": True}

    tool = orchestrator._tool_handler(
        "session-1",
        "make_move",
        started_summary="starting",
        action=action,
        completed_summary=lambda _args, _result: "done",
        pace_with_speech=True,
    )
    params = _FakeToolParams({"san": "e4", "say": "White opens with e4."})

    task = asyncio.create_task(tool(params))
    await asyncio.sleep(0.05)
    # The narration must be queued into TTS before the move applies.
    assert len(fake_task.queued) == 1
    assert fake_task.queued[0].text == "White opens with e4."
    assert not action_ran.is_set(), "the move must wait for the narration audio"

    pacer.on_bot_started_speaking()
    await asyncio.wait_for(action_ran.wait(), timeout=1.0)
    await task
    assert params.results == [{"ok": True}]


async def test_say_is_ignored_when_the_model_already_streamed_text() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        speech_pacing_lead_seconds=0.0,
        speech_pacing_wait_timeout_seconds=0.05,
    )
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    from voice_chess_server.services.orchestrator import _ActiveSession

    fake_task = _FakeTask()
    orchestrator._active_sessions["session-1"] = _ActiveSession(
        task=fake_task,
        llm_messages_append_frame_cls=type(None),
        tts_speak_frame_cls=_FakeSpeakFrame,
    )
    pacer = SpeechPacer()
    pacer.on_llm_response_start()
    pacer.on_llm_text()  # the model narrated in-stream this turn
    orchestrator._speech_pacers["session-1"] = pacer

    async def action(_arguments: dict) -> dict:
        return {"ok": True}

    tool = orchestrator._tool_handler(
        "session-1",
        "make_move",
        started_summary="starting",
        action=action,
        completed_summary=lambda _args, _result: "done",
        pace_with_speech=True,
    )
    params = _FakeToolParams({"san": "e4", "say": "duplicate narration"})
    await tool(params)

    # No duplicated speech: nothing queued into TTS.
    assert fake_task.queued == []
    assert params.results == [{"ok": True}]


def test_llm_extra_params_default_to_low_latency_for_gpt5() -> None:
    settings = Settings(
        deepgram_api_key="x", openai_api_key="x", elevenlabs_api_key="x", llm_model="gpt-5-mini"
    )
    orchestrator = BotOrchestrator(settings=settings, session_manager=SessionManager())

    extra = orchestrator._llm_extra_params()

    assert extra == {
        "parallel_tool_calls": False,
        "reasoning_effort": "minimal",
        "verbosity": "low",
    }


def test_llm_extra_params_omit_gpt5_knobs_for_other_models() -> None:
    settings = Settings(
        deepgram_api_key="x", openai_api_key="x", elevenlabs_api_key="x", llm_model="gpt-4o"
    )
    orchestrator = BotOrchestrator(settings=settings, session_manager=SessionManager())

    extra = orchestrator._llm_extra_params()

    assert extra == {"parallel_tool_calls": False}


def test_llm_extra_params_respect_explicit_overrides() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        llm_model="gpt-5",
        llm_reasoning_effort="low",
        llm_verbosity="medium",
    )
    orchestrator = BotOrchestrator(settings=settings, session_manager=SessionManager())

    extra = orchestrator._llm_extra_params()

    assert extra["reasoning_effort"] == "low"
    assert extra["verbosity"] == "medium"


def test_spanish_language_flows_into_stt_and_tts() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        cartesia_api_key="x",
        cartesia_voice_id="voice-es",
        tts_provider="cartesia",
    )
    orchestrator = BotOrchestrator(settings=settings, session_manager=SessionManager())
    runtime = orchestrator._load_runtime()

    stt = orchestrator._build_stt(runtime)
    assert str(stt._settings.language) == "multi"

    tts = orchestrator._build_tts(runtime)
    assert str(tts._settings.language) == "es"


def test_stt_model_override_is_applied() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        stt_model="nova-2-general",
        stt_language="es",
    )
    orchestrator = BotOrchestrator(settings=settings, session_manager=SessionManager())
    runtime = orchestrator._load_runtime()

    stt = orchestrator._build_stt(runtime)
    assert stt._settings.model == "nova-2-general"
    assert str(stt._settings.language) == "es"


async def test_say_with_leaked_markers_is_sanitized_before_speaking() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        speech_pacing_lead_seconds=0.0,
        speech_pacing_wait_timeout_seconds=0.05,
    )
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    from voice_chess_server.services.orchestrator import _ActiveSession

    fake_task = _FakeTask()
    orchestrator._active_sessions["session-1"] = _ActiveSession(
        task=fake_task,
        llm_messages_append_frame_cls=type(None),
        tts_speak_frame_cls=_FakeSpeakFrame,
    )
    pacer = SpeechPacer()
    pacer.on_llm_response_start()
    orchestrator._speech_pacers["session-1"] = pacer

    async def action(_arguments: dict) -> dict:
        return {"ok": True}

    tool = orchestrator._tool_handler(
        "session-1",
        "make_move",
        started_summary="starting",
        action=action,
        completed_summary=lambda _args, _result: "done",
        pace_with_speech=True,
    )
    params = _FakeToolParams({"san": "e4", "say": "Las blancas abren con e4 [[move e2e4]]"})
    await tool(params)

    assert len(fake_task.queued) == 1
    spoken = fake_task.queued[0].text
    assert "[[" not in spoken and "]]" not in spoken
    assert spoken == "Las blancas abren con e4"


async def test_say_that_is_only_markers_is_not_spoken_at_all() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        speech_pacing_lead_seconds=0.0,
        speech_pacing_wait_timeout_seconds=0.05,
    )
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    from voice_chess_server.services.orchestrator import _ActiveSession

    fake_task = _FakeTask()
    orchestrator._active_sessions["session-1"] = _ActiveSession(
        task=fake_task,
        llm_messages_append_frame_cls=type(None),
        tts_speak_frame_cls=_FakeSpeakFrame,
    )
    pacer = SpeechPacer()
    pacer.on_llm_response_start()
    orchestrator._speech_pacers["session-1"] = pacer

    async def action(_arguments: dict) -> dict:
        return {"ok": True}

    tool = orchestrator._tool_handler(
        "session-1",
        "make_move",
        started_summary="starting",
        action=action,
        completed_summary=lambda _args, _result: "done",
        pace_with_speech=True,
    )
    params = _FakeToolParams({"san": "e4", "say": "[[move e2e4]]"})
    await tool(params)

    assert fake_task.queued == []
    assert params.results == [{"ok": True}]


async def test_board_events_and_text_prompts_reach_the_live_pipeline() -> None:
    settings = Settings(deepgram_api_key="x", openai_api_key="x", elevenlabs_api_key="x")
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    # No active session: prompt is not consumed, board event is a no-op.
    assert await orchestrator.deliver_text_prompt("s1", "hola") is False
    await orchestrator.notify_board_event("s1", "load_fen", {"fen": "8/8/8/8/8/8/8/8 w - - 0 1"})

    class _AppendFrame:
        def __init__(self, messages: list, run_llm: bool) -> None:
            self.messages = messages
            self.run_llm = run_llm

    from voice_chess_server.services.orchestrator import _ActiveSession

    fake_task = _FakeTask()
    orchestrator._active_sessions["s1"] = _ActiveSession(
        task=fake_task,
        llm_messages_append_frame_cls=_AppendFrame,
    )

    assert await orchestrator.deliver_text_prompt("s1", "repasemos mi partida") is True
    await orchestrator.notify_board_event("s1", "load_pgn", {"pgn": "1. e4 c5", "start_ply": 0})

    assert len(fake_task.queued) == 2
    assert fake_task.queued[0].messages[0]["content"] == "repasemos mi partida"
    assert "1. e4 c5" in fake_task.queued[1].messages[0]["content"]
    assert all(frame.run_llm for frame in fake_task.queued)


class _RecordingAppendFrame:
    def __init__(self, messages: list, run_llm: bool) -> None:
        self.messages = messages
        self.run_llm = run_llm


def _orchestrator_with_fake_pipeline(
    session_manager: SessionManager, **settings_overrides
) -> tuple[BotOrchestrator, "_FakeTask"]:
    from voice_chess_server.services.orchestrator import _ActiveSession

    settings = Settings(
        deepgram_api_key="x", openai_api_key="x", elevenlabs_api_key="x", **settings_overrides
    )
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)
    fake_task = _FakeTask()
    orchestrator._active_sessions["s1"] = _ActiveSession(
        task=fake_task,
        llm_messages_append_frame_cls=_RecordingAppendFrame,
    )
    return orchestrator, fake_task


async def test_kickoff_prefers_loaded_fen_over_auto_demo() -> None:
    session_manager = SessionManager()
    orchestrator, fake_task = _orchestrator_with_fake_pipeline(
        session_manager,
        auto_start_demo_on_voice_connect=True,
        auto_start_demo_prompt="DEMO RUY LOPEZ",
    )
    await session_manager.agent_load_fen(
        "s1", fen="r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
    )

    handled = await orchestrator._kick_off_initial_turn("s1")

    assert handled is True
    content = fake_task.queued[0].messages[0]["content"]
    assert "analyze_position" in content
    assert "DEMO RUY LOPEZ" not in content


async def test_kickoff_prefers_loaded_pgn_and_instructs_board_review() -> None:
    session_manager = SessionManager()
    orchestrator, fake_task = _orchestrator_with_fake_pipeline(
        session_manager,
        auto_start_demo_on_voice_connect=True,
        auto_start_demo_prompt="DEMO RUY LOPEZ",
    )
    await session_manager.agent_load_pgn("s1", pgn="1. e4 c5 2. Nf3 d6", start_ply=0)

    handled = await orchestrator._kick_off_initial_turn("s1")

    assert handled is True
    content = fake_task.queued[0].messages[0]["content"]
    assert "[[next <san>]]" in content
    assert "1. e4 c5" in content


async def test_kickoff_runs_demo_on_pristine_board() -> None:
    session_manager = SessionManager()
    orchestrator, fake_task = _orchestrator_with_fake_pipeline(
        session_manager,
        auto_start_demo_on_voice_connect=True,
        auto_start_demo_prompt="DEMO RUY LOPEZ",
    )

    handled = await orchestrator._kick_off_initial_turn("s1")

    assert handled is True
    assert fake_task.queued[0].messages[0]["content"] == "DEMO RUY LOPEZ"


async def test_kickoff_falls_back_to_plain_intro_without_demo() -> None:
    session_manager = SessionManager()
    orchestrator, fake_task = _orchestrator_with_fake_pipeline(session_manager)

    handled = await orchestrator._kick_off_initial_turn("s1")

    assert handled is False
    assert fake_task.queued == []


def test_classify_centipawn_loss_thresholds() -> None:
    from voice_chess_server.services.orchestrator import classify_centipawn_loss

    assert classify_centipawn_loss(None) == "desconocida"
    assert classify_centipawn_loss(0) == "excelente"
    assert classify_centipawn_loss(20) == "excelente"
    assert classify_centipawn_loss(50) == "buena"
    assert classify_centipawn_loss(100) == "imprecisión"
    assert classify_centipawn_loss(250) == "error"
    assert classify_centipawn_loss(251) == "blunder"


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="stockfish binary not installed")
async def test_evaluate_move_uses_a_persistent_engine() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        engine_quick_time_seconds=0.05,
    )
    orchestrator = BotOrchestrator(settings=settings, session_manager=SessionManager())

    board = chess.Board()
    first = await orchestrator._evaluate_move_with_engine(board, board.parse_san("e4"))
    engine_after_first = orchestrator._engine
    assert engine_after_first is not None
    assert first["verdict"] in {"excelente", "buena"}
    assert first["centipawnLoss"] is not None

    second = await orchestrator._evaluate_move_with_engine(board, board.parse_san("Nf3"))
    assert orchestrator._engine is engine_after_first, "engine must be reused, not respawned"
    assert second["move"] == "Nf3"

    await orchestrator.shutdown()
    assert orchestrator._engine is None


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="stockfish binary not installed")
async def test_evaluate_move_tool_rejects_illegal_moves() -> None:
    settings = Settings(
        deepgram_api_key="x",
        openai_api_key="x",
        elevenlabs_api_key="x",
        engine_quick_time_seconds=0.05,
    )
    session_manager = SessionManager()
    orchestrator = BotOrchestrator(settings=settings, session_manager=session_manager)

    tool = orchestrator._tool_evaluate_move("s1")
    params = _FakeToolParams({"san": "Ke5"})
    await tool(params)
    assert params.results[0]["error"]["code"] == "illegal_move"

    good = _FakeToolParams({"san": "e4"})
    await tool(good)
    assert good.results[0]["verdict"] in {"excelente", "buena"}

    await orchestrator.shutdown()
