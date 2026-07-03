"""Pipecat runtime orchestration and tool wiring."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import chess
import chess.engine
import structlog

from voice_chess_server.core.config import Settings
from voice_chess_server.schemas.protocol import BoardAnnotation, BoardHighlight, MoveDescriptor
from voice_chess_server.services.board_state import BoardCommandError
from voice_chess_server.services.narration import (
    ChoreographyState,
    StreamMarkerParser,
    move_arguments,
    parse_action_spec,
    strip_markers,
)
from voice_chess_server.services.session_manager import SessionManager
from voice_chess_server.services.signaling import SignalingRuntimeError

log = structlog.get_logger()

ToolAction = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ToolSummary = Callable[[dict[str, Any], dict[str, Any]], str]

# Tools that visibly change the board and therefore synchronize with speech.
PACED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "load_position",
        "load_pgn",
        "make_move",
        "reset_board",
        "undo_move",
        "set_highlight",
        "set_highlights",
        "clear_highlights",
        "set_annotations",
        "show_next_move",
        "show_previous_move",
        "go_to_move",
        "return_to_live",
        "play_variation_move",
        "end_variation",
    }
)


def classify_centipawn_loss(centipawn_loss: int | None) -> str:
    """Map centipawn loss to the verdict vocabulary a coach would use."""

    if centipawn_loss is None:
        return "desconocida"
    if centipawn_loss <= 20:
        return "excelente"
    if centipawn_loss <= 50:
        return "buena"
    if centipawn_loss <= 100:
        return "imprecisión"
    if centipawn_loss <= 250:
        return "error"
    return "blunder"


_SAY_PROPERTY: dict[str, str] = {
    "type": "string",
    "description": (
        "One short spoken sentence about the chess idea, said aloud exactly as "
        "this appears on the board. Plain spoken words only — NEVER put "
        "[[...]] markers inside say, and never both call this tool and write "
        "a marker for the same move."
    ),
}


@dataclass(slots=True)
class _ActiveSession:
    """Bookkeeping for a running voice pipeline, keyed by session id."""

    task: Any
    llm_messages_append_frame_cls: type
    tts_speak_frame_cls: type | None = None


class SpeechPacer:
    """Hold board mutations until the assistant's voice for the turn lands.

    The LLM emits tool calls the moment they are generated, while the TTS
    audio for the sentence announcing them is still being synthesized — so
    the board would always beat the voice. Board-mutating tools wait here:
    if the current completion produced spoken text, the mutation is released
    only once bot audio actually starts (plus a small lead), which makes the
    piece move while the coach is saying it.
    """

    def __init__(self) -> None:
        self._speaking = asyncio.Event()
        self._turn_has_text = False
        self._spoke_this_turn = False

    def on_llm_response_start(self) -> None:
        self._turn_has_text = False
        self._spoke_this_turn = False

    def on_llm_text(self) -> None:
        self._turn_has_text = True

    def on_bot_started_speaking(self) -> None:
        self._spoke_this_turn = True
        self._speaking.set()

    def on_bot_stopped_speaking(self) -> None:
        self._speaking.clear()

    def on_interruption(self) -> None:
        self._speaking.clear()

    @property
    def turn_has_text(self) -> bool:
        """Whether the current LLM completion produced spoken text."""

        return self._turn_has_text

    async def await_speech_lead(self, timeout: float, lead: float) -> None:
        """Wait until this turn's speech is audible before mutating the board."""

        if not self._turn_has_text:
            # The model called the tool without saying anything first; there
            # is no speech to synchronize with.
            return
        if self._spoke_this_turn and not self._speaking.is_set():
            # The announcing sentence already finished playing.
            return
        await self.await_speaking(timeout, lead)

    async def await_speaking(self, timeout: float, lead: float) -> None:
        """Wait for bot audio to be playing, regardless of turn text state.

        Used for narration injected by the server itself (the tool `say`
        argument): the caller queues a TTSSpeakFrame first and then holds the
        board mutation until that audio starts.
        """

        try:
            await asyncio.wait_for(self._speaking.wait(), timeout=timeout)
        except TimeoutError:
            return
        await asyncio.sleep(lead)


class BotOrchestrator:
    """Run the voice pipeline for a negotiated transport."""

    def __init__(self, settings: Settings, session_manager: SessionManager) -> None:
        self._settings = settings
        self._session_manager = session_manager
        self._active_sessions: dict[str, _ActiveSession] = {}
        self._speech_pacers: dict[str, SpeechPacer] = {}
        self._engine: Any = None
        self._engine_lock = asyncio.Lock()
        session_manager.set_manual_move_hook(self.notify_manual_move)
        session_manager.set_board_event_hook(self.notify_board_event)
        session_manager.set_text_prompt_hook(self.deliver_text_prompt)

    def get_runtime_status(self) -> tuple[bool, str | None]:
        """Return whether the voice pipeline can start with current config."""

        try:
            runtime = self._load_runtime()
            self._build_stt(runtime)
            self._build_tts(runtime)
            self._build_llm(runtime)
        except SignalingRuntimeError as exc:
            return False, str(exc)
        return True, None

    async def warmup(self) -> None:
        """Pre-load the per-connection audio models once at startup.

        SileroVADAnalyzer and LocalSmartTurnAnalyzerV3 are instantiated per
        voice connection (they hold per-connection audio state), but loading
        them once here warms the module init, weight files and OS page cache,
        which shaves noticeable time off the first join.
        """

        try:
            runtime = self._load_runtime()
        except SignalingRuntimeError:
            return

        def _load_models() -> None:
            runtime["SileroVADAnalyzer"](params=runtime["VADParams"](stop_secs=0.2))
            runtime["LocalSmartTurnAnalyzerV3"]()

        try:
            await asyncio.to_thread(_load_models)
            log.info("voice_models_warmed_up")
        except Exception:
            log.exception("voice_model_warmup_failed")

    async def notify_manual_move(self, session_id: str, move: MoveDescriptor) -> None:
        """Tell the running pipeline (if any) that the user moved a piece by hand."""

        side_to_move = "las negras" if move.color == "white" else "las blancas"
        content = (
            f"[Tablero] El alumno jugó manualmente {move.san} "
            f"({move.from_square} a {move.to_square}). Ahora mueven {side_to_move}. "
            "Reconócelo brevemente y continúa el análisis."
        )
        await self._push_context_message(session_id, content)

    async def notify_board_event(self, session_id: str, kind: str, payload: dict) -> bool:
        """Tell the running pipeline about UI position changes (FEN/PGN/reset)."""

        if kind == "load_fen":
            content = (
                f"[Tablero] El alumno cargó una posición nueva por FEN: {payload.get('fen')}. "
                "Analízala ahora: llama a analyze_position para obtener la evaluación del "
                "motor y la mejor jugada, y luego explica en voz alta lo esencial de la "
                "posición — quién está mejor y por qué, los planes de cada bando. Puedes "
                "resaltar las casillas clave con [[highlight ...]] mientras lo explicas."
            )
        elif kind == "load_pgn":
            start_ply = payload.get("start_ply")
            situation = (
                f"Está en modo repaso en la jugada {start_ply}."
                if start_ply is not None
                else "El tablero muestra la posición final."
            )
            content = (
                f"[Tablero] El alumno cargó una partida en PGN:\n{payload.get('pgn')}\n"
                f"{situation} Repásala EN EL TABLERO, moviendo las piezas mientras hablas. "
                "Tu PRIMERA marca es siempre [[goto 0]] para poner el tablero al inicio; "
                "después avanza cada movimiento con su marca [[next]] colocada en el "
                "momento exacto en que lo comentas — una frase corta por movimiento, ambos "
                "bandos, en una sola narración fluida. Nunca uses [[reset]] con una partida "
                "cargada (la borraría) y nunca comentes una jugada sin su [[next]]: si la "
                "jugada no aparece en el tablero, el alumno no la ve. En los momentos "
                "críticos usa analyze_position y muestra alternativas con [[var ...]] y "
                "[[endvar]]."
            )
        elif kind == "reset":
            content = (
                "[Tablero] El alumno reinició el tablero a la posición inicial. "
                "Reconócelo brevemente y pregunta qué quiere hacer."
            )
        else:
            return False
        return await self._push_context_message(session_id, content)

    async def deliver_text_prompt(self, session_id: str, prompt: str) -> bool:
        """Route a typed prompt to the live coach; False if no pipeline runs."""

        return await self._push_context_message(session_id, prompt)

    async def _push_context_message(
        self, session_id: str, content: str, run_llm: bool = True
    ) -> bool:
        active = self._active_sessions.get(session_id)
        if active is None:
            return False
        frame = active.llm_messages_append_frame_cls(
            messages=[{"role": "user", "content": content}],
            run_llm=run_llm,
        )
        try:
            await active.task.queue_frames([frame])
        except Exception:
            log.exception("context_message_push_failed", session_id=session_id)
            return False
        return True

    async def execute_narrated_action(self, session_id: str, spec: str) -> None:
        """Run one inline-marker action fired by the speech timeline.

        Never raises: a malformed or illegal marker is traced and dropped so
        the narration keeps flowing.
        """

        action = parse_action_spec(spec)
        if action is None:
            return
        trace_name = f"narrate:{action.verb}"
        try:
            if action.verb == "move" and action.args:
                arguments = move_arguments(" ".join(action.args))
                result = await self._session_manager.agent_apply_move(session_id, **arguments)
                summary = f"Played {result['move']['san']} on the spoken word."
            elif action.verb == "var" and action.args:
                arguments = move_arguments(" ".join(action.args))
                result = await self._session_manager.agent_play_variation_move(
                    session_id, **arguments
                )
                summary = f"Sideline continues with {result['move']['san']}."
            elif action.verb == "next":
                try:
                    await self._session_manager.agent_review_step(session_id, 1)
                except BoardCommandError as exc:
                    # The classic miss: the game was loaded live (final
                    # position) and the coach forgot [[goto 0]]. Its narration
                    # expects the first move, so recover by reviewing ply 1.
                    snapshot = self._session_manager.get_board_state(session_id)
                    if (
                        exc.code == "invalid_ply"
                        and snapshot.view_mode == "live"
                        and snapshot.move_history
                    ):
                        await self._session_manager.agent_go_to_ply(session_id, 1)
                    else:
                        raise
                summary = "Advanced the reviewed game by one move."
            elif action.verb == "prev":
                await self._session_manager.agent_review_step(session_id, -1)
                summary = "Stepped the reviewed game one move back."
            elif action.verb == "goto" and action.args:
                try:
                    ply = int(action.args[0])
                except ValueError:
                    log.warning("narrated_action_bad_ply", session_id=session_id, spec=spec)
                    return
                await self._session_manager.agent_go_to_ply(session_id, ply)
                summary = f"Jumped to ply {ply}."
            elif action.verb == "reset":
                await self._session_manager.agent_reset(session_id)
                summary = "Board reset."
            elif action.verb == "endvar":
                await self._session_manager.agent_end_variation(session_id)
                summary = "Back to the reviewed game."
            elif action.verb == "clear":
                await self._session_manager.agent_clear_highlights(session_id)
                summary = "Highlights cleared."
            elif action.verb == "highlight" and action.args:
                await self._session_manager.agent_set_highlights(
                    session_id,
                    [
                        BoardHighlight(
                            id="narration-highlight",
                            squares=[square.lower() for square in action.args],
                            color="green",
                            label=None,
                        )
                    ],
                )
                summary = f"Highlighted {', '.join(action.args)}."
            else:
                log.warning("narrated_action_unknown", session_id=session_id, spec=spec)
                return
        except BoardCommandError as exc:
            log.info("narrated_action_rejected", session_id=session_id, spec=spec, code=exc.code)
            await self._session_manager.trace_tool_call(
                session_id, trace_name, "completed", f"Rejected: {exc.message}", {"spec": spec}
            )
            # Markers have no result_callback: without this note the model
            # keeps narrating while the board silently stays behind.
            await self._push_context_message(
                session_id,
                f"[Tablero] Tu marca [[{spec}]] falló ({exc.message}). El tablero NO "
                "cambió: corrige el rumbo en tu próxima intervención.",
                run_llm=False,
            )
            return
        except Exception:
            log.exception("narrated_action_failed", session_id=session_id, spec=spec)
            return

        await self._session_manager.trace_tool_call(
            session_id, trace_name, "completed", summary, {"spec": spec}
        )

    async def _speak(self, session_id: str, text: str) -> bool:
        """Queue server-driven narration into the running pipeline's TTS."""

        active = self._active_sessions.get(session_id)
        if active is None or active.tts_speak_frame_cls is None:
            return False
        try:
            await active.task.queue_frames([active.tts_speak_frame_cls(text=text)])
        except Exception:
            log.exception("tool_narration_failed", session_id=session_id)
            return False
        return True

    async def _supersede_active_session(self, session_id: str) -> None:
        """Cancel a previous pipeline for this session before starting a new one."""

        active = self._active_sessions.pop(session_id, None)
        if active is None:
            return
        log.info("voice_pipeline_superseded", session_id=session_id)
        try:
            await active.task.cancel()
        except Exception:
            log.exception("voice_pipeline_cancel_failed", session_id=session_id)

    async def run_transport(self, session_id: str, transport: Any) -> None:
        """Start a Pipecat pipeline for a transport."""

        transport_started_at = time.monotonic()
        await self._supersede_active_session(session_id)

        runtime = self._load_runtime()
        FunctionSchema = runtime["FunctionSchema"]
        ToolsSchema = runtime["ToolsSchema"]
        LLMContext = runtime["LLMContext"]
        LLMContextAggregatorPair = runtime["LLMContextAggregatorPair"]
        LLMUserAggregatorParams = runtime["LLMUserAggregatorParams"]
        LLMMessagesAppendFrame = runtime["LLMMessagesAppendFrame"]
        LocalSmartTurnAnalyzerV3 = runtime["LocalSmartTurnAnalyzerV3"]
        SileroVADAnalyzer = runtime["SileroVADAnalyzer"]
        VADParams = runtime["VADParams"]
        UserTurnStrategies = runtime["UserTurnStrategies"]
        TurnAnalyzerUserTurnStopStrategy = runtime["TurnAnalyzerUserTurnStopStrategy"]
        Pipeline = runtime["Pipeline"]
        PipelineTask = runtime["PipelineTask"]
        PipelineParams = runtime["PipelineParams"]
        PipelineRunner = runtime["PipelineRunner"]
        LLMRunFrame = runtime["LLMRunFrame"]
        TranscriptProcessor = runtime["TranscriptProcessor"]
        BaseObserver = runtime["BaseObserver"]
        UserStartedSpeakingFrame = runtime["UserStartedSpeakingFrame"]
        UserStoppedSpeakingFrame = runtime["UserStoppedSpeakingFrame"]
        BotStartedSpeakingFrame = runtime["BotStartedSpeakingFrame"]
        BotStoppedSpeakingFrame = runtime["BotStoppedSpeakingFrame"]
        LLMFullResponseStartFrame = runtime["LLMFullResponseStartFrame"]
        LLMFullResponseEndFrame = runtime["LLMFullResponseEndFrame"]
        LLMTextFrame = runtime["LLMTextFrame"]
        InterruptionFrame = runtime["InterruptionFrame"]
        TTSSpeakFrame = runtime["TTSSpeakFrame"]
        TTSTextFrame = runtime["TTSTextFrame"]
        FrameProcessor = runtime["FrameProcessor"]

        pacer = SpeechPacer()
        self._speech_pacers[session_id] = pacer

        stt = self._build_stt(runtime)
        tts = self._build_tts(runtime)
        llm = self._build_llm(runtime)

        llm.register_function("get_board_state", self._tool_get_board_state(session_id))
        llm.register_function("load_position", self._tool_load_position(session_id))
        llm.register_function("load_pgn", self._tool_load_pgn(session_id))
        llm.register_function("make_move", self._tool_make_move(session_id))
        llm.register_function("undo_move", self._tool_undo_move(session_id))
        llm.register_function("reset_board", self._tool_reset_board(session_id))
        llm.register_function("set_highlight", self._tool_set_highlights(session_id))
        llm.register_function("set_highlights", self._tool_set_highlights(session_id))
        llm.register_function("clear_highlights", self._tool_clear_highlights(session_id))
        llm.register_function("set_annotations", self._tool_set_annotations(session_id))
        llm.register_function("analyze_position", self._tool_analyze_position(session_id))
        llm.register_function("evaluate_move", self._tool_evaluate_move(session_id))
        llm.register_function("show_next_move", self._tool_show_next_move(session_id))
        llm.register_function("show_previous_move", self._tool_show_previous_move(session_id))
        llm.register_function("go_to_move", self._tool_go_to_move(session_id))
        llm.register_function("return_to_live", self._tool_return_to_live(session_id))
        llm.register_function("play_variation_move", self._tool_play_variation_move(session_id))
        llm.register_function("end_variation", self._tool_end_variation(session_id))

        tools = ToolsSchema(
            standard_tools=[
                FunctionSchema(
                    name="get_board_state",
                    description="Return the current board state, turn, FEN, PGN and move history.",
                    properties={},
                    required=[],
                ),
                FunctionSchema(
                    name="load_position",
                    description="Replace the current board with a FEN position.",
                    properties={"fen": {"type": "string", "description": "A valid FEN string."}},
                    required=["fen"],
                ),
                FunctionSchema(
                    name="load_pgn",
                    description="Load a PGN and optionally jump to a specific ply.",
                    properties={
                        "pgn": {"type": "string", "description": "A valid PGN string."},
                        "start_ply": {
                            "type": "integer",
                            "description": "Optional ply to review from after loading the PGN.",
                        },
                    },
                    required=["pgn"],
                ),
                FunctionSchema(
                    name="make_move",
                    description=(
                        "Play one legal move on the live board. Give coordinate squares "
                        "or SAN. Call once per move, right after announcing it out loud."
                    ),
                    properties={
                        "from_square": {"type": "string", "description": "From square like e2."},
                        "to_square": {"type": "string", "description": "To square like e4."},
                        "san": {
                            "type": "string",
                            "description": "The move in standard algebraic notation, like Nf3 or O-O. Alternative to coordinates.",
                        },
                        "promotion": {
                            "type": "string",
                            "enum": ["queen", "rook", "bishop", "knight"],
                            "description": "Promotion piece when needed.",
                        },
                    },
                    required=[],
                ),
                FunctionSchema(
                    name="reset_board",
                    description="Reset the board to the default initial position.",
                    properties={},
                    required=[],
                ),
                FunctionSchema(
                    name="undo_move",
                    description="Undo the latest live move on the board.",
                    properties={},
                    required=[],
                ),
                FunctionSchema(
                    name="set_highlight",
                    description="Highlight one or more squares on the board.",
                    properties={
                        "squares": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Squares to highlight.",
                        },
                        "color": {
                            "type": "string",
                            "enum": ["green", "yellow", "red", "blue"],
                            "description": "Highlight color.",
                        },
                        "label": {"type": "string", "description": "Optional label."},
                    },
                    required=["squares", "color"],
                ),
                FunctionSchema(
                    name="set_highlights",
                    description="Highlight one or more squares on the board.",
                    properties={
                        "squares": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Squares to highlight.",
                        },
                        "color": {
                            "type": "string",
                            "enum": ["green", "yellow", "red", "blue"],
                            "description": "Highlight color.",
                        },
                        "label": {"type": "string", "description": "Optional label."},
                    },
                    required=["squares", "color"],
                ),
                FunctionSchema(
                    name="clear_highlights",
                    description="Clear all highlights from the board.",
                    properties={},
                    required=[],
                ),
                FunctionSchema(
                    name="set_annotations",
                    description="Add board annotations such as comments, arrows or circles.",
                    properties={
                        "annotations": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Annotation payloads.",
                        }
                    },
                    required=["annotations"],
                ),
                FunctionSchema(
                    name="analyze_position",
                    description=(
                        "Run a chess engine on the current board position to get the "
                        "objectively best move and evaluation. Use this before proposing a "
                        "strong move or judging who stands better; never guess engine-level "
                        "analysis yourself."
                    ),
                    properties={},
                    required=[],
                ),
                FunctionSchema(
                    name="evaluate_move",
                    description=(
                        "Fast engine verdict (~a quarter second) for ONE concrete move in "
                        "the position currently on the board: evaluation, best "
                        "alternative, centipawn loss and a verdict (excelente/buena/"
                        "imprecisión/error/blunder). Use it while reviewing a game to "
                        "judge the move you are about to comment, or when the student "
                        "asks about a specific move. For a full position assessment use "
                        "analyze_position instead."
                    ),
                    properties={
                        "san": {
                            "type": "string",
                            "description": "The move to judge, in SAN like Nf3 (or UCI like g1f3).",
                        },
                        "from_square": {"type": "string", "description": "From square like e2."},
                        "to_square": {"type": "string", "description": "To square like e4."},
                    },
                    required=[],
                ),
                FunctionSchema(
                    name="show_next_move",
                    description=(
                        "Advance the reviewed game by exactly one move so the student sees "
                        "it played on the board — both sides advance this way. Use after "
                        "load_pgn to walk through a game move by move; announce the move's "
                        "idea out loud first, then call this once."
                    ),
                    properties={},
                    required=[],
                ),
                FunctionSchema(
                    name="show_previous_move",
                    description="Step the reviewed game one move backwards on the board.",
                    properties={},
                    required=[],
                ),
                FunctionSchema(
                    name="go_to_move",
                    description=(
                        "Jump the review to a specific ply (half-move). Ply 0 shows the "
                        "starting position; ply 2 is after Black's first move."
                    ),
                    properties={
                        "ply": {"type": "integer", "description": "Target ply, starting at 0."}
                    },
                    required=["ply"],
                ),
                FunctionSchema(
                    name="return_to_live",
                    description="Leave review mode and show the live game position again.",
                    properties={},
                    required=[],
                ),
                FunctionSchema(
                    name="play_variation_move",
                    description=(
                        "While reviewing a game, play a hypothetical sideline move on the "
                        "board without changing the recorded game. Call once per move; you "
                        "may move for both sides to walk a whole line. Use end_variation "
                        "to return to the game."
                    ),
                    properties={
                        "from_square": {"type": "string", "description": "From square like e2."},
                        "to_square": {"type": "string", "description": "To square like e4."},
                        "san": {
                            "type": "string",
                            "description": "The move in standard algebraic notation, like Nf3. Alternative to coordinates.",
                        },
                        "promotion": {
                            "type": "string",
                            "enum": ["queen", "rook", "bishop", "knight"],
                            "description": "Promotion piece when needed.",
                        },
                    },
                    required=[],
                ),
                FunctionSchema(
                    name="end_variation",
                    description=(
                        "Remove the sideline from the board and return to the reviewed "
                        "game position."
                    ),
                    properties={},
                    required=[],
                ),
            ]
        )

        # Every board-changing tool accepts `say`: the narration travels with
        # the tool call, so the server can speak it and hold the move until
        # the audio lands — regardless of whether the model streamed text.
        for schema in tools.standard_tools:
            if schema.name in PACED_TOOL_NAMES:
                schema.properties["say"] = dict(_SAY_PROPERTY)

        context = LLMContext(self._initial_messages(), tools)
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=UserTurnStrategies(
                    stop=[
                        TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())
                    ]
                ),
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            ),
        )

        transcript = TranscriptProcessor()

        @transcript.event_handler("on_transcript_update")
        async def on_transcript_update(_processor: Any, frame: Any) -> None:
            for message in frame.messages:
                role = getattr(message, "role", None)
                content = getattr(message, "content", None)
                if not content or role not in ("user", "assistant"):
                    continue
                await self._session_manager.add_conversation_message(session_id, role, content)

        orchestrator = self
        marker_parser = StreamMarkerParser()
        choreography = ChoreographyState()

        class _NarrationMarkerProcessor(FrameProcessor):  # type: ignore[misc, valid-type]
            """Strip inline [[action]] markers from the LLM stream before TTS.

            Each stripped marker is registered as a cue anchored to its offset
            in the clean narration text, tagged with the generation sequence.
            """

            async def process_frame(self, frame: Any, direction: Any) -> None:
                await super().process_frame(frame, direction)
                if isinstance(frame, LLMFullResponseStartFrame):
                    marker_parser.reset()
                    choreography.on_generation_start()
                    await self.push_frame(frame, direction)
                    return
                if isinstance(frame, LLMTextFrame):
                    clean, cues = marker_parser.feed(frame.text)
                    for cue in cues:
                        cue.sequence = choreography.generation_sequence
                        choreography.register(cue)
                    if clean:
                        await self.push_frame(LLMTextFrame(text=clean), direction)
                    return
                if isinstance(frame, LLMFullResponseEndFrame):
                    remainder = marker_parser.flush()
                    if remainder:
                        await self.push_frame(LLMTextFrame(text=remainder), direction)
                    await self.push_frame(frame, direction)
                    return
                if isinstance(frame, InterruptionFrame):
                    marker_parser.reset()
                await self.push_frame(frame, direction)

        class _ActionSchedulerProcessor(FrameProcessor):  # type: ignore[misc, valid-type]
            """Fire narrated actions as their anchor words are actually spoken.

            Sits after the output transport, where word-timestamped
            TTSTextFrames arrive on the playout clock and control frames are
            ordered with the audio stream.
            """

            async def process_frame(self, frame: Any, direction: Any) -> None:
                await super().process_frame(frame, direction)
                if isinstance(frame, TTSTextFrame):
                    for cue in choreography.on_word_spoken(frame.text):
                        await orchestrator.execute_narrated_action(session_id, cue.spec)
                elif isinstance(frame, LLMFullResponseStartFrame):
                    choreography.on_playout_start()
                elif isinstance(frame, BotStoppedSpeakingFrame):
                    for cue in choreography.drain():
                        await orchestrator.execute_narrated_action(session_id, cue.spec)
                elif isinstance(frame, InterruptionFrame):
                    choreography.clear()
                await self.push_frame(frame, direction)

        narration_enabled = self._settings.narrated_actions_enabled
        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                transcript.user(),
                user_aggregator,
                llm,
                *([_NarrationMarkerProcessor()] if narration_enabled else []),
                tts,
                transport.output(),
                *([_ActionSchedulerProcessor()] if narration_enabled else []),
                transcript.assistant(),
                assistant_aggregator,
            ]
        )

        session_manager = self._session_manager
        first_audio_logged = False

        class _BoardBridgeObserver(BaseObserver):  # type: ignore[misc, valid-type]
            """Mirror real turn-taking frames onto the board channel and pacer."""

            def __init__(self) -> None:
                super().__init__()
                self._last_state: str | None = None

            async def on_push_frame(self, data: Any) -> None:
                frame = data.frame
                if isinstance(frame, UserStartedSpeakingFrame):
                    await self._set_state("listening")
                elif isinstance(frame, UserStoppedSpeakingFrame):
                    await self._set_state("thinking")
                elif isinstance(frame, BotStartedSpeakingFrame):
                    nonlocal first_audio_logged
                    if not first_audio_logged:
                        first_audio_logged = True
                        log.info(
                            "voice_first_audio",
                            session_id=session_id,
                            seconds_since_transport=round(
                                time.monotonic() - transport_started_at, 3
                            ),
                        )
                    pacer.on_bot_started_speaking()
                    await self._set_state("speaking")
                elif isinstance(frame, BotStoppedSpeakingFrame):
                    pacer.on_bot_stopped_speaking()
                    await self._set_state("listening")
                elif isinstance(frame, LLMFullResponseStartFrame):
                    pacer.on_llm_response_start()
                elif isinstance(frame, LLMTextFrame):
                    pacer.on_llm_text()
                elif isinstance(frame, InterruptionFrame):
                    pacer.on_interruption()

            async def _set_state(self, state: str) -> None:
                if state == self._last_state:
                    return
                self._last_state = state
                await session_manager.set_conversation_state(session_id, state)  # type: ignore[arg-type]

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
                audio_out_sample_rate=24000,
            ),
            observers=[_BoardBridgeObserver()],
            # The browser client is a plain RTCPeerConnection without a data
            # channel: RTVI app messages would only pile up in the transport
            # queue ("Message queue is full" warnings) and get discarded.
            enable_rtvi=False,
        )
        self._active_sessions[session_id] = _ActiveSession(
            task=task,
            llm_messages_append_frame_cls=LLMMessagesAppendFrame,
            tts_speak_frame_cls=TTSSpeakFrame,
        )
        log.info(
            "voice_pipeline_ready",
            session_id=session_id,
            seconds_since_transport=round(time.monotonic() - transport_started_at, 3),
        )

        initial_turn_started = False

        async def start_initial_turn(trigger: str) -> None:
            nonlocal initial_turn_started
            if initial_turn_started:
                return
            initial_turn_started = True
            log.info("voice_initial_turn_started", session_id=session_id, trigger=trigger)
            # The opening move depends on the board the student prepared: a
            # loaded position or game takes priority over the auto demo, which
            # only plays on a pristine board.
            if not await self._kick_off_initial_turn(session_id):
                await task.queue_frames([LLMRunFrame()])

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client) -> None:
            log.info("voice_client_connected", session_id=session_id)
            asyncio.create_task(start_initial_turn("transport_client_connected"))

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client) -> None:
            log.info("voice_client_disconnected", session_id=session_id)
            await task.cancel()

        active_session = self._active_sessions[session_id]
        try:
            runner = PipelineRunner(handle_sigint=False)
            await runner.run(task)
        except Exception:
            log.exception("voice_pipeline_failed", session_id=session_id)
        finally:
            if self._active_sessions.get(session_id) is active_session:
                del self._active_sessions[session_id]
            if self._speech_pacers.get(session_id) is pacer:
                del self._speech_pacers[session_id]

    def _build_stt(self, runtime: dict[str, Any]) -> Any:
        if self._settings.stt_provider != "deepgram":
            raise SignalingRuntimeError(f"Unsupported STT provider: {self._settings.stt_provider}")
        DeepgramSTTService = runtime["DeepgramSTTService"]
        if not self._settings.deepgram_api_key:
            raise SignalingRuntimeError("VOICE_CHESS_DEEPGRAM_API_KEY is required.")
        stt_settings: dict[str, Any] = {"language": self._settings.stt_language}
        if self._settings.stt_model:
            stt_settings["model"] = self._settings.stt_model
        return DeepgramSTTService(
            api_key=self._settings.deepgram_api_key,
            settings=DeepgramSTTService.Settings(**stt_settings),
        )

    def _build_tts(self, runtime: dict[str, Any]) -> Any:
        if self._settings.tts_provider == "elevenlabs":
            ElevenLabsTTSService = runtime["ElevenLabsTTSService"]
            if not self._settings.elevenlabs_api_key:
                raise SignalingRuntimeError("VOICE_CHESS_ELEVENLABS_API_KEY is required.")
            return ElevenLabsTTSService(
                api_key=self._settings.elevenlabs_api_key,
                voice_id=self._settings.elevenlabs_voice_id,
            )

        if self._settings.tts_provider == "cartesia":
            CartesiaTTSService = runtime["CartesiaTTSService"]
            if not self._settings.cartesia_api_key:
                raise SignalingRuntimeError("VOICE_CHESS_CARTESIA_API_KEY is required.")
            return CartesiaTTSService(
                api_key=self._settings.cartesia_api_key,
                settings=CartesiaTTSService.Settings(
                    voice=self._settings.cartesia_voice_id,
                    model=self._settings.cartesia_model,
                    language=self._resolve_language(runtime),
                ),
            )

        raise SignalingRuntimeError(f"Unsupported TTS provider: {self._settings.tts_provider}")

    def _resolve_language(self, runtime: dict[str, Any]) -> Any:
        Language = runtime["Language"]
        try:
            return Language(self._settings.language)
        except ValueError:
            log.warning("unknown_language_fallback_en", language=self._settings.language)
            return Language.EN

    def _build_llm(self, runtime: dict[str, Any]) -> Any:
        if self._settings.llm_provider != "openai":
            raise SignalingRuntimeError(f"Unsupported LLM provider: {self._settings.llm_provider}")
        OpenAILLMService = runtime["OpenAILLMService"]
        if not self._settings.openai_api_key:
            raise SignalingRuntimeError("VOICE_CHESS_OPENAI_API_KEY is required.")
        return OpenAILLMService(
            api_key=self._settings.openai_api_key,
            settings=OpenAILLMService.Settings(
                model=self._settings.llm_model,
                extra=self._llm_extra_params(),
            ),
        )

    def _llm_extra_params(self) -> dict[str, Any]:
        """Provider params beyond what pipecat models natively.

        `parallel_tool_calls=False` keeps one tool call per completion —
        batched parallel calls would put several moves on the board within a
        single breath. The GPT-5 knobs default to the low-latency combination
        for live voice and are omitted for non-GPT-5 models, which reject
        them.
        """

        extra: dict[str, Any] = {"parallel_tool_calls": False}
        is_gpt5 = self._settings.llm_model.startswith("gpt-5")
        reasoning_effort = self._settings.llm_reasoning_effort or ("minimal" if is_gpt5 else None)
        verbosity = self._settings.llm_verbosity or ("low" if is_gpt5 else None)
        if reasoning_effort:
            extra["reasoning_effort"] = reasoning_effort
        if verbosity:
            extra["verbosity"] = verbosity
        return extra

    def _tool_handler(
        self,
        session_id: str,
        tool_name: str,
        *,
        started_summary: str,
        action: ToolAction,
        completed_summary: ToolSummary,
        pace_with_speech: bool = False,
    ):
        """Wrap a tool action with tracing and defensive error handling.

        A tool that raises leaves `result_callback` uncalled, which hangs the
        assistant's turn instead of letting it recover verbally. Every failure
        mode here is turned into a compact error payload the LLM can react to.

        With `pace_with_speech`, board mutations wait for the assistant's
        voice to land first (see SpeechPacer), so the piece moves while the
        coach is saying it instead of seconds before the audio arrives.
        """

        async def tool(params) -> None:
            arguments = dict(params.arguments) if params.arguments else {}
            if pace_with_speech and self._settings.speech_pacing_enabled:
                speech_pacer = self._speech_pacers.get(session_id)
                if speech_pacer is not None:
                    # Weak models sometimes leak [[...]] markers into `say`;
                    # they must never be read aloud.
                    say = strip_markers(arguments.get("say") or "").strip()
                    timeout = self._settings.speech_pacing_wait_timeout_seconds
                    lead = self._settings.speech_pacing_lead_seconds
                    if say and not speech_pacer.turn_has_text:
                        # The model narrated inside the tool call instead of
                        # streaming text: speak it ourselves, then hold the
                        # board change until that audio starts.
                        if await self._speak(session_id, say):
                            await speech_pacer.await_speaking(timeout=timeout, lead=lead)
                    else:
                        await speech_pacer.await_speech_lead(timeout=timeout, lead=lead)
            await self._session_manager.trace_tool_call(
                session_id, tool_name, "started", started_summary, arguments
            )
            try:
                result = await action(arguments)
            except BoardCommandError as exc:
                log.info(
                    "tool_call_rejected",
                    session_id=session_id,
                    tool=tool_name,
                    code=exc.code,
                )
                await self._session_manager.trace_tool_call(
                    session_id, tool_name, "completed", f"Rejected: {exc.message}", arguments
                )
                await params.result_callback({"error": {"code": exc.code, "message": exc.message}})
                return
            except (KeyError, ValueError, TypeError) as exc:
                log.warning(
                    "tool_call_bad_arguments",
                    session_id=session_id,
                    tool=tool_name,
                    error=str(exc),
                )
                await self._session_manager.trace_tool_call(
                    session_id,
                    tool_name,
                    "completed",
                    f"Rejected: invalid arguments ({exc}).",
                    arguments,
                )
                await params.result_callback(
                    {"error": {"code": "invalid_arguments", "message": str(exc)}}
                )
                return
            except Exception:
                log.exception("tool_call_failed", session_id=session_id, tool=tool_name)
                await self._session_manager.trace_tool_call(
                    session_id,
                    tool_name,
                    "completed",
                    "Internal error while running this tool.",
                    arguments,
                )
                await params.result_callback(
                    {
                        "error": {
                            "code": "internal_error",
                            "message": "Internal error while running this tool.",
                        }
                    }
                )
                return

            await self._session_manager.trace_tool_call(
                session_id, tool_name, "completed", completed_summary(arguments, result), arguments
            )
            await params.result_callback(result)

        return tool

    def _tool_get_board_state(self, session_id: str):
        async def action(_arguments: dict[str, Any]) -> dict[str, Any]:
            snapshot = self._session_manager.get_board_state(session_id)
            return snapshot.model_dump(by_alias=True, mode="json")

        return self._tool_handler(
            session_id,
            "get_board_state",
            started_summary="Inspecting the current board state.",
            action=action,
            completed_summary=lambda _args, result: (
                f"Fetched the live board with {len(result.get('moveHistory', []))} moves."
            ),
        )

    def _tool_load_position(self, session_id: str):
        async def action(arguments: dict[str, Any]) -> dict[str, Any]:
            fen = arguments.get("fen")
            if not fen:
                raise BoardCommandError("missing_fen", "A FEN string is required.")
            return await self._session_manager.agent_load_fen(session_id, fen=fen)

        return self._tool_handler(
            session_id,
            "load_position",
            started_summary="Loading a FEN position.",
            action=action,
            completed_summary=lambda _args, _result: "FEN position loaded.",
            pace_with_speech=True,
        )

    def _tool_load_pgn(self, session_id: str):
        async def action(arguments: dict[str, Any]) -> dict[str, Any]:
            pgn = arguments.get("pgn")
            if not pgn:
                raise BoardCommandError("missing_pgn", "A PGN string is required.")
            return await self._session_manager.agent_load_pgn(
                session_id, pgn=pgn, start_ply=arguments.get("start_ply")
            )

        return self._tool_handler(
            session_id,
            "load_pgn",
            started_summary="Loading a PGN line.",
            action=action,
            completed_summary=lambda _args, _result: "PGN line loaded.",
            pace_with_speech=True,
        )

    def _tool_make_move(self, session_id: str):
        async def action(arguments: dict[str, Any]) -> dict[str, Any]:
            return await self._session_manager.agent_apply_move(
                session_id,
                from_square=arguments.get("from_square"),
                to_square=arguments.get("to_square"),
                promotion=arguments.get("promotion"),
                san=arguments.get("san"),
            )

        return self._tool_handler(
            session_id,
            "make_move",
            started_summary="Applying a move on the board.",
            action=action,
            completed_summary=lambda _args, result: f"Applied {result['move']['san']}.",
            pace_with_speech=True,
        )

    def _tool_show_next_move(self, session_id: str):
        async def action(_arguments: dict[str, Any]) -> dict[str, Any]:
            return await self._session_manager.agent_review_step(session_id, 1)

        return self._tool_handler(
            session_id,
            "show_next_move",
            started_summary="Advancing the reviewed game by one move.",
            action=action,
            completed_summary=lambda _args, result: (
                f"Showed {((result.get('board') or {}).get('lastMove') or {}).get('san', 'the position')}."
            ),
            pace_with_speech=True,
        )

    def _tool_show_previous_move(self, session_id: str):
        async def action(_arguments: dict[str, Any]) -> dict[str, Any]:
            return await self._session_manager.agent_review_step(session_id, -1)

        return self._tool_handler(
            session_id,
            "show_previous_move",
            started_summary="Stepping the reviewed game one move back.",
            action=action,
            completed_summary=lambda _args, _result: "Stepped one move back.",
            pace_with_speech=True,
        )

    def _tool_go_to_move(self, session_id: str):
        async def action(arguments: dict[str, Any]) -> dict[str, Any]:
            ply = arguments.get("ply")
            if ply is None:
                raise BoardCommandError("missing_ply", "A target ply is required.")
            return await self._session_manager.agent_go_to_ply(session_id, int(ply))

        return self._tool_handler(
            session_id,
            "go_to_move",
            started_summary="Jumping to a position in the reviewed game.",
            action=action,
            completed_summary=lambda args, _result: f"Jumped to ply {args.get('ply')}.",
            pace_with_speech=True,
        )

    def _tool_return_to_live(self, session_id: str):
        async def action(_arguments: dict[str, Any]) -> dict[str, Any]:
            return await self._session_manager.agent_go_live(session_id)

        return self._tool_handler(
            session_id,
            "return_to_live",
            started_summary="Returning to the live position.",
            action=action,
            completed_summary=lambda _args, _result: "Back on the live board.",
            pace_with_speech=True,
        )

    def _tool_play_variation_move(self, session_id: str):
        async def action(arguments: dict[str, Any]) -> dict[str, Any]:
            return await self._session_manager.agent_play_variation_move(
                session_id,
                from_square=arguments.get("from_square"),
                to_square=arguments.get("to_square"),
                promotion=arguments.get("promotion"),
                san=arguments.get("san"),
            )

        return self._tool_handler(
            session_id,
            "play_variation_move",
            started_summary="Exploring a sideline move.",
            action=action,
            completed_summary=lambda _args, result: (
                f"Sideline continues with {result['move']['san']}."
            ),
            pace_with_speech=True,
        )

    def _tool_end_variation(self, session_id: str):
        async def action(_arguments: dict[str, Any]) -> dict[str, Any]:
            return await self._session_manager.agent_end_variation(session_id)

        return self._tool_handler(
            session_id,
            "end_variation",
            started_summary="Returning from the sideline.",
            action=action,
            completed_summary=lambda _args, _result: "Back to the reviewed game.",
            pace_with_speech=True,
        )

    def _tool_reset_board(self, session_id: str):
        async def action(_arguments: dict[str, Any]) -> dict[str, Any]:
            return await self._session_manager.agent_reset(session_id)

        return self._tool_handler(
            session_id,
            "reset_board",
            started_summary="Resetting the board to the initial position.",
            action=action,
            completed_summary=lambda _args, _result: "Board reset to the initial position.",
            pace_with_speech=True,
        )

    def _tool_undo_move(self, session_id: str):
        async def action(_arguments: dict[str, Any]) -> dict[str, Any]:
            return await self._session_manager.agent_undo_move(session_id)

        return self._tool_handler(
            session_id,
            "undo_move",
            started_summary="Undoing the latest move.",
            action=action,
            completed_summary=lambda _args, _result: "Latest move reverted.",
            pace_with_speech=True,
        )

    def _tool_set_highlights(self, session_id: str):
        async def action(arguments: dict[str, Any]) -> dict[str, Any]:
            squares = arguments.get("squares")
            color = arguments.get("color")
            if not squares or not color:
                raise BoardCommandError(
                    "missing_highlight_fields", "Both squares and color are required."
                )
            return await self._session_manager.agent_set_highlights(
                session_id,
                [
                    BoardHighlight(
                        id="agent-highlight",
                        squares=squares,
                        color=color,
                        label=arguments.get("label"),
                    )
                ],
            )

        return self._tool_handler(
            session_id,
            "set_highlight",
            started_summary="Highlighting target squares.",
            action=action,
            completed_summary=lambda args, _result: (
                f"Highlighted {', '.join(args.get('squares', []))}."
            ),
            pace_with_speech=True,
        )

    def _tool_clear_highlights(self, session_id: str):
        async def action(_arguments: dict[str, Any]) -> dict[str, Any]:
            return await self._session_manager.agent_clear_highlights(session_id)

        return self._tool_handler(
            session_id,
            "clear_highlights",
            started_summary="Clearing all highlights.",
            action=action,
            completed_summary=lambda _args, _result: "Board highlights cleared.",
            pace_with_speech=True,
        )

    def _tool_set_annotations(self, session_id: str):
        async def action(arguments: dict[str, Any]) -> dict[str, Any]:
            raw_annotations = arguments.get("annotations")
            if not raw_annotations:
                return {"annotations": [], "skipped": True}
            annotations = [BoardAnnotation(**annotation) for annotation in raw_annotations]
            return await self._session_manager.agent_set_annotations(session_id, annotations)

        return self._tool_handler(
            session_id,
            "set_annotations",
            started_summary="Adding board annotations.",
            action=action,
            completed_summary=lambda _args, result: (
                "Skipped annotation update because no annotations were provided."
                if result.get("skipped")
                else "Board annotations updated."
            ),
            pace_with_speech=True,
        )

    def _tool_analyze_position(self, session_id: str):
        async def action(_arguments: dict[str, Any]) -> dict[str, Any]:
            snapshot = self._session_manager.get_board_state(session_id)
            board = chess.Board(snapshot.fen)
            return await self._analyze_with_engine(board)

        return self._tool_handler(
            session_id,
            "analyze_position",
            started_summary="Running the chess engine on the current position.",
            action=action,
            completed_summary=lambda _args, result: (
                f"Engine suggests {result['bestMoveSan']} ({result['evaluation']})."
                if result.get("bestMoveSan")
                else "Engine analysis completed with no clear best move."
            ),
        )

    def _tool_evaluate_move(self, session_id: str):
        async def action(arguments: dict[str, Any]) -> dict[str, Any]:
            snapshot = self._session_manager.get_board_state(session_id)
            board = chess.Board(snapshot.fen)
            move_input = arguments.get("san") or (
                (arguments.get("from_square") or "") + (arguments.get("to_square") or "")
            )
            if not move_input:
                raise BoardCommandError("missing_move", "Provide the move as SAN or squares.")
            move_args = move_arguments(move_input)
            try:
                if move_args["san"]:
                    move = board.parse_san(move_args["san"])
                else:
                    move = chess.Move.from_uci(
                        f"{move_args['from_square']}{move_args['to_square']}"
                    )
            except ValueError as exc:
                raise BoardCommandError(
                    "illegal_move", f"'{move_input}' is not a legal move in this position."
                ) from exc
            if move not in board.legal_moves:
                raise BoardCommandError(
                    "illegal_move", f"'{move_input}' is not a legal move in this position."
                )
            return await self._evaluate_move_with_engine(board, move)

        return self._tool_handler(
            session_id,
            "evaluate_move",
            started_summary="Quick engine check on a move.",
            action=action,
            completed_summary=lambda _args, result: (
                f"{result['move']}: {result['verdict']}"
                + (
                    f" (pierde {result['centipawnLoss']} centipeones; mejor era {result['bestMoveSan']})"
                    if result.get("centipawnLoss") and result.get("bestMoveSan")
                    else ""
                )
            ),
        )

    async def _get_engine(self) -> Any:
        """Return the persistent UCI engine, starting it on first use.

        Spawning Stockfish per call cost 100ms+ before a single node was
        searched; one long-lived process (guarded by `_engine_lock`) makes
        quick evaluations actually quick.
        """

        path = self._settings.stockfish_path
        if not path:
            raise BoardCommandError(
                "engine_unavailable", "No chess engine is configured on this server."
            )
        if self._engine is not None:
            return self._engine
        try:
            _transport, engine = await chess.engine.popen_uci(path)
        except (FileNotFoundError, OSError) as exc:
            raise BoardCommandError(
                "engine_unavailable",
                f"Chess engine binary '{path}' is not available on this server.",
            ) from exc
        self._engine = engine
        return engine

    async def _engine_analyse(self, board: chess.Board, limit: Any) -> Any:
        """Analyse under the engine lock, restarting a dead engine once."""

        async with self._engine_lock:
            engine = await self._get_engine()
            try:
                return await engine.analyse(board, limit)
            except chess.engine.EngineError:
                log.warning("engine_restarting_after_error")
                self._engine = None
                engine = await self._get_engine()
                return await engine.analyse(board, limit)

    async def shutdown(self) -> None:
        """Release runtime resources (the persistent engine)."""

        engine, self._engine = self._engine, None
        if engine is not None:
            try:
                await engine.quit()
            except Exception:
                log.exception("engine_shutdown_failed")

    async def _analyze_with_engine(self, board: chess.Board) -> dict[str, Any]:
        limit = (
            chess.engine.Limit(time=self._settings.engine_move_time_seconds)
            if self._settings.engine_move_time_seconds
            else chess.engine.Limit(depth=self._settings.engine_analysis_depth)
        )
        info = await self._engine_analyse(board, limit)

        pv = info.get("pv") or []
        best_move = pv[0] if pv else None
        score = info.get("score")
        return {
            "fen": board.fen(),
            "bestMoveUci": best_move.uci() if best_move else None,
            "bestMoveSan": board.san(best_move) if best_move else None,
            "evaluation": self._format_engine_score(score, board.turn) if score else "unknown",
            "depth": info.get("depth"),
            "principalVariationSan": self._principal_variation_san(board, pv),
        }

    async def _evaluate_move_with_engine(
        self, board: chess.Board, move: chess.Move
    ) -> dict[str, Any]:
        """Fast verdict for one concrete move: centipawn loss vs the best move."""

        quick = chess.engine.Limit(time=self._settings.engine_quick_time_seconds)
        mover = board.turn

        best_info = await self._engine_analyse(board, quick)
        best_pv = best_info.get("pv") or []
        best_move = best_pv[0] if best_pv else None
        best_score = best_info.get("score")

        after = board.copy()
        after.push(move)
        played_info = await self._engine_analyse(after, quick)
        played_score = played_info.get("score")

        centipawn_loss: int | None = None
        if best_score is not None and played_score is not None:
            best_cp = best_score.pov(mover).score(mate_score=100_000)
            played_cp = played_score.pov(mover).score(mate_score=100_000)
            if best_cp is not None and played_cp is not None:
                centipawn_loss = max(0, best_cp - played_cp)

        return {
            "move": board.san(move),
            "evaluationAfter": (
                self._format_engine_score(played_score, mover) if played_score else "unknown"
            ),
            "bestMoveSan": board.san(best_move) if best_move else None,
            "bestEvaluation": (
                self._format_engine_score(best_score, mover) if best_score else "unknown"
            ),
            "centipawnLoss": centipawn_loss,
            "verdict": classify_centipawn_loss(centipawn_loss),
        }

    @staticmethod
    def _format_engine_score(score: Any, turn: bool) -> str:
        relative = score.pov(turn)
        if relative.is_mate():
            mate_in = relative.mate()
            return f"mate in {abs(mate_in)}" if mate_in else "mate"
        centipawns = relative.score()
        if centipawns is None:
            return "unknown"
        return f"{centipawns / 100:+.2f}"

    @staticmethod
    def _principal_variation_san(board: chess.Board, pv: list[Any]) -> list[str]:
        working = board.copy()
        sans: list[str] = []
        for move in pv[:6]:
            if move not in working.legal_moves:
                break
            sans.append(working.san(move))
            working.push(move)
        return sans

    def _initial_messages(self) -> list[dict[str, str]]:
        # The auto-demo prompt is NOT baked in here: the kick-off decision at
        # connect time (_kick_off_initial_turn) checks the board first, so a
        # position the student prepared beforehand wins over the demo.
        return [{"role": "system", "content": self._settings.system_prompt}]

    async def _kick_off_initial_turn(self, session_id: str) -> bool:
        """Choose the session opener based on the board the student prepared.

        Returns True when a context message (with run_llm) was pushed; the
        caller falls back to a plain LLM run (bare introduction) otherwise.
        """

        snapshot = self._session_manager.get_board_state(session_id)
        board_is_pristine = (
            snapshot.fen == chess.STARTING_FEN
            and not snapshot.move_history
            and snapshot.view_mode == "live"
        )

        if not board_is_pristine:
            if snapshot.pgn:
                start_ply = snapshot.review_ply if snapshot.view_mode == "review" else None
                return await self.notify_board_event(
                    session_id, "load_pgn", {"pgn": snapshot.pgn, "start_ply": start_ply}
                )
            return await self.notify_board_event(session_id, "load_fen", {"fen": snapshot.fen})

        if (
            self._settings.auto_start_demo_on_voice_connect
            and self._settings.auto_start_demo_prompt
        ):
            return await self._push_context_message(
                session_id, self._settings.auto_start_demo_prompt
            )

        return False

    def _load_runtime(self) -> dict[str, Any]:
        try:
            from pipecat.adapters.schemas.function_schema import FunctionSchema
            from pipecat.adapters.schemas.tools_schema import ToolsSchema
            from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            from pipecat.audio.vad.vad_analyzer import VADParams
            from pipecat.frames.frames import (
                BotStartedSpeakingFrame,
                BotStoppedSpeakingFrame,
                InterruptionFrame,
                LLMFullResponseEndFrame,
                LLMFullResponseStartFrame,
                LLMMessagesAppendFrame,
                LLMRunFrame,
                LLMTextFrame,
                TTSSpeakFrame,
                TTSTextFrame,
                UserStartedSpeakingFrame,
                UserStoppedSpeakingFrame,
            )
            from pipecat.observers.base_observer import BaseObserver
            from pipecat.pipeline.pipeline import Pipeline
            from pipecat.pipeline.runner import PipelineRunner
            from pipecat.pipeline.task import PipelineParams, PipelineTask
            from pipecat.processors.frame_processor import FrameProcessor
            from pipecat.transcriptions.language import Language
            from pipecat.processors.aggregators.llm_context import LLMContext
            from pipecat.processors.aggregators.llm_response_universal import (
                LLMContextAggregatorPair,
                LLMUserAggregatorParams,
            )
            from pipecat.processors.transcript_processor import TranscriptProcessor
            from pipecat.services.cartesia.tts import CartesiaTTSService
            from pipecat.services.deepgram.stt import DeepgramSTTService
            from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
            from pipecat.services.openai.llm import OpenAILLMService
            from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
            from pipecat.turns.user_turn_strategies import UserTurnStrategies
        except ImportError as exc:
            raise SignalingRuntimeError(
                "Pipecat voice runtime is not installed. Install the optional `voice` extras."
            ) from exc

        return {
            "BaseObserver": BaseObserver,
            "BotStartedSpeakingFrame": BotStartedSpeakingFrame,
            "BotStoppedSpeakingFrame": BotStoppedSpeakingFrame,
            "CartesiaTTSService": CartesiaTTSService,
            "DeepgramSTTService": DeepgramSTTService,
            "ElevenLabsTTSService": ElevenLabsTTSService,
            "FrameProcessor": FrameProcessor,
            "FunctionSchema": FunctionSchema,
            "InterruptionFrame": InterruptionFrame,
            "Language": Language,
            "LLMContext": LLMContext,
            "LLMContextAggregatorPair": LLMContextAggregatorPair,
            "LLMFullResponseEndFrame": LLMFullResponseEndFrame,
            "LLMFullResponseStartFrame": LLMFullResponseStartFrame,
            "LLMMessagesAppendFrame": LLMMessagesAppendFrame,
            "LLMRunFrame": LLMRunFrame,
            "LLMTextFrame": LLMTextFrame,
            "LLMUserAggregatorParams": LLMUserAggregatorParams,
            "LocalSmartTurnAnalyzerV3": LocalSmartTurnAnalyzerV3,
            "OpenAILLMService": OpenAILLMService,
            "Pipeline": Pipeline,
            "PipelineParams": PipelineParams,
            "PipelineRunner": PipelineRunner,
            "PipelineTask": PipelineTask,
            "SileroVADAnalyzer": SileroVADAnalyzer,
            "ToolsSchema": ToolsSchema,
            "TranscriptProcessor": TranscriptProcessor,
            "TTSSpeakFrame": TTSSpeakFrame,
            "TTSTextFrame": TTSTextFrame,
            "TurnAnalyzerUserTurnStopStrategy": TurnAnalyzerUserTurnStopStrategy,
            "UserStartedSpeakingFrame": UserStartedSpeakingFrame,
            "UserStoppedSpeakingFrame": UserStoppedSpeakingFrame,
            "UserTurnStrategies": UserTurnStrategies,
            "VADParams": VADParams,
        }
